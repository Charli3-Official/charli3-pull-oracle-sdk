"""Consensus calculation and validation utilities for oracle feed data."""

import logging
from statistics import median

from pycardano import VerificationKeyHash

from charli3_offchain_core.models.oracle_datums import (
    AggregateMessage,
    OracleSettingsDatum,
)
from charli3_offchain_core.oracle.exceptions import (
    AggregationError,
    ConsensusError,
    OutlierError,
    QuorumError,
)

logger = logging.getLogger(__name__)


class ConsensusCalculator:
    """Calculates consensus from oracle feed data."""

    def __init__(self, settings: OracleSettingsDatum) -> None:
        """Initialize consensus calculator with oracle settings.

        Args:
            settings: Oracle settings containing consensus parameters
        """
        self.settings = settings
        self.iqr_multiplier = (
            settings.iqr_fence_multiplier / 100.0
        )  # Convert from percent

    def calculate_consensus(
        self, message: AggregateMessage, min_value: int, max_value: int
    ) -> tuple[int, set[VerificationKeyHash]]:
        """Calculate consensus value from node feeds.

        Args:
            message: Aggregate message containing node feeds
            min_value: Minimum valid feed value
            max_value: Maximum valid feed value

        Returns:
            Tuple of (consensus value, set of outlier VKHs)
        """
        try:
            # Extract feed values and create VKH mapping
            feeds = dict(message.node_feeds_sorted_by_feed)

            # Validate feed count
            if len(feeds) < self.settings.required_node_signatures_count:
                raise QuorumError(
                    f"Insufficient feeds: {len(feeds)} < "
                    f"{self.settings.required_node_signatures_count}"
                )

            # Validate feed values
            valid_feeds = {
                vkh: value
                for vkh, value in feeds.items()
                if min_value <= value <= max_value
            }

            if len(valid_feeds) < self.settings.required_node_signatures_count:
                raise QuorumError("Insufficient valid feeds after range validation")

            # Detect outliers
            outliers = self._detect_outliers(valid_feeds)
            remaining_feeds = {
                vkh: value for vkh, value in valid_feeds.items() if vkh not in outliers
            }

            if len(remaining_feeds) < self.settings.required_node_signatures_count:
                raise QuorumError("Insufficient feeds after outlier removal")

            # Calculate final consensus
            consensus_value = int(median(remaining_feeds.values()))
            logger.info(
                "Calculated consensus value %d from %d feeds (%d outliers)",
                consensus_value,
                len(remaining_feeds),
                len(outliers),
            )

            return consensus_value, outliers

        except Exception as e:
            raise ConsensusError(f"Failed to calculate consensus: {e}") from e

    def _detect_outliers(self, feeds: dict[int, int]) -> set[int]:
        """Detect outlier feeds using IQR method.

        Args:
            feeds: Dictionary of node feeds

        Returns:
            Set of outlier node IDs

        Raises:
            OutlierError: If outlier detection fails
        """
        try:
            values = sorted(feeds.values())
            if len(values) < 4:  # Need at least 4 values for meaningful quartiles
                return set()

            # Calculate quartiles
            n = len(values)
            q1_idx = (n + 1) // 4
            q3_idx = (3 * (n + 1)) // 4

            q1 = float(values[q1_idx - 1])
            q3 = float(values[q3_idx - 1])
            iqr = q3 - q1

            # Calculate bounds
            lower_bound = q1 - (self.iqr_multiplier * iqr)
            upper_bound = q3 + (self.iqr_multiplier * iqr)

            # Identify outliers
            outliers = {
                node_id
                for node_id, value in feeds.items()
                if value < lower_bound or value > upper_bound
            }

            if outliers:
                logger.info(
                    "Detected %d outliers outside bounds [%.2f, %.2f]",
                    len(outliers),
                    lower_bound,
                    upper_bound,
                )

            return outliers

        except Exception as e:
            raise OutlierError(f"Failed to detect outliers: {e}") from e

    def validate_aggregate_message(
        self, msg: AggregateMessage, current_time: int
    ) -> bool:
        """Validate aggregate message contents.

        Args:
            msg: Aggregate message to validate
            current_time: Current time in milliseconds

        Returns:
            bool: True if message is valid

        Raises:
            AggregationError: If validation fails
        """
        try:
            # Validate node count
            if len(msg.node_feeds_sorted_by_feed) != msg.node_feeds_count:
                logger.warning("Node count mismatch in message")
                return False

            # Validate minimum node count
            if msg.node_feeds_count < self.settings.required_node_signatures_count:
                logger.warning("Insufficient nodes in message")
                return False

            # Validate timestamp
            time_window = self.settings.time_absolute_uncertainty
            if not (
                current_time - time_window
                <= msg.timestamp
                <= current_time + time_window
            ):
                logger.warning("Message timestamp outside valid window")
                return False

            # Validate feed sorting - checking that feeds are sorted by value
            feed_values = [feed for _, feed in msg.node_feeds_sorted_by_feed]
            if feed_values != sorted(feed_values):
                logger.warning("Feeds not properly sorted")
                return False

            return True

        except Exception as e:
            raise AggregationError(f"Failed to validate aggregate message: {e}") from e

    def validate_consensus_result(
        self,
        consensus_value: int,
        feeds: dict[int, int],
        outliers: set[int],
        min_value: int,
        max_value: int,
    ) -> bool:
        """Validate consensus calculation result.

        Args:
            consensus_value: Calculated consensus value
            feeds: Original node feeds
            outliers: Detected outlier node IDs
            min_value: Minimum valid value
            max_value: Maximum valid value

        Returns:
            bool: True if consensus result is valid

        Raises:
            ConsensusError: If validation fails
        """
        try:
            # Validate consensus range
            if not min_value <= consensus_value <= max_value:
                logger.warning("Consensus value outside valid range")
                return False

            # Validate with remaining feeds
            remaining_feeds = {
                node_id: value
                for node_id, value in feeds.items()
                if node_id not in outliers
            }

            # Verify minimum feed count
            if len(remaining_feeds) < self.settings.required_node_signatures_count:
                logger.warning("Insufficient feeds after outlier removal")
                return False

            # Verify consensus against median
            calculated_median = int(median(remaining_feeds.values()))
            if calculated_median != consensus_value:
                logger.warning("Consensus value does not match median")
                return False

            return True

        except Exception as e:
            raise ConsensusError(f"Failed to validate consensus result: {e}") from e
