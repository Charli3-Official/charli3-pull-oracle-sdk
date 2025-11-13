""" Common utility functions for oracle operations. """

import time
from typing import Any

from pycardano import (
    Address,
    AssetName,
    RawPlutusData,
    ScriptHash,
    UTxO,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.models.oracle_datums import (
    AggState,
    SomeAsset,
)
from charli3_offchain_core.models.oracle_redeemers import AggregateMessage

from ..exceptions import TransactionError, ValidationError


async def get_script_utxos(
    script_address: Address, tx_manager: TransactionManager
) -> list[UTxO]:
    """Get and validate UTxOs at script address."""
    try:
        utxos = await tx_manager.chain_query.get_utxos(script_address)
        if not utxos:
            raise ValidationError("No UTxOs found at script address")
        return utxos
    except Exception as e:
        raise TransactionError(f"Failed to get script UTxOs: {e}") from e


def get_fee_rate_reference_utxo(chain_query: ChainQuery, rate_nft: SomeAsset) -> UTxO:
    """Get fee rate UTxOs and return the most fresh Aggregation State."""
    try:
        rate_policy_id = ScriptHash.from_primitive(rate_nft.asset.policy_id)
        rate_name = AssetName.from_primitive(rate_nft.asset.name)

        utxos = chain_query.get_utxos_with_asset_from_kupo(rate_policy_id, rate_name)
        if not utxos:
            raise ValidationError("No UTxOs found with asset name")

        for utxo in utxos:
            if utxo.output.datum and utxo.output.datum.cbor:
                utxo.output.datum = AggState.from_cbor(utxo.output.datum.cbor)

        current_time = int(time.time_ns() * 1e-6)
        non_expired_agg_states = [
            utxo
            for utxo in utxos
            if utxo.output.datum
            and isinstance(utxo.output.datum, AggState)
            and utxo.output.datum.price_data.is_valid
            and utxo.output.datum.price_data.is_active(current_time)
        ]
        if not non_expired_agg_states:
            raise ValidationError(
                "No Aggregation State Rate datum with fresh timestamp"
            )

        non_expired_agg_states.sort(
            key=lambda utxo: utxo.output.datum.price_data.get_expirity_time
        )
        return non_expired_agg_states.pop()
    except Exception as e:
        raise TransactionError(f"Failed to get fee rate UTxOs: {e}") from e


def get_reference_script_utxo(utxos: list[UTxO]) -> UTxO:
    """Find reference script UTxO.

    Args:
        utxos: List of UTxOs to search

    Returns:
        UTxO: Reference script UTxO

    Raises:
        StateValidationError: If no reference script UTxO is found
    """
    for utxo in utxos:
        if utxo.output.script:
            return utxo

    raise ValidationError("No reference script UTxO found")


# def build_aggregate_message(
#     nodes_messages: list[SignedOracleNodeMessage],
#     timestamp: PosixTime,
# ) -> AggregateMessage:
#     """Build aggregate message from node messages and timestamp.

#     Args:
#         nodes_messages: List of signed oracle messages from nodes
#         timestamp: POSIX timestamp in milliseconds

#     Returns:
#         AggregateMessage with sorted feeds and provided timestamp

#     Raises:
#         ValueError: If no messages provided or signature validation fails
#     """
#     if not nodes_messages:
#         raise ValueError("No node messages provided")

#     for msg in nodes_messages:
#         try:
#             msg.validate_signature()
#         except ValueError as e:
#             raise ValueError(f"Invalid message signature: {e}") from e

#     feeds = {msg.verification_key.hash(): msg.message.feed for msg in nodes_messages}

#     sorted_feeds = dict(sorted(feeds.items(), key=lambda x: x[1]))

#     return AggregateMessage(
#         node_feeds_sorted_by_feed=sorted_feeds,
#         node_feeds_count=len(sorted_feeds),
#         timestamp=timestamp,
#     )


def build_aggregate_message(nodes_messages: list) -> AggregateMessage:
    if not nodes_messages:
        raise ValueError("No node messages provided")

    for msg in nodes_messages:
        msg.validate_signature()

    feeds = {}
    for msg in nodes_messages:
        vkh = msg.verification_key.hash()
        print(f"VKH length: {len(vkh.payload)} bytes (should be 28)")
        print(f"VKH hex: {vkh.to_primitive().hex()}")

        feeds[vkh] = msg.message.feed

    sorted_feeds = dict(sorted(feeds.items(), key=lambda x: x[0].payload))
    return AggregateMessage(node_feeds_sorted_by_feed=sorted_feeds)


# def build_aggregate_message(
#     nodes_messages: list,  # SignedOracleNodeMessage
# ) -> AggregateMessage:
#     """Build aggregate message from node messages.

#     IMPORTANT: timestamp is NOT part of the on-chain AggregateMessage.
#     The on-chain validator uses the transaction validity range for timing.

#     Args:
#         nodes_messages: List of signed oracle messages from nodes

#     Returns:
#         AggregateMessage with sorted feeds

#     Raises:
#         ValueError: If no messages provided or signature validation fails
#     """
#     if not nodes_messages:
#         raise ValueError("No node messages provided")

#     for msg in nodes_messages:
#         try:
#             msg.validate_signature()
#         except ValueError as e:
#             raise ValueError(f"Invalid message signature: {e}") from e

#     feeds = {msg.verification_key.hash(): msg.message.feed for msg in nodes_messages}

#     sorted_feeds = dict(sorted(feeds.items(), key=lambda x: x[0].payload))

#     return AggregateMessage(node_feeds_sorted_by_feed=sorted_feeds)


def try_parse_datum(datum: RawPlutusData, datum_class: Any) -> Any:
    """Attempt to parse a datum using the provided class."""
    try:
        return datum_class.from_cbor(datum.to_cbor())
    except Exception:
        return None
