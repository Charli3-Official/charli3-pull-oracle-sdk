"""Validation functions for ODV transaction components."""

import logging
from typing import Any

from charli3_offchain_core.models.node_types import SignedOracleNodeMessage
from charli3_offchain_core.models.oracle_datums import (
    Aggregation,
    OracleSettingsDatum,
    RewardConsensusPending,
)
from charli3_offchain_core.oracle.utils.calc_methods import median

logger = logging.getLogger(__name__)


def validate_timestamp(tx_validity: dict[str, int], timestamp: int) -> None:
    """
    Validate timestamp is within transaction validity interval

    Args:
        tx_validity: dict with start and end timestamps
        timestamp: int timestamp to validate

    Raises:
        TimestampValidationError: If timestamp is outside validity interval
    """
    start = tx_validity.start if hasattr(tx_validity, "start") else tx_validity["start"]
    end = tx_validity.end if hasattr(tx_validity, "end") else tx_validity["end"]

    if not start <= timestamp <= end:
        raise ValueError(
            f"Timestamp {timestamp} outside validity interval " f"[{start}, {end}]"
        )


def validate_node_signatures(
    signed_messages: dict[str, Any]
) -> tuple[bool, str | None]:
    """Validate signatures of all node messages."""
    try:
        for vkey_hex, msg_data in signed_messages.items():
            signed_msg = SignedOracleNodeMessage.from_json(msg_data)
            if not signed_msg.validate():
                return False, f"Invalid signature for node {vkey_hex}"
        return True, None
    except Exception as e:
        return False, f"Signature validation error: {e!s}"


def validate_median_calculation(
    transport_datum: RewardConsensusPending, signed_messages: dict[str, Any]
) -> tuple[bool, str | None]:
    """Validate median calculation against node messages."""
    try:
        aggregation = transport_datum.aggregation
        node_feeds = aggregation.message.node_feeds_sorted_by_feed

        # Collect and validate feed values
        feeds = []
        for _, msg_data in signed_messages.items():
            signed_msg = SignedOracleNodeMessage.from_json(msg_data)
            vkh = signed_msg.verification_key.hash()
            if vkh not in node_feeds:
                return False, f"Node {vkh} message not in aggregation"

            tx_feed = node_feeds[vkh]
            msg_feed = signed_msg.message.feed

            if tx_feed != msg_feed:
                return False, f"Feed mismatch for node {vkh}: {tx_feed} vs {msg_feed}"

            feeds.append(tx_feed)

        # Verify median calculation
        calculated_median = median(feeds, len(feeds))
        if calculated_median != aggregation.oracle_feed:
            return (
                False,
                f"Median mismatch: {calculated_median} vs {aggregation.oracle_feed}",
            )

        return True, None
    except Exception as e:
        return False, f"Median validation error: {e!s}"


def validate_node_rewards(
    aggregation: Aggregation, settings_datum: OracleSettingsDatum
) -> tuple[bool, str | None]:
    """Validate reward distribution matches settings."""
    try:
        # Check reward amount per node
        node_reward = aggregation.node_reward_price
        expected_reward = settings_datum.fee_info.reward_prices.node_fee

        if node_reward != expected_reward:
            return False, f"Node reward mismatch: {node_reward} vs {expected_reward}"

        # Verify rewards are set for all participating nodes
        node_count = len(aggregation.message.node_feeds_sorted_by_feed)
        total_rewards = aggregation.rewards_amount_paid
        expected_total = node_count * node_reward

        if total_rewards < expected_total:
            return (
                False,
                f"Insufficient total rewards: {total_rewards} vs {expected_total}",
            )

        return True, None
    except Exception as e:
        return False, f"Reward validation error: {e!s}"
