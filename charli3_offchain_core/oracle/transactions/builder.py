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
    ConsensusError,
    StateValidationError,
    TransactionError,
    ValidationError,
)
from charli3_offchain_core.oracle.utils import (
    asset_checks,
    consensus,
    rewards,
    state_checks,
    value_checks,
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
    consensus_values: dict[int, int]  # Feed index -> consensus value
    reward_distribution: rewards.RewardDistribution


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
            # Get current network time
            current_time = message.timestamp

            # Get UTxOs and settings
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

            # Validate message content
            if not self.consensus_calculator.validate_aggregate_message(
                message, self.tx_manager.chain_query.get_current_posix_chain_time_ms()
            ):
                raise ValidationError("Invalid aggregate message")

            # Validate oracle state
            if state_checks.is_oracle_closing(settings_datum):
                raise StateValidationError("Oracle is in closing period")

            # Calculate median
            feeds = list(message.node_feeds_sorted_by_feed.values())
            median_value = int(median(feeds))

            # Get reward prices and calculate fees
            minimum_fee = self.reward_calculator.calculate_min_fee_amount(
                len(message.node_feeds_sorted_by_feed)
            )

            # Create message with current timestamp
            current_message = AggregateMessage(
                node_feeds_sorted_by_feed=message.node_feeds_sorted_by_feed,
                node_feeds_count=message.node_feeds_count,
                timestamp=current_time,
            )

            # Create transport output with fees
            transport_output = deepcopy(transport.output)

            # Use class attributes directly
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

            transport_output = TransactionOutput(
                address=self.script_address,
                amount=transport_output.amount,
                datum=RewardTransportVariant(
                    datum=RewardConsensusPending(
                        aggregation=Aggregation(
                            oracle_feed=median_value,
                            message=current_message,
                            node_reward_price=minimum_fee,
                            rewards_amount_paid=minimum_fee,
                        )
                    )
                ),
            )

            # Create agg state output
            expiry_time = current_time + settings_datum.aggregation_liveness_period
            agg_state_output = TransactionOutput(
                address=self.script_address,
                amount=agg_state.output.amount,
                datum=AggStateVariant(
                    datum=SomeAggStateDatum(
                        aggstate=AggStateDatum(
                            oracle_feed=median_value,
                            expiry_timestamp=expiry_time,
                            created_at=current_time,
                        )
                    )
                ),
            )

            # Extract VKHs from message nodes
            node_vkhs = list(message.node_feeds_sorted_by_feed.keys())

            # Build transaction
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (transport, OdvAggregate(), script_utxo),
                    (agg_state, OdvAggregate(), script_utxo),
                ],
                script_outputs=[transport_output, agg_state_output],
                reference_inputs=[settings_utxo],
                required_signers=node_vkhs,
                change_address=change_address,
                signing_key=signing_key,
            )

            return OdvResult(tx, transport_output, agg_state_output)

        except Exception as e:
            raise TransactionError(f"Failed to build ODV transaction: {e}") from e

    async def build_rewards_tx(
        self,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        max_inputs: int = 8,
        min_feed_value: int = 0,
        max_feed_value: int = 10**15,
        change_address: Address | None = None,
    ) -> RewardsResult:
        """Build rewards calculation transaction with consensus processing.

        Args:
            signing_key: Signing key for transaction
            max_inputs: Maximum number of transport UTxOs to process
            min_feed_value: Minimum valid feed value
            max_feed_value: Maximum valid feed value
            change_address: Optional change address

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
            transports = state_checks.filter_pending_transports(
                asset_checks.filter_utxos_by_token_name(
                    utxos, self.policy_id, "transport"
                )
            )[:max_inputs]
            if not transports:
                raise StateValidationError("No pending transport UTxOs found")

            # Find reward account
            reward_accounts = state_checks.filter_reward_accounts(
                asset_checks.filter_utxos_by_token_name(
                    utxos, self.policy_id, "rewardaccount"
                )
            )
            if not reward_accounts:
                raise StateValidationError("No reward account UTxO found")
            reward_account = reward_accounts[0]

            # Process feeds and calculate rewards
            consensus_values = {}
            total_distribution = None

            for idx, transport in enumerate(transports):
                if not isinstance(
                    transport.output.datum.variant.datum, RewardConsensusPending
                ):
                    continue

                message = transport.output.datum.variant.datum.message

                # Validate feed values
                if not value_checks.validate_feed_values(
                    message.node_feeds_sorted_by_feed,
                    min_feed_value,
                    max_feed_value,
                ):
                    continue

                # Calculate consensus
                consensus_value, outliers = (
                    self.consensus_calculator.calculate_consensus(
                        message.node_feeds_sorted_by_feed,
                        min_feed_value,
                        max_feed_value,
                    )
                )
                consensus_values[idx] = consensus_value

                # Calculate rewards
                distribution = self.reward_calculator.calculate_rewards(
                    participants=set(message.node_feeds_sorted_by_feed.keys()),
                    outliers=outliers,
                    total_fees=settings_datum.fee_info.reward_prices.node_fee,
                )

                # Update total distribution
                if total_distribution is None:
                    total_distribution = distribution
                else:
                    # Use reward accumulator to combine distributions
                    accumulated_rewards = self.reward_accumulator.accumulate_rewards(
                        total_distribution.node_rewards, distribution.node_rewards
                    )
                    total_distribution = rewards.RewardDistribution(
                        node_rewards=accumulated_rewards,
                        platform_fee=total_distribution.platform_fee
                        + distribution.platform_fee,
                        total_distributed=total_distribution.total_distributed
                        + distribution.total_distributed,
                    )

            if not consensus_values:
                raise ConsensusError("No valid consensus values calculated")

            # Create new transport outputs
            new_transports = [
                TransactionOutput(
                    address=self.script_address,
                    amount=t.output.amount,
                    datum=RewardTransportVariant(datum=NoRewards()),
                )
                for t in transports
            ]

            # Create new reward account output
            reward_account_output = TransactionOutput(
                address=self.script_address,
                amount=reward_account.output.amount,
                datum=RewardAccountVariant(
                    datum=self.reward_accumulator.update_reward_account(
                        reward_account.output.datum.variant.datum,
                        total_distribution,
                    )
                ),
            )

            # Build transaction
            script_inputs = [(t, CalculateRewards(), script_utxo) for t in transports]
            script_inputs.append((reward_account, CalculateRewards(), script_utxo))

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
                consensus_values=consensus_values,
                reward_distribution=total_distribution,
            )

        except Exception as e:
            raise TransactionError(f"Failed to build rewards transaction: {e}") from e
