"""Oracle transaction builder leveraging comprehensive validation utilities."""

import logging
from dataclasses import dataclass

from pycardano import (
    Address,
    ExtendedSigningKey,
    PaymentSigningKey,
    Transaction,
    TransactionOutput,
    UTxO,
)

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.models.oracle_datums import (
    AggregateMessage,
    AggStateDatum,
    AggStateVariant,
    NoRewards,
    OracleConfiguration,
    OracleSettingsDatum,
    RewardAccountVariant,
    RewardConsensusPending,
    RewardTransportVariant,
)
from charli3_offchain_core.models.oracle_redeemers import (
    CalculateRewards,
    OdvAggregate,
)
from charli3_offchain_core.oracle.exceptions import (
    ConsensusError,
    StateValidationError,
    TimeValidationError,
    TransactionError,
    ValidationError,
)
from charli3_offchain_core.oracle.utils import (
    asset_checks,
    consensus,
    rewards,
    signature_checks,
    state_checks,
    time_checks,
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
        oracle_config: OracleConfiguration,
    ) -> None:
        """Initialize transaction builder.

        Args:
            tx_manager: Transaction manager
            script_address: Script address
            policy_id: Policy ID for tokens
            oracle_config: Oracle configuration
        """
        self.tx_manager = tx_manager
        self.script_address = script_address
        self.policy_id = policy_id
        self.oracle_config = oracle_config
        self.consensus_calculator = consensus.ConsensusCalculator(None)
        self.reward_calculator = rewards.RewardCalculator(None)
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

    async def _find_transport_pair(self, utxos: list[UTxO]) -> tuple[UTxO, UTxO]:
        """Find matching empty transport and agg state pair."""
        try:
            # Find empty transport
            transports = state_checks.filter_empty_transports(
                asset_checks.filter_utxos_by_token_name(
                    utxos, self.policy_id, "transport"
                )
            )
            if not transports:
                raise StateValidationError("No empty transport UTxO found")

            # Find empty agg state
            agg_states = state_checks.filter_empty_agg_states(
                asset_checks.filter_utxos_by_token_name(
                    utxos, self.policy_id, "aggstate"
                )
            )
            if not agg_states:
                raise StateValidationError("No empty agg state UTxO found")

            # Find matching pair
            for transport in transports:
                for agg_state in agg_states:
                    if state_checks.validate_matching_pair(transport, agg_state):
                        return transport, agg_state

            raise StateValidationError("No matching transport/agg state pair found")

        except Exception as e:
            raise TransactionError(f"Failed to find UTxO pair: {e}") from e

    async def build_odv_tx(
        self,
        message: AggregateMessage,
        settings: OracleSettingsDatum,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        change_address: Address | None = None,
    ) -> OdvResult:
        """Build ODV aggregation transaction with comprehensive validation.

        Args:
            message: Aggregate message to validate
            settings: Oracle settings datum
            signing_key: Signing key for transaction
            change_address: Optional change address

        Returns:
            OdvResult containing transaction and outputs

        Raises:
            ValidationError: If validation fails
            TransactionError: If transaction building fails
        """
        try:
            # Update calculators with current settings
            self.consensus_calculator = consensus.ConsensusCalculator(settings)

            # Validate message content
            if not self.consensus_calculator.validate_aggregate_message(
                message, self.tx_manager.chain_query.get_current_posix_chain_time_ms()
            ):
                raise ValidationError("Invalid aggregate message")

            # Validate signatures
            if not signature_checks.validate_message_nodes(message, settings):
                raise ValidationError("Invalid node signatures")

            # Validate oracle state
            if state_checks.is_oracle_closing(settings):
                raise StateValidationError("Oracle is in closing period")

            # Get and validate UTxOs
            utxos = await self._get_script_utxos()
            transport, agg_state = await self._find_transport_pair(utxos)

            # Validate timestamp
            current_time = self.tx_manager.chain_query.get_current_posix_chain_time_ms()
            if not time_checks.is_valid_timestamp(
                message.timestamp, current_time, settings.time_absolute_uncertainty
            ):
                raise TimeValidationError("Invalid message timestamp")

            # Create outputs with updated datums
            transport_output = TransactionOutput(
                address=self.script_address,
                amount=transport.output.amount,
                datum=RewardTransportVariant(
                    datum=RewardConsensusPending(
                        oracle_feed=0,  # Set by validator
                        message=message,
                        node_reward_price=0,
                    )
                ),
            )

            expiry_time = time_checks.calculate_expiry_time(
                message.timestamp, settings.aggregation_liveness_period
            )
            agg_state_output = TransactionOutput(
                address=self.script_address,
                amount=agg_state.output.amount,
                datum=AggStateVariant(
                    datum=AggStateDatum(
                        oracle_feed=0,  # Set by validator
                        expiry_timestamp=expiry_time,
                        created_at=message.timestamp,
                    )
                ),
            )

            # Build transaction
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (transport, OdvAggregate(), None),
                    (agg_state, OdvAggregate(), None),
                ],
                script_outputs=[transport_output, agg_state_output],
                change_address=change_address,
                signing_key=signing_key,
            )

            return OdvResult(tx, transport_output, agg_state_output)

        except Exception as e:
            raise TransactionError(f"Failed to build ODV transaction: {e}") from e

    async def build_rewards_tx(
        self,
        settings: OracleSettingsDatum,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        max_inputs: int = 8,
        min_feed_value: int = 0,
        max_feed_value: int = 10**15,
        change_address: Address | None = None,
    ) -> RewardsResult:
        """Build rewards calculation transaction with consensus processing.

        Args:
            settings: Oracle settings datum
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
            # Update calculators with current settings
            self.consensus_calculator = consensus.ConsensusCalculator(settings)
            self.reward_calculator = rewards.RewardCalculator(settings.fee_info)

            # Get and validate UTxOs
            utxos = await self._get_script_utxos()

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
                    total_fees=settings.fee_info.reward_prices.node_fee,
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
            script_inputs = [(t, CalculateRewards(), None) for t in transports]
            script_inputs.append((reward_account, CalculateRewards(), None))

            tx = await self.tx_manager.build_script_tx(
                script_inputs=script_inputs,
                script_outputs=[*new_transports, reward_account_output],
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
