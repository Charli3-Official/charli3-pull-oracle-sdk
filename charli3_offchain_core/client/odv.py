import asyncio
import logging

import aiohttp
from pycardano import Transaction, TransactionWitnessSet

from charli3_offchain_core.cli.config.odv_client import NodeNetworkId
from charli3_offchain_core.models.client import OdvFeedRequest, OdvTxSignatureRequest
from charli3_offchain_core.models.message import SignedOracleNodeMessage

logger = logging.getLogger(__name__)


class ODVClient:
    """Client for ODV node interactions."""

    async def collect_feed_updates(
        self,
        nodes: list[NodeNetworkId],
        feed_request: OdvFeedRequest,
    ) -> dict[str, SignedOracleNodeMessage]:
        """
        Collect feed updates from nodes.

        :param nodes: List of nodes to interact with.
        :param feed_request: The feed request to send to the nodes.
        :return: A dictionary mapping node public keys to their responses.
        """

        async def fetch_from_node(
            session: aiohttp.ClientSession, node: NodeNetworkId
        ) -> tuple[str, SignedOracleNodeMessage | None]:
            try:
                endpoint = f"{node.root_url.rstrip('/')}/odv/feed"
                async with session.post(
                    endpoint, json=feed_request.model_dump()
                ) as response:
                    if response.status != 200:
                        logger.error(f"Error from {node.root_url}: {response.status}")
                        return node.pub_key, None

                    data = await response.json()
                    signed_message = SignedOracleNodeMessage.model_validate(data)
                    return node.pub_key, signed_message

            except Exception as e:
                logger.error(f"Failed to fetch from {node.root_url}: {e!s}")
                return node.pub_key, None

        async with aiohttp.ClientSession() as session:
            tasks = [fetch_from_node(session, node) for node in nodes]
            responses = await asyncio.gather(*tasks)

            return {pkh: msg for pkh, msg in responses if msg is not None}

    async def collect_tx_signatures(
        self,
        nodes: list[NodeNetworkId],
        tx_request: OdvTxSignatureRequest,
    ) -> dict[str, str]:
        """
        Collect transaction signatures from nodes.

        :param nodes: List of nodes to interact with.
        :param tx_request: The transaction signature request to send to the nodes.
        :return: A dictionary mapping node public keys to their signatures.
        """

        async def fetch_signature(
            session: aiohttp.ClientSession, node: NodeNetworkId
        ) -> tuple[str, str | None]:
            try:
                endpoint = f"{node.root_url.rstrip('/')}/odv/sign"
                payload = tx_request.model_dump()
                async with session.post(endpoint, json=payload) as response:
                    if response.status != 200:
                        logger.error(f"Error from {node.root_url}: {response.status}")
                        return node.pub_key, None

                    data = await response.json()
                    logger.debug(f"Received response from {node.root_url}: {data}")
                    return node.pub_key, data["signed_tx_cbor"]

            except aiohttp.ClientError as e:
                logger.error(f"Connection error to {node.root_url}: {e!s}")
                return node.pub_key, None
            except Exception as e:
                logger.error(f"Error processing {node.root_url}: {e!s}")
                return node.pub_key, None

        async with aiohttp.ClientSession() as session:
            tasks = [fetch_signature(session, node) for node in nodes]
            responses = await asyncio.gather(*tasks)

            return {pkh: sig for pkh, sig in responses if sig is not None}

    def attach_tx_signatures(
        self,
        transaction: Transaction,
        signed_txs: dict[str, str],
    ) -> Transaction:
        """
        Attach collected signatures to the transaction.

        :param transaction: The transaction to attach signatures to.
        :param signed_txs: A dictionary of node public keys to their signatures.
        :return: The transaction with attached signatures.
        """
        if transaction.transaction_witness_set is None:
            transaction.transaction_witness_set = TransactionWitnessSet()

        for signed_tx_response in signed_txs.values():
            signed_tx = Transaction.from_cbor(signed_tx_response)
            if (
                signed_tx.transaction_witness_set
                and signed_tx.transaction_witness_set.vkey_witnesses
            ):
                transaction.transaction_witness_set.vkey_witnesses.extend(
                    signed_tx.transaction_witness_set.vkey_witnesses
                )

        return transaction
