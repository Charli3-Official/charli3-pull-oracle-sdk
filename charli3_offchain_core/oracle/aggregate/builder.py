"""Oracle transaction builder leveraging comprehensive validation utilities."""

import logging
from copy import deepcopy
from dataclasses import dataclass

from pycardano import (
    Address,
    Asset,
    AssetName,
    ExtendedSigningKey,
    MultiAsset,
    PaymentSigningKey,
    Redeemer,
    ScriptHash,
    Transaction,
    TransactionOutput,
    UTxO,
)

from charli3_offchain_core.blockchain.transactions import (
    TransactionManager,
    ValidityWindow,
)
from charli3_offchain_core.models.oracle_datums import (
    AggregateMessage,
    Aggregation,
    AggState,
    NoDatum,
    NoRewards,
    OracleSettingsDatum,
    PriceData,
    RewardAccountDatum,
    RewardAccountVariant,
    RewardConsensusPending,
    RewardTransportVariant,
)
from charli3_offchain_core.models.oracle_redeemers import (
    CalculateRewards,
    OdvAggregate,
)
from charli3_offchain_core.oracle.exceptions import (
    StateValidationError,
    TransactionError,
)
from charli3_offchain_core.oracle.utils import (
    asset_checks,
    calc_methods,
    common,
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
    pending_transports: list[UTxO]
    new_reward_account: TransactionOutput
    in_settings: OracleSettingsDatum | None = None

    @property
    def reward_distribution(self) -> dict[int, int]:
        """Get reward distribution from pending transports.

        Returns:
            Dictionary mapping node IDs to their reward amounts.
            The rewards are extracted from the first transport's aggregation data
            and matched with reward amounts from the reward account datum.

        Note:
            Only processes the first transport UTxO, even if multiple are present.
        """
        # Early return if no pending transports
        if not self.pending_transports:
            return {}

        # Get reward amounts list from reward account
        reward_list = self.new_reward_account.datum.datum.nodes_to_rewards

        # Get the first transport's datum
        transport_datum = self.pending_transports[0].output.datum.datum

        # Early return if no aggregation data
        if not hasattr(transport_datum, "aggregation"):
            return {}

        # Build distribution mapping
        distribution = {}
        node_map_keys = list(self.in_settings.nodes.node_map.keys())
        for node_id in transport_datum.aggregation.message.node_feeds_sorted_by_feed:
            if node_id not in node_map_keys:
                continue

            idx = node_map_keys.index(node_id)
            distribution[node_id] = reward_list[idx]

        return distribution

    @property
    def platform_fee(self) -> int:
        """Calculate total platform fee from pending transports."""
        total_fee = 0
        for transport in self.pending_transports:
            datum = transport.output.datum.datum
            if hasattr(datum, "aggregation"):
                agg = datum.aggregation
                node_count = len(agg.message.node_feeds_sorted_by_feed)
                total_fee += agg.rewards_amount_paid - (
                    node_count * agg.node_reward_price
                )
        return total_fee

    @property
    def total_distributed(self) -> int:
        """Calculate total rewards distributed."""
        return sum(self.reward_distribution.values()) + self.platform_fee

    @property
    def transport_details(self) -> list[dict]:
        """Get detailed information about each transport."""
        details = []
        for transport in self.pending_transports:
            datum = transport.output.datum.datum
            if hasattr(datum, "aggregation"):
                agg = datum.aggregation
                node_count = len(agg.message.node_feeds_sorted_by_feed)
                platform_fee = agg.rewards_amount_paid - (
                    node_count * agg.node_reward_price
                )

                details.append(
                    {
                        "tx_hash": transport.input.transaction_id,
                        "index": transport.input.index,
                        "oracle_feed": agg.oracle_feed,
                        "node_count": node_count,
                        "reward_per_node": agg.node_reward_price,
                        "platform_fee": platform_fee,
                        "total_amount": agg.rewards_amount_paid,
                        "node_feeds": dict(agg.message.node_feeds_sorted_by_feed),
                        "timestamp": agg.message.timestamp,
                    }
                )
        return details


class OracleTransactionBuilder:
    """Builder for Oracle transactions with comprehensive validation."""

    def __init__(
        self,
        tx_manager: TransactionManager,
        script_address: Address,
        policy_id: ScriptHash,
        reward_token_hash: ScriptHash | None = None,
        reward_token_name: AssetName | None = None,
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
        self.reward_token_hash = reward_token_hash
        self.reward_token_name = reward_token_name
        self.network_config = self.tx_manager.chain_query.config.network_config

    async def build_odv_tx(
        self,
        message: AggregateMessage,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        change_address: Address | None = None,
        validity_window: ValidityWindow | None = None,
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
            utxos = await common.get_script_utxos(self.script_address, self.tx_manager)

            settings_datum, settings_utxo = (
                state_checks.get_oracle_settings_by_policy_id(utxos, self.policy_id)
            )
            script_utxo = common.get_reference_script_utxo(utxos)

            reference_inputs = {settings_utxo}

            # Calculate the transaction time window and current time ONCE
            if validity_window is None:
                validity_window = self.tx_manager.calculate_validity_window(
                    settings_datum.time_uncertainty_aggregation
                )
            else:
                window_length = (
                    validity_window.validity_end - validity_window.validity_start
                )
                if window_length > settings_datum.time_uncertainty_aggregation:
                    raise ValueError(
                        f"Incorrect validity window length: {window_length} > {settings_datum.time_uncertainty_aggregation}"
                    )
                if window_length <= 0:
                    raise ValueError(
                        f"Incorrect validity window length: {window_length}"
                    )
            validity_start, validity_end, current_time = [
                validity_window.validity_start,
                validity_window.validity_end,
                validity_window.current_time,
            ]

            validity_start_slot, validity_end_slot = self._validity_window_to_slot(
                validity_start, validity_end
            )

            transport, agg_state = state_checks.find_transport_pair(
                utxos, self.policy_id, current_time
            )

            # Create a new message with the current timestamp
            current_message = AggregateMessage(
                node_feeds_sorted_by_feed=message.node_feeds_sorted_by_feed,
                node_feeds_count=message.node_feeds_count,
                timestamp=current_time,
            )

            # Calculate median using the current message
            feeds = list(current_message.node_feeds_sorted_by_feed.values())
            node_count = current_message.node_feeds_count
            median_value = calc_methods.median(
                feeds,
                node_count,
            )

            # Update fees according to the rate feed
            reward_prices = deepcopy(settings_datum.fee_info.reward_prices)
            if settings_datum.fee_info.rate_nft != NoDatum():
                oracle_fee_rate_utxo = common.get_fee_rate_reference_utxo(
                    self.tx_manager.chain_query, settings_datum.fee_info.rate_nft
                )
                if oracle_fee_rate_utxo.output.datum is None:
                    raise ValueError(
                        "Oracle fee rate datum is None. "
                        "A valid fee rate datum is required to scale rewards."
                    )

                standard_datum: AggState = oracle_fee_rate_utxo.output.datum
                reference_inputs.add(oracle_fee_rate_utxo)
                rewards.scale_rewards_by_rate(
                    reward_prices,
                    standard_datum,
                )

            # Calculate minimum fee
            minimum_fee = rewards.calculate_min_fee_amount(
                reward_prices, len(current_message.node_feeds_sorted_by_feed)
            )

            # Create outputs using helper methods
            transport_output = self._create_transport_output(
                transport=transport,
                current_message=current_message,
                median_value=median_value,
                node_reward_price=reward_prices.node_fee,
                minimum_fee=minimum_fee,
            )

            agg_state_output = self._create_agg_state_output(
                agg_state=agg_state,
                median_value=median_value,
                current_time=current_time,
                liveness_period=settings_datum.aggregation_liveness_period,
            )

            # Estimate tx fee
            evaluated_tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (transport, Redeemer(OdvAggregate()), script_utxo),
                    (agg_state, Redeemer(OdvAggregate()), script_utxo),
                ],
                script_outputs=[transport_output, agg_state_output],
                reference_inputs=reference_inputs,
                required_signers=list(current_message.node_feeds_sorted_by_feed.keys()),
                change_address=change_address,
                signing_key=signing_key,
                validity_start=validity_start_slot,
                validity_end=validity_end_slot,
            )
            transport_output.amount.coin += evaluated_tx.transaction_body.fee
            # Build and return transaction
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (transport, Redeemer(OdvAggregate()), script_utxo),
                    (agg_state, Redeemer(OdvAggregate()), script_utxo),
                ],
                script_outputs=[transport_output, agg_state_output],
                reference_inputs=reference_inputs,
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
            utxos = await common.get_script_utxos(self.script_address, self.tx_manager)
            settings_datum, settings_utxo = (
                state_checks.get_oracle_settings_by_policy_id(utxos, self.policy_id)
            )
            script_utxo = common.get_reference_script_utxo(utxos)

            # Find pending transports
            pending_transports = state_checks.filter_pending_transports(
                asset_checks.filter_utxos_by_token_name(utxos, self.policy_id, "C3RT")
            )[:max_inputs]
            if not pending_transports:
                raise StateValidationError("No pending transport UTxOs found")

            # Find reward account
            _, reward_account_utxo = state_checks.get_reward_account_by_policy_id(
                utxos, self.policy_id
            )

            # Calculate the minimum ADA required for Transport UTxOs,
            # using the CoreSettings UTxO as a reference.
            # This approach aligns with the deployment strategy where
            # the CoreSettings UTxO determines the minimum ADA.
            min_core_settings_ada = settings_datum.utxo_size_safety_buffer

            # Create new transport outputs
            new_transports = [
                self._create_empty_transport(transport, min_core_settings_ada)
                for transport in pending_transports
            ]

            # Create new reward account output
            reward_account_output = self._create_reward_account(
                reward_account_utxo, pending_transports, settings_datum
            )

            # Build transaction
            script_inputs = [
                (t, Redeemer(CalculateRewards()), script_utxo)
                for t in pending_transports
            ]
            script_inputs.append(
                (reward_account_utxo, Redeemer(CalculateRewards()), script_utxo)
            )

            tx = await self.tx_manager.build_script_tx(
                script_inputs=script_inputs,
                script_outputs=[*new_transports, reward_account_output],
                reference_inputs=[settings_utxo],
                change_address=change_address,
                signing_key=signing_key,
            )

            return RewardsResult(
                transaction=tx,
                pending_transports=pending_transports,
                new_reward_account=reward_account_output,
                in_settings=settings_datum,
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

        self._add_reward_to_output(transport_output, minimum_fee)

        return self._create_final_output(
            transport_output,
            current_message,
            median_value,
            node_reward_price,
            minimum_fee,
        )

    def _add_reward_to_output(
        self, transport_output: TransactionOutput, minimum_fee: int
    ) -> None:
        """
        Add fees to the transport output based on reward token configuration.

        Args:
            transport_output: The output to add fees to
            minimum_fee: The fee amount to add
        """
        if not (self.reward_token_hash or self.reward_token_name):
            transport_output.amount.coin += minimum_fee
            return

        self._add_token_fees(transport_output, minimum_fee)

    def _add_token_fees(
        self, transport_output: TransactionOutput, minimum_fee: int
    ) -> None:
        """
        Add token-based fees to the output.

        Args:
            transport_output: The output to add token fees to
            minimum_fee: The fee amount to add
        """
        token_hash = self.reward_token_hash
        token_name = self.reward_token_name

        if (
            token_hash in transport_output.amount.multi_asset
            and token_name in transport_output.amount.multi_asset[token_hash]
        ):
            transport_output.amount.multi_asset[token_hash][token_name] += minimum_fee
        else:
            fee_asset = MultiAsset({token_hash: Asset({token_name: minimum_fee})})
            transport_output.amount.multi_asset += fee_asset

    def _create_final_output(
        self,
        transport_output: TransactionOutput,
        current_message: AggregateMessage,
        median_value: int,
        node_reward_price: int,
        minimum_fee: int,
    ) -> TransactionOutput:
        """
        Create the final transaction output with all necessary data.

        Args:
            transport_output: The processed transport output
            current_message: Current aggregate message
            median_value: The calculated median value
            node_reward_price: Price for node reward
            minimum_fee: Minimum fee added

        Returns:
            TransactionOutput: The final transaction output
        """
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
            datum=AggState(
                price_data=PriceData.set_price_map(
                    median_value, current_time, current_time + liveness_period
                )
            ),
        )

    def _create_empty_transport(
        self, transport: UTxO, min_ada: int
    ) -> TransactionOutput:
        """Create empty reward transport output."""
        output_amount = deepcopy(transport.output.amount)

        # Just set the fee token quantity to 0 - MultiAsset normalize() will handle cleanup
        if self.reward_token_hash and self.reward_token_name:
            if (
                output_amount.multi_asset
                and self.reward_token_hash in output_amount.multi_asset
                and self.reward_token_name
                in output_amount.multi_asset[self.reward_token_hash]
            ):
                output_amount.multi_asset[self.reward_token_hash][
                    self.reward_token_name
                ] = 0
        output_amount.coin = min_ada

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

        # Calculate total fees and rewards
        total_payment_tokens = rewards.calculate_total_fees(
            transports,
            self.reward_token_hash,
            self.reward_token_name,
        )
        node_rewards = rewards.calculate_node_rewards_from_transports(
            transports, nodes, settings.iqr_fence_multiplier
        )

        # Accumulate rewards
        new_rewards = rewards.accumulate_node_rewards(
            current_datum, node_rewards, nodes
        )

        # Update fee tokens
        new_value = rewards.update_fee_tokens(
            output_amount,
            self.reward_token_hash,
            self.reward_token_name,
            total_payment_tokens,
        )

        return TransactionOutput(
            address=self.script_address,
            amount=new_value,
            datum=RewardAccountVariant(
                datum=RewardAccountDatum(nodes_to_rewards=new_rewards)
            ),
        )

    def _validity_window_to_slot(
        self, validity_start: int, validity_end: int
    ) -> tuple[int, int]:
        """Convert validity window to slot numbers."""
        validity_start_slot = self.network_config.posix_to_slot(validity_start)
        validity_end_slot = self.network_config.posix_to_slot(validity_end)
        return validity_start_slot, validity_end_slot
