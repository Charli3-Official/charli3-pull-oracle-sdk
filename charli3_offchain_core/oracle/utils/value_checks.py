"""Utilities for validating oracle feed values and numeric constraints."""

import logging

from pycardano import UTxO

from charli3_offchain_core.oracle.exceptions import (
    OutlierError,
    RangeError,
    ValueValidationError,
)

logger = logging.getLogger(__name__)

# Constants for value validation
DEFAULT_MIN_VALUE = 0
DEFAULT_MAX_VALUE = 1_000_000_000_000  # 1 trillion
MIN_FEED_COUNT = 1
DEFAULT_DEVIATION_THRESHOLD = 0.5  # 50% deviation threshold


def validate_feed_values(
    feeds: dict[int, int],
    min_value: int = DEFAULT_MIN_VALUE,
    max_value: int = DEFAULT_MAX_VALUE,
) -> bool:
    """Validate feed values are within acceptable range.

    Args:
        feeds: Dictionary of node ID to feed value
        min_value: Minimum acceptable value
        max_value: Maximum acceptable value

    Returns:
        bool: True if all feeds are valid

    Raises:
        RangeError: If validation fails
    """
    try:
        if not feeds:
            raise RangeError("Empty feeds dictionary")

        for node_id, value in feeds.items():
            if not min_value <= value <= max_value:
                logger.warning(
                    "Feed value %d from node %d outside valid range [%d, %d]",
                    value,
                    node_id,
                    min_value,
                    max_value,
                )
                return False

        return True

    except Exception as e:
        raise ValueValidationError(f"Failed to validate feed values: {e}") from e


def validate_consensus_value(
    consensus: int, node_feeds: dict[int, int], multiplier: float
) -> bool:
    """Validate consensus value against node feeds using IQR.

    Args:
        consensus: Calculated consensus value
        node_feeds: Dictionary of node ID to feed value
        multiplier: IQR multiplier for outlier detection

    Returns:
        bool: True if consensus value is valid

    Raises:
        OutlierError: If consensus value is an outlier
    """
    try:
        if not node_feeds:
            raise OutlierError("Empty node feeds")

        # Calculate IQR boundaries
        values = sorted(node_feeds.values())
        q1, q3 = _calculate_quartiles(values)
        iqr = q3 - q1
        lower_bound = q1 - (multiplier * iqr)
        upper_bound = q3 + (multiplier * iqr)

        # Check consensus value
        if not lower_bound <= consensus <= upper_bound:
            logger.warning(
                "Consensus value %d outside IQR bounds [%d, %d]",
                consensus,
                lower_bound,
                upper_bound,
            )
            return False

        return True

    except Exception as e:
        raise ValueValidationError(f"Failed to validate consensus value: {e}") from e


def _calculate_quartiles(values: list[int]) -> tuple[float, float]:
    """Calculate first and third quartiles of values.

    Args:
        values: Sorted list of values

    Returns:
        Tuple of (Q1, Q3)
    """
    n = len(values)
    if n < 4:
        return float(values[0]), float(values[-1])

    # Calculate quartile positions
    q1_pos = (n + 1) // 4
    q3_pos = (3 * (n + 1)) // 4

    # Calculate quartile values
    q1 = float(values[q1_pos - 1])
    q3 = float(values[q3_pos - 1])

    return q1, q3


def detect_outliers(feeds: dict[int, int], multiplier: float) -> set[int]:
    """Detect outlier feeds using IQR method.

    Args:
        feeds: Dictionary of node ID to feed value
        multiplier: IQR multiplier for outlier detection

    Returns:
        Set of node IDs with outlier values

    Raises:
        OutlierError: If outlier detection fails
    """
    try:
        if not feeds:
            raise OutlierError("Empty feeds dictionary")

        # Calculate IQR boundaries
        values = sorted(feeds.values())
        q1, q3 = _calculate_quartiles(values)
        iqr = q3 - q1
        lower_bound = q1 - (multiplier * iqr)
        upper_bound = q3 + (multiplier * iqr)

        # Find outliers
        outliers = {
            node_id
            for node_id, value in feeds.items()
            if value < lower_bound or value > upper_bound
        }

        if outliers:
            logger.info(
                "Detected %d outliers outside bounds [%d, %d]",
                len(outliers),
                lower_bound,
                upper_bound,
            )

        return outliers

    except Exception as e:
        raise OutlierError(f"Failed to detect outliers: {e}") from e


def validate_min_fee_amount(utxo: UTxO, min_amount: int) -> bool:
    """Validate UTxO contains minimum required fee amount.

    Args:
        utxo: UTxO to validate
        min_amount: Minimum required amount

    Returns:
        bool: True if UTxO contains sufficient amount

    Raises:
        ValueValidationError: If validation fails
    """
    try:
        if min_amount < 0:
            raise ValueValidationError("Minimum amount cannot be negative")

        return utxo.output.amount.coin >= min_amount

    except Exception as e:
        raise ValueValidationError(f"Failed to validate fee amount: {e}") from e


def validate_feed_distribution(
    feeds: dict[int, int], max_deviation: float = DEFAULT_DEVIATION_THRESHOLD
) -> bool:
    """Validate distribution of feed values.

    Args:
        feeds: Dictionary of node ID to feed value
        max_deviation: Maximum allowed deviation from median

    Returns:
        bool: True if feed distribution is valid

    Raises:
        ValueValidationError: If validation fails
    """
    try:
        if not feeds:
            raise ValueValidationError("Empty feeds dictionary")

        if max_deviation <= 0 or max_deviation >= 1:
            raise ValueValidationError("Max deviation must be between 0 and 1")

        # Calculate median
        values = sorted(feeds.values())
        median = values[len(values) // 2]

        if median == 0:
            return all(v == 0 for v in values)

        # Check deviations
        for value in values:
            deviation = abs(value - median) / median
            if deviation > max_deviation:
                return False

        return True

    except Exception as e:
        raise ValueValidationError(f"Failed to validate feed distribution: {e}") from e
