"""Node simulator implementation."""

import logging
import secrets
import time

from pycardano import Transaction, TransactionWitnessSet, VerificationKeyWitness

from charli3_offchain_core.models.client import OdvFeedRequest, OdvTxSignatureRequest
from charli3_offchain_core.models.message import (
    OracleNodeMessage,
    SignedOracleNodeMessage,
)

from .models import SimulatedNode

logger = logging.getLogger(__name__)


class NodeSimulator:
    """Simulates a single ODV node's behavior."""

    def __init__(self, node: SimulatedNode, base_feed: int, variance: float) -> None:
        """Initialize node simulator.

        Args:
            node: Simulated node instance with keys
            base_feed: Base feed value
            variance: Maximum variance percentage (0-1)
        """
        self.node = node
        self.base_feed = base_feed
        self.variance = variance

    def _generate_feed(self) -> int:
        """Generate feed value with random variance."""
        variance_amount = self.base_feed * (
            (secrets.randbelow(10000) / 10000.0) * self.variance
        )
        return self.base_feed + int(variance_amount)

    async def handle_feed_request(
        self, request: OdvFeedRequest
    ) -> tuple[str, SignedOracleNodeMessage | None]:
        """Handle ODV feed request."""
        try:
            # Generate feed with variance
            feed_value = self._generate_feed()
            timestamp = int(time.time() * 1000)

            # Create and sign message
            message = OracleNodeMessage(
                feed=feed_value,
                timestamp=timestamp,
                oracle_nft_policy_id=bytes.fromhex(request.oracle_nft_policy_id),
            )

            signature = message.sign(self.node.signing_key)

            logger.info(f"Node {self.node.hex_feed_vkh} generated Feed: {feed_value}")

            signed_message = SignedOracleNodeMessage(
                message=message,
                signature=signature,
                verification_key=self.node.verification_key,
            )

            return self.node.hex_feed_vkh, signed_message

        except Exception as e:
            logger.error(
                f"Feed request failed for node {self.node.hex_feed_vkh}: {e!s}"
            )
            return self.node.hex_feed_vkh, None

    async def handle_sign_request(
        self, request: OdvTxSignatureRequest
    ) -> Transaction | None:
        """Handle ODV transaction signing request."""
        try:
            tx = Transaction.from_cbor(request.tx_cbor)

            # Sign transaction
            if tx.transaction_witness_set is None:
                tx.transaction_witness_set = TransactionWitnessSet()

            signature = self.node.signing_key.sign(tx.transaction_body.hash())
            witness = VerificationKeyWitness(
                vkey=self.node.verification_key, signature=signature
            )
            tx.transaction_witness_set.vkey_witnesses.append(witness)

            logger.info(f"Node {self.node.hex_feed_vkh[:8]} signed transaction")
            return tx

        except Exception as e:
            logger.error(
                f"Sign request failed for node {self.node.hex_feed_vkh}: {e!s}"
            )
            return None

    @property
    def vkh(self) -> str:
        """Get node's verification key hash."""
        return self.node.hex_feed_vkh
