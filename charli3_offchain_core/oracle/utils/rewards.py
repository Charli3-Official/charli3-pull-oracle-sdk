"""Reward calculation and distribution utilities for oracle operations."""

import logging
from dataclasses import dataclass

from charli3_offchain_core.models.oracle_datums import FeeConfig, RewardAccountDatum
from charli3_offchain_core.oracle.exceptions import (
    AccountingError,
    DistributionError,
)

logger = logging.getLogger(__name__)


@dataclass
class RewardDistribution:
    """Result of reward calculation."""

    node_rewards: dict[int, int]
    platform_fee: int
    total_distributed: int


class RewardCalculator:
    """Handles reward calculations and distributions."""

    def __init__(self, fee_config: FeeConfig) -> None:
        """Initialize reward calculator with fee configuration.

        Args:
            fee_config: Fee configuration for calculations
        """
        self.fee_config = fee_config

    def calculate_rewards(
        self,
        participants: set[int],
        outliers: set[int],
        total_fees: int,
        min_reward: int | None = None,
    ) -> RewardDistribution:
        """Calculate reward distribution.

        Args:
            participants: Set of participating node IDs
            outliers: Set of outlier node IDs
            total_fees: Total fees to distribute
            min_reward: Optional minimum reward per node

        Returns:
            RewardDistribution with calculated amounts

        Raises:
            DistributionError: If reward calculation fails
        """
        try:
            # Validate inputs
            if not participants:
                raise DistributionError("Empty participant set")
            if total_fees <= 0:
                raise DistributionError("Total fees must be positive")

            # Calculate valid nodes
            valid_nodes = participants - outliers
            if not valid_nodes:
                raise DistributionError("No valid nodes for reward")

            # Calculate platform fee
            platform_fee = self.fee_config.reward_prices.platform_fee
            if total_fees <= platform_fee:
                raise DistributionError("Insufficient fees for distribution")

            # Calculate per-node reward
            distributable = total_fees - platform_fee
            per_node = distributable // len(valid_nodes)

            if min_reward and per_node < min_reward:
                raise DistributionError(
                    f"Per-node reward {per_node} below minimum {min_reward}"
                )

            # Create reward distribution
            node_rewards = {node_id: per_node for node_id in valid_nodes}

            # Handle remainder
            remainder = distributable - (per_node * len(valid_nodes))
            if remainder > 0:
                platform_fee += remainder

            total_distributed = sum(node_rewards.values()) + platform_fee

            return RewardDistribution(
                node_rewards=node_rewards,
                platform_fee=platform_fee,
                total_distributed=total_distributed,
            )

        except Exception as e:
            raise DistributionError(f"Failed to calculate rewards: {e}") from e

    def validate_distribution(
        self, distribution: RewardDistribution, total_fees: int
    ) -> bool:
        """Validate reward distribution.

        Args:
            distribution: Calculated reward distribution
            total_fees: Total fees available

        Returns:
            bool: True if distribution is valid

        Raises:
            DistributionError: If validation fails
        """
        try:
            # Check total distributed matches fees
            if distribution.total_distributed != total_fees:
                logger.warning(
                    "Distribution total %d does not match fees %d",
                    distribution.total_distributed,
                    total_fees,
                )
                return False

            # Check platform fee
            if distribution.platform_fee < self.fee_config.reward_prices.platform_fee:
                logger.warning("Platform fee below minimum")
                return False

            # Check node rewards are equal
            if distribution.node_rewards:
                reward_values = set(distribution.node_rewards.values())
                if len(reward_values) > 1:
                    logger.warning("Unequal node rewards")
                    return False

            return True

        except Exception as e:
            raise DistributionError(f"Failed to validate distribution: {e}") from e


class RewardAccumulator:
    """Handles reward accumulation and accounting."""

    def accumulate_rewards(
        self,
        current: dict[int, int],
        new: dict[int, int],
        max_accumulation: int | None = None,
    ) -> dict[int, int]:
        """Accumulate new rewards with existing rewards.

        Args:
            current: Current accumulated rewards
            new: New rewards to add
            max_accumulation: Optional maximum per-node accumulation

        Returns:
            Updated rewards dictionary

        Raises:
            AccountingError: If accumulation fails
        """
        try:
            # Create result dictionary
            result = current.copy()

            # Add new rewards
            for node_id, amount in new.items():
                if amount < 0:
                    raise AccountingError(f"Negative reward amount for node {node_id}")

                current_amount = result.get(node_id, 0)
                new_amount = current_amount + amount

                if max_accumulation and new_amount > max_accumulation:
                    logger.warning(
                        "Node %d reward %d exceeds maximum %d",
                        node_id,
                        new_amount,
                        max_accumulation,
                    )
                    new_amount = max_accumulation

                result[node_id] = new_amount

            return result

        except Exception as e:
            raise AccountingError(f"Failed to accumulate rewards: {e}") from e

    def update_reward_account(
        self, current: RewardAccountDatum, distribution: RewardDistribution
    ) -> RewardAccountDatum:
        """Update reward account with new distribution.

        Args:
            current: Current reward account datum
            distribution: New reward distribution

        Returns:
            Updated reward account datum

        Raises:
            AccountingError: If update fails
        """
        try:
            # Convert current rewards to dictionary
            current_rewards = dict(
                zip(
                    current.nodes_to_rewards[::2],
                    current.nodes_to_rewards[1::2],
                )
            )

            # Accumulate new rewards
            updated_rewards = self.accumulate_rewards(
                current_rewards, distribution.node_rewards
            )

            # Convert back to list format
            nodes_to_rewards = []
            for node_id, amount in sorted(updated_rewards.items()):
                nodes_to_rewards.extend([node_id, amount])

            return RewardAccountDatum(nodes_to_rewards=nodes_to_rewards)

        except Exception as e:
            raise AccountingError(f"Failed to update reward account: {e}") from e

    def validate_reward_account(
        self, datum: RewardAccountDatum, min_amount: int | None = None
    ) -> bool:
        """Validate reward account datum.

        Args:
            datum: Reward account datum to validate
            min_amount: Optional minimum reward amount

        Returns:
            bool: True if datum is valid

        Raises:
            AccountingError: If validation fails
        """
        try:
            rewards = datum.nodes_to_rewards

            # Check list length is even
            if len(rewards) % 2 != 0:
                logger.warning("Rewards list length is not even")
                return False

            # Validate node IDs and amounts
            for i in range(0, len(rewards), 2):
                node_id = rewards[i]
                amount = rewards[i + 1]

                # Check node ID
                if node_id < 0:
                    logger.warning("Invalid node ID: %d", node_id)
                    return False

                # Check amount
                if amount < 0:
                    logger.warning("Negative reward amount: %d", amount)
                    return False

                if min_amount and amount < min_amount:
                    logger.warning(
                        "Reward amount %d below minimum %d", amount, min_amount
                    )
                    return False

            return True

        except Exception as e:
            raise AccountingError(f"Failed to validate reward account: {e}") from e
