"""Oracle transaction builder leveraging comprehensive validation utilities."""

import logging
from copy import deepcopy
from dataclasses import dataclass
from statistics import median

from pycardano import (
    Address,
    Asset,
    AssetName,
    ExtendedSigningKey,
    MultiAsset,
    PaymentSigningKey,
    ScriptHash,
    Transaction,
    TransactionOutput,
    UTxO,
)

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.models.oracle_datums import (
    AggregateMessage,
    Aggregation,
    AggStateDatum,
    AggStateVariant,
    NoRewards,
    OracleSettingsDatum,
    RewardAccountDatum,
    RewardAccountVariant,
    RewardConsensusPending,
    RewardTransportVariant,
    SomeAggStateDatum,
)
from charli3_offchain_core.models.oracle_redeemers import (
    CalculateRewards,
    OdvAggregate,
)
from charli3_offchain_core.oracle.exceptions import (
    StateValidationError,
    TransactionError,
    ValidationError,
)
from charli3_offchain_core.oracle.utils import (
    asset_checks,
    consensus,
    rewards,
    state_checks,
)

logger = logging.getLogger(__name__)


@dataclass
class OdvResult:
    """Result of ODV transaction."""

    transaction: Transaction
    transport_output: TransactionOutput
    agg_state_output: TransactionOutput


@dataclass
class RewardsResult:
    """Result of rewards calculation transaction."""

    transaction: Transaction
    new_transports: list[TransactionOutput]
    new_reward_account: TransactionOutput


