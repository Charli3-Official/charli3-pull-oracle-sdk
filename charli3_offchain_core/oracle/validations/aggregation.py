"""Validation functions for ODV aggregation related operations."""

import logging
from typing import Any

from pycardano import ScriptHash, Transaction

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.models.base import PosixTime
from charli3_offchain_core.models.message import SignedOracleNodeMessage
from charli3_offchain_core.models.oracle_datums import (
    AggState,
    OracleSettingsDatum,
    RewardConsensusPending,
    RewardTransportVariant,
)
from charli3_offchain_core.oracle.utils.calc_methods import median
from charli3_offchain_core.oracle.utils.common import get_script_utxos, try_parse_datum
from charli3_offchain_core.oracle.utils.state_checks import (
    get_oracle_settings_by_policy_id,
    is_oracle_paused,
)

logger = logging.getLogger(__name__)


def validate_timestamp(tx_validity: dict[str, PosixTime], timestamp: PosixTime) -> None:
    """Validates if the given timestamp falls within the transaction validity window."""
    start = tx_validity.start if hasattr(tx_validity, "start") else tx_validity["start"]
    end = tx_validity.end if hasattr(tx_validity, "end") else tx_validity["end"]

    if not start <= timestamp <= end:
        raise ValueError(
            f"Timestamp {timestamp} outside validity interval " f"[{start}, {end}]"
        )


async def validate_is_node_registered(
    tx_manager: TransactionManager, oracle_addr: str, policy_id: str, node_vkh: str
) -> tuple[bool, OracleSettingsDatum]:
    """Verifies if the node is registered in oracle settings and returns registration status with settings."""
    try:
        utxos = await get_script_utxos(oracle_addr, tx_manager)
        settings_datum, settings_utxo = get_oracle_settings_by_policy_id(
            utxos, ScriptHash(bytes.fromhex(policy_id))
        )
        if settings_utxo is None:
            raise ValueError("Oracle settings not found")

        if is_oracle_paused(settings_datum):
            raise ValueError("Oracle is currently paused")

        if node_vkh not in settings_datum.nodes.node_map:
            raise ValueError(f"Node {node_vkh} not registered")
        return True, settings_datum
    except Exception as e:
        raise ValueError(f"Node registration validation error: {e!s}") from e


def validate_node_message_signatures(
    node_messages: list[dict[str, Any]]
) -> list[SignedOracleNodeMessage]:
    """Validates signatures of node messages and returns list of serialized responses."""
    signed_messages = []
    try:
        for node_message in node_messages:
            signed_message = SignedOracleNodeMessage.model_validate(node_message)
            signed_messages.append(signed_message)
        return signed_messages
    except Exception as e:
        raise ValueError(f"Signature validation error: {e!s}") from e


def validate_policy_id_in_messages(node_messages: list[SignedOracleNodeMessage]) -> str:
    """Validates Oracle NFT policy ID consistency across messages and returns the policy ID."""
    policy_ids = {data.message.oracle_nft_policy_id for data in node_messages}
    if len(policy_ids) == 1:
        return bytes.hex(policy_ids.pop())
    raise ValueError("Mismatch in oracle_nft_policy_id across messages") from None


def validate_node_updates_and_aggregation_median(
    signed_messages: list[SignedOracleNodeMessage],
    transport_datum: RewardConsensusPending,
) -> bool:
    """Validates median calculation against node messages and returns success status."""
    try:
        aggregation = transport_datum.aggregation
        node_feeds = aggregation.message.node_feeds_sorted_by_feed

        feeds = []
        for signed_msg in signed_messages:
            vkh = signed_msg.verification_key.hash()
            if vkh not in node_feeds:
                raise ValueError(f"Node {vkh} message not in aggregation")

            tx_feed = node_feeds[vkh]
            msg_feed = signed_msg.message.feed

            if tx_feed != msg_feed:
                raise ValueError(
                    f"Feed mismatch for node {vkh}: {tx_feed} vs {msg_feed}"
                )

            feeds.append(tx_feed)

        calculated_median = median(feeds, len(feeds))
        if calculated_median != aggregation.oracle_feed:
            raise ValueError(
                f"Median mismatch: {calculated_median} vs {aggregation.oracle_feed}"
            )

        return True
    except Exception as e:
        raise ValueError(f"Median validation error: {e!s}") from e


def validate_transaction_datums(
    tx: Transaction, oracle_addr: str
) -> tuple[RewardTransportVariant, AggState]:
    """Extracts and validates reward transport and aggregation state datums from transaction outputs."""
    transport_datum: RewardTransportVariant | None = None
    agg_state_datum: AggState | None = None

    for output in tx.transaction_body.outputs:
        if str(output.address) != oracle_addr or not output.datum:
            continue

        if transport_datum is None:
            transport_datum = try_parse_datum(output.datum, RewardTransportVariant)
        if agg_state_datum is None:
            agg_state_datum = try_parse_datum(output.datum, AggState)

        if transport_datum and agg_state_datum:
            break

    if not transport_datum or not agg_state_datum:
        raise ValueError("Missing or invalid transaction datums")

    return transport_datum, agg_state_datum
