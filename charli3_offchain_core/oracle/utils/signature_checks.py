"""Utilities for validating oracle node signatures and message authenticity."""

import logging
import time

from pycardano import VerificationKey

from charli3_offchain_core.models.oracle_datums import (
    AggregateMessage,
    OracleSettingsDatum,
)
from charli3_offchain_core.oracle.exceptions import SignatureError, ThresholdError

logger = logging.getLogger(__name__)


def validate_node_signatures(
    message: AggregateMessage, node_signatures: list[bytes], node_keys: list[bytes]
) -> bool:
    """Validate node signatures for aggregate message.

    Args:
        message: Aggregate message to validate
        node_signatures: List of node signatures
        node_keys: List of node verification keys

    Returns:
        bool: True if signatures are valid

    Raises:
        SignatureError: If signature validation fails
    """
    try:
        if len(node_signatures) != len(node_keys):
            raise SignatureError("Signature and key count mismatch")

        message_bytes = encode_oracle_feed(message.oracle_feed, message.timestamp)

        # Verify each signature
        for signature, key_bytes in zip(node_signatures, node_keys):
            try:
                key = VerificationKey.from_primitive(key_bytes)
                if not key.verify(message_bytes, signature):
                    logger.warning("Invalid signature detected")
                    return False
            except Exception as e:
                logger.error("Signature verification failed: %s", e)
                return False

        return True

    except Exception as e:
        raise SignatureError(f"Failed to validate node signatures: {e}") from e


def check_signature_threshold(valid_signatures: int, required_count: int) -> bool:
    """Check if number of valid signatures meets threshold.

    Args:
        valid_signatures: Number of valid signatures
        required_count: Required signature count

    Returns:
        bool: True if threshold is met

    Raises:
        ThresholdError: If threshold check fails
    """
    try:
        if required_count < 1:
            raise ThresholdError("Required count must be positive")

        if valid_signatures < 0:
            raise ThresholdError("Valid signature count cannot be negative")

        return valid_signatures >= required_count

    except Exception as e:
        raise ThresholdError(f"Failed to check signature threshold: {e}") from e


def encode_oracle_feed(feed_value: int, timestamp: int, node_id: int = 0) -> bytes:
    """Encode oracle feed data for signature verification.

    Args:
        feed_value: Oracle feed value
        timestamp: Feed timestamp
        node_id: Optional node ID

    Returns:
        bytes: Encoded feed data

    Raises:
        SignatureError: If encoding fails
    """
    try:
        # Encode components as big-endian bytes
        feed_bytes = feed_value.to_bytes(8, byteorder="big", signed=False)
        time_bytes = timestamp.to_bytes(8, byteorder="big", signed=False)
        node_bytes = node_id.to_bytes(4, byteorder="big", signed=False)

        return feed_bytes + time_bytes + node_bytes

    except Exception as e:
        raise SignatureError(f"Failed to encode oracle feed: {e}") from e


def validate_message_nodes(
    msg: AggregateMessage, settings: OracleSettingsDatum
) -> bool:
    """Validate nodes in aggregate message against oracle settings.

    Args:
        msg: Aggregate message to validate
        settings: Oracle settings datum

    Returns:
        bool: True if message nodes are valid

    Raises:
        SignatureError: If validation fails
    """
    try:
        # Get set of registered node IDs
        registered_nodes = {node.feed_vkh for node in settings.nodes}

        # Get set of nodes in message
        message_nodes = set(msg.node_feeds_sorted_by_feed.keys())

        # Validate all message nodes are registered
        if not message_nodes.issubset(registered_nodes):
            logger.warning("Message contains unregistered nodes")
            return False

        # Validate node count matches
        if msg.node_feeds_count != len(message_nodes):
            logger.warning("Node count mismatch in message")
            return False

        return True

    except Exception as e:
        raise SignatureError(f"Failed to validate message nodes: {e}") from e


def get_valid_node_set(
    node_feeds: list[int],
    node_signatures: list[bytes],
    node_keys: list[bytes],
    node_ids: list[int],
) -> set[int]:
    """Get set of nodes with valid signatures.

    Args:
        node_feeds: List of feed values
        node_signatures: List of signatures
        node_keys: List of verification keys
        node_ids: List of node IDs

    Returns:
        Set of node IDs with valid signatures

    Raises:
        SignatureError: If validation fails
    """
    try:
        if not (
            len(node_feeds) == len(node_signatures) == len(node_keys) == len(node_ids)
        ):
            raise SignatureError("Input lists must have same length")

        valid_nodes = set()

        for feed, sig, key, node_id in zip(
            node_feeds, node_signatures, node_keys, node_ids
        ):
            try:
                message = encode_oracle_feed(feed, int(time.time()), node_id)
                key_obj = VerificationKey.from_primitive(key)
                if key_obj.verify(message, sig):
                    valid_nodes.add(node_id)
            except Exception as e:  # pylint: disable=broad-except
                logger.warning(
                    "Signature validation failed for node %d: %s", node_id, e
                )

        return valid_nodes

    except Exception as e:
        raise SignatureError(f"Failed to get valid node set: {e}") from e