class OracleTransactionBuilder:
    """Builder for Oracle transactions with comprehensive validation."""

    def __init__(
        self,
        tx_manager: TransactionManager,
        script_address: Address,
        policy_id: bytes,
        fee_token_hash: ScriptHash,
        fee_token_name: AssetName,
    ) -> None:
        """Initialize transaction builder.

        Args:
            tx_manager: Transaction manager
            script_address: Script address
            policy_id: Policy ID for tokens
        """
        self.tx_manager = tx_manager
        self.script_address = script_address
        self.policy_id = policy_id
        self.fee_token_hash = fee_token_hash
        self.fee_token_name = fee_token_name
        self.consensus_calculator = None
        self.reward_calculator = None
        self.reward_accumulator = rewards.RewardAccumulator()
        self.network_config = self.tx_manager.chain_query.config.network_config

    async def _get_script_utxos(self) -> list[UTxO]:
        """Get and validate UTxOs at script address."""
        try:
            utxos = await self.tx_manager.chain_query.get_utxos(self.script_address)
            if not utxos:
                raise ValidationError("No UTxOs found at script address")
            return utxos
        except Exception as e:
            raise TransactionError(f"Failed to get script UTxOs: {e}") from e

    async def build_odv_tx(
        self,
        message: AggregateMessage,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        change_address: Address | None = None,
    ) -> OdvResult:
        """Build ODV aggregation transaction with comprehensive validation.

        Args:
            message: Aggregate message to validate
            signing_key: Signing key for transaction
            change_address: Optional change address

        Returns:
            OdvResult containing transaction and outputs

        Raises:
            ValidationError: If validation fails
            TransactionError: If transaction building fails
        """
        try:
            # Get UTxOs and settings first
            utxos = await self._get_script_utxos()
            transport, agg_state = state_checks.find_transport_pair(
                utxos, self.policy_id
            )
            settings_datum, settings_utxo = (
                state_checks.get_oracle_settings_by_policy_id(utxos, self.policy_id)
            )
            script_utxo = state_checks.get_reference_script_utxo(utxos)

            # Update calculators with current settings
            self.consensus_calculator = consensus.ConsensusCalculator(settings_datum)
            self.reward_calculator = rewards.RewardCalculator(settings_datum.fee_info)

            # Calculate the transaction time window and current time ONCE
            validity_start = (
                self.tx_manager.chain_query.get_current_posix_chain_time_ms()
            )
            validity_end = validity_start + settings_datum.time_absolute_uncertainty
            current_time = (validity_end + validity_start) // 2

            validity_start_slot = self.network_config.posix_to_slot(validity_start)
            validity_end_slot = self.network_config.posix_to_slot(validity_end)

            # Create a new message with the current timestamp
            current_message = AggregateMessage(
                node_feeds_sorted_by_feed=message.node_feeds_sorted_by_feed,
                node_feeds_count=message.node_feeds_count,
                timestamp=current_time,
            )

            # Calculate median using the current message
            feeds = list(current_message.node_feeds_sorted_by_feed.values())
            median_value = int(median(feeds))

            # Calculate minimum fee
            minimum_fee = self.reward_calculator.calculate_min_fee_amount(
                len(current_message.node_feeds_sorted_by_feed)
            )

            # Create outputs using helper methods
            transport_output = self._create_transport_output(
                transport=transport,
                current_message=current_message,
                median_value=median_value,
                node_reward_price=settings_datum.fee_info.reward_prices.node_fee,
                minimum_fee=minimum_fee,
            )

            agg_state_output = self._create_agg_state_output(
                agg_state=agg_state,
                median_value=median_value,
                current_time=current_time,
                liveness_period=settings_datum.aggregation_liveness_period,
            )

            # Build and return transaction
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (transport, OdvAggregate(), script_utxo),
                    (agg_state, OdvAggregate(), script_utxo),
                ],
                script_outputs=[transport_output, agg_state_output],
                reference_inputs=[settings_utxo],
                required_signers=list(current_message.node_feeds_sorted_by_feed.keys()),
                change_address=change_address,
                signing_key=signing_key,
                validity_start=validity_start_slot,
                validity_end=validity_end_slot,
            )

            return OdvResult(tx, transport_output, agg_state_output)

        except Exception as e:
            raise TransactionError(f"Failed to build ODV transaction: {e}") from e

    async def build_rewards_tx(
        self,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        change_address: Address | None = None,
        max_inputs: int = 10,
    ) -> RewardsResult:
        """Build rewards calculation transaction with consensus processing.

        Args:
            signing_key: Signing key for transaction
            change_address: Optional change address
            max_inputs: Maximum number of transport inputs to process

        Returns:
            RewardsResult containing transaction and processing results

        Raises:
            ValidationError: If validation fails
            TransactionError: If transaction building fails
        """
        try:
            # Get and validate UTxOs
            utxos = await self._get_script_utxos()
            settings_datum, settings_utxo = (
                state_checks.get_oracle_settings_by_policy_id(utxos, self.policy_id)
            )
            script_utxo = state_checks.get_reference_script_utxo(utxos)

            # Update calculators with current settings
            self.consensus_calculator = consensus.ConsensusCalculator(settings_datum)
            self.reward_calculator = rewards.RewardCalculator(settings_datum.fee_info)

            # Find pending transports
            pending_transports = state_checks.filter_pending_transports(
                asset_checks.filter_utxos_by_token_name(
                    utxos, self.policy_id, "RewardTransport"
                )
            )[:max_inputs]
            if not pending_transports:
                raise StateValidationError("No pending transport UTxOs found")

            # Find reward account
            _, reward_account_utxo = state_checks.get_reward_account_by_policy_id(
                utxos, self.policy_id
            )

            # Create new transport outputs
            new_transports = [
                self._create_empty_transport(transport)
                for transport in pending_transports
            ]

            # Create new reward account output
            reward_account_output = self._create_reward_account(
                reward_account_utxo, pending_transports, settings_datum
            )

            # Build transaction
            script_inputs = [
                (t, CalculateRewards(), script_utxo) for t in pending_transports
            ]
            script_inputs.append((reward_account_utxo, CalculateRewards(), script_utxo))

            tx = await self.tx_manager.build_script_tx(
                script_inputs=script_inputs,
                script_outputs=[*new_transports, reward_account_output],
                reference_inputs=[settings_utxo],
                change_address=change_address,
                signing_key=signing_key,
            )

            return RewardsResult(
                transaction=tx,
                new_transports=new_transports,
                new_reward_account=reward_account_output,
            )

        except Exception as e:
            raise TransactionError(f"Failed to build rewards transaction: {e}") from e

    def _create_transport_output(
        self,
        transport: UTxO,
        current_message: AggregateMessage,
        median_value: int,
        node_reward_price: int,
        minimum_fee: int,
    ) -> TransactionOutput:
        """Helper method to create transport output with consistent data."""
        transport_output = deepcopy(transport.output)

        # Add fees to output
        if (
            self.fee_token_hash in transport_output.amount.multi_asset
            and self.fee_token_name
            in transport_output.amount.multi_asset[self.fee_token_hash]
        ):
            transport_output.amount.multi_asset[self.fee_token_hash][
                self.fee_token_name
            ] += minimum_fee
        else:
            fee_asset = MultiAsset(
                {self.fee_token_hash: Asset({self.fee_token_name: minimum_fee})}
            )
            transport_output.amount.multi_asset += fee_asset

        return TransactionOutput(
            address=self.script_address,
            amount=transport_output.amount,
            datum=RewardTransportVariant(
                datum=RewardConsensusPending(
                    aggregation=Aggregation(
                        oracle_feed=median_value,
                        message=current_message,
                        node_reward_price=node_reward_price,
                        rewards_amount_paid=minimum_fee,
                    )
                )
            ),
        )

    def _create_agg_state_output(
        self,
        agg_state: UTxO,
        median_value: int,
        current_time: int,
        liveness_period: int,
    ) -> TransactionOutput:
        """Helper method to create agg state output with consistent timestamp."""
        return TransactionOutput(
            address=self.script_address,
            amount=agg_state.output.amount,
            datum=AggStateVariant(
                datum=SomeAggStateDatum(
                    aggstate=AggStateDatum(
                        oracle_feed=median_value,
                        expiry_timestamp=current_time + liveness_period,
                        created_at=current_time,
                    )
                )
            ),
        )

    def _create_empty_transport(self, transport: UTxO) -> TransactionOutput:
        """Create empty reward transport output."""
        output_amount = deepcopy(transport.output.amount)

        # Just set the fee token quantity to 0 - MultiAsset normalize() will handle cleanup
        if (
            output_amount.multi_asset
            and self.fee_token_hash in output_amount.multi_asset
        ):
            output_amount.multi_asset[self.fee_token_hash][self.fee_token_name] = 0

        return TransactionOutput(
            address=self.script_address,
            amount=output_amount,
            datum=RewardTransportVariant(datum=NoRewards()),
        )

    def _create_reward_account(
        self,
        reward_account: UTxO,
        transports: list[UTxO],
        settings: OracleSettingsDatum,
    ) -> TransactionOutput:
        """Create updated reward account output.

        The nodes_to_rewards list contains only the reward amounts, which map positionally
        to the nodes list in oracle settings.
        """
        # Calculate rewards from transports
        output_amount = deepcopy(reward_account.output.amount)
        current_datum = reward_account.output.datum.datum
        nodes = list(settings.nodes.node_map.keys())

        total_fee_tokens = 0
        node_rewards = {}

        for transport in transports:
            pending = transport.output.datum.datum
            aggregation = pending.aggregation

            # Accumulate total fees (includes both node and platform portions)
            if (
                transport.output.amount.multi_asset
                and self.fee_token_hash in transport.output.amount.multi_asset
            ):
                fee_tokens = transport.output.amount.multi_asset[self.fee_token_hash][
                    self.fee_token_name
                ]
                total_fee_tokens += fee_tokens

            # Use node_reward_price from aggregation - this already accounts for the split
            reward_per_node = aggregation.node_reward_price

            # Add reward for each participating node
            for node_id in aggregation.message.node_feeds_sorted_by_feed:
                node_rewards[node_id] = node_rewards.get(node_id, 0) + reward_per_node

        # Create rewards list matching nodes order
        new_rewards = []
        for node_id in nodes:
            current_idx = len(new_rewards)
            current_reward = (
                current_datum.nodes_to_rewards[current_idx]
                if current_idx < len(current_datum.nodes_to_rewards)
                else 0
            )
            new_reward = current_reward + node_rewards.get(node_id, 0)
            new_rewards.append(new_reward)

        # Update fee tokens in output (total amount includes both node and platform portions)
        if total_fee_tokens > 0:
            if self.fee_token_hash not in output_amount.multi_asset:
                output_amount.multi_asset[self.fee_token_hash] = Asset()
            output_amount.multi_asset[self.fee_token_hash][self.fee_token_name] = (
                output_amount.multi_asset[self.fee_token_hash].get(
                    self.fee_token_name, 0
                )
                + total_fee_tokens
            )

        return TransactionOutput(
            address=self.script_address,
            amount=output_amount,
            datum=RewardAccountVariant(
                datum=RewardAccountDatum(nodes_to_rewards=new_rewards)
            ),
        )
