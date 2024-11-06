"""Time-related validation utilities for oracle operations."""

import logging

from charli3_offchain_core.models.oracle_datums import (
    AggregateMessage,
    NoDatum,
    OracleSettingsDatum,
)
from charli3_offchain_core.oracle.exceptions import TimeValidationError

logger = logging.getLogger(__name__)

# Constants for time validation
MAX_FUTURE_TIME = 5 * 60 * 1000  # 5 minutes in milliseconds
MIN_TIMESTAMP = 1672531200000  # 2023-01-01 in milliseconds


def is_valid_timestamp(
    timestamp: int, current_time: int, uncertainty_window: int
) -> bool:
    """Validate timestamp is within acceptable range.

    Args:
        timestamp: Timestamp to validate (milliseconds)
        current_time: Current time (milliseconds)
        uncertainty_window: Allowed time uncertainty (milliseconds)

    Returns:
        bool: True if timestamp is valid

    Raises:
        TimeValidationError: If validation parameters are invalid
    """
    if uncertainty_window < 0:
        raise TimeValidationError("Uncertainty window cannot be negative")

    if timestamp < MIN_TIMESTAMP:
        return False

    # Check if timestamp is too far in future
    if timestamp > current_time + MAX_FUTURE_TIME:
        return False

    # Check if timestamp is too old
    return timestamp >= current_time - uncertainty_window


def is_within_liveness_period(
    creation_time: int, current_time: int, liveness_period: int
) -> bool:
    """Check if time is within liveness period.

    Args:
        creation_time: Creation timestamp (milliseconds)
        current_time: Current time (milliseconds)
        liveness_period: Liveness period duration (milliseconds)

    Returns:
        bool: True if within liveness period

    Raises:
        TimeValidationError: If parameters are invalid
    """
    if liveness_period <= 0:
        raise TimeValidationError("Liveness period must be positive")

    if creation_time < MIN_TIMESTAMP:
        raise TimeValidationError("Invalid creation time")

    return current_time <= creation_time + liveness_period


def is_reward_expired(
    consensus_time: int, current_time: int, dismissal_period: int
) -> bool:
    """Check if reward consensus has expired.

    Args:
        consensus_time: Consensus timestamp (milliseconds)
        current_time: Current time (milliseconds)
        dismissal_period: Dismissal period duration (milliseconds)

    Returns:
        bool: True if reward has expired

    Raises:
        TimeValidationError: If parameters are invalid
    """
    if dismissal_period <= 0:
        raise TimeValidationError("Dismissal period must be positive")

    if consensus_time < MIN_TIMESTAMP:
        raise TimeValidationError("Invalid consensus time")

    return current_time > consensus_time + dismissal_period


def validate_message_timestamp(
    msg: AggregateMessage,
    settings: OracleSettingsDatum,
    current_time: int,
    max_age: int | None = None,
) -> bool:
    """Validate aggregate message timestamp.

    Args:
        msg: Aggregate message to validate
        settings: Oracle settings
        current_time: Current time (milliseconds)
        max_age: Optional maximum age override (milliseconds)

    Returns:
        bool: True if timestamp is valid

    Raises:
        TimeValidationError: If validation fails
    """
    try:
        # Use settings uncertainty window if max_age not specified
        time_window = max_age or settings.time_absolute_uncertainty

        # Basic timestamp validation
        if not is_valid_timestamp(msg.timestamp, current_time, time_window):
            logger.warning(
                "Message timestamp %d outside valid range (current: %d, window: %d)",
                msg.timestamp,
                current_time,
                time_window,
            )
            return False

        # Check if oracle is closing
        if not isinstance(settings.closing_period_started_at, NoDatum):
            logger.warning("Cannot process message - oracle is in closing period")
            return False

        # Validate against liveness period
        if not is_within_liveness_period(
            msg.timestamp, current_time, settings.aggregation_liveness_period
        ):
            logger.warning(
                "Message timestamp %d outside liveness period (current: %d, period: %d)",
                msg.timestamp,
                current_time,
                settings.aggregation_liveness_period,
            )
            return False

        return True

    except Exception as e:
        raise TimeValidationError(f"Failed to validate message timestamp: {e}") from e


def calculate_expiry_time(
    creation_time: int, liveness_period: int, buffer: int = 0
) -> int:
    """Calculate expiry time for oracle feed.

    Args:
        creation_time: Creation timestamp (milliseconds)
        liveness_period: Liveness period duration (milliseconds)
        buffer: Optional additional buffer time (milliseconds)

    Returns:
        int: Expiry timestamp

    Raises:
        TimeValidationError: If parameters are invalid
    """
    if liveness_period <= 0:
        raise TimeValidationError("Liveness period must be positive")

    if buffer < 0:
        raise TimeValidationError("Buffer cannot be negative")

    if creation_time < MIN_TIMESTAMP:
        raise TimeValidationError("Invalid creation time")

    return creation_time + liveness_period + buffer
