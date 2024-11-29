"""Models for oracle simulation."""

import time
from dataclasses import dataclass

from nacl.signing import VerifyKey
from pycardano import PaymentSigningKey, PaymentVerificationKey, VerificationKeyHash

from charli3_offchain_core.oracle.utils.signature_checks import encode_oracle_feed


@dataclass
class NodeKeys:
    """Container for node cryptographic keys."""

    signing_key: PaymentSigningKey
    verification_key: PaymentVerificationKey
    feed_vkh: VerificationKeyHash
    payment_vkh: VerificationKeyHash


class SimulatedNode:
    """Represents a simulated oracle node."""

    def __init__(self) -> None:
        """Initialize node with generated keys."""
        # Generate node keys
        self.signing_key = PaymentSigningKey.generate()
        self.verification_key = self.signing_key.to_verification_key()

        # Create verification key hashes
        self.feed_vkh = self.verification_key.hash()
        self.payment_vkh = self.verification_key.hash()

        # Create nacl verify key for signature verification
        self._nacl_verify_key = VerifyKey(self.verification_key.payload)

    @property
    def hex_feed_vkh(self) -> str:
        """Get feed verification key hash as hex."""
        return self.feed_vkh.to_primitive().hex()

    @property
    def hex_payment_vkh(self) -> str:
        """Get payment verification key hash as hex."""
        return self.payment_vkh.to_primitive().hex()

    def sign_feed(self, value: int, timestamp: int | None = None) -> tuple[int, bytes]:
        """Sign feed value and return signature.

        Args:
            value: Feed value to sign
            timestamp: Optional timestamp (uses current time if None)

        Returns:
            Tuple of (timestamp, signature bytes)
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)  # Convert to milliseconds

        # Create message bytes
        message = encode_oracle_feed(value, timestamp)

        # Use pycardano's signing key for signatures
        signature = self.signing_key.sign(message)

        return timestamp, signature

    def verify_feed_signature(
        self, value: int, timestamp: int, signature: bytes
    ) -> bool:
        """Verify a feed signature.

        Args:
            value: Feed value
            timestamp: Timestamp in milliseconds
            signature: Signature to verify

        Returns:
            bool: True if signature is valid
        """
        try:
            message = encode_oracle_feed(value, timestamp)
            # Use nacl's VerifyKey for verification
            self._nacl_verify_key.verify(message, signature)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    @property
    def verify_key_bytes(self) -> bytes:
        """Get raw verification key bytes for signature validation."""
        return self.verification_key.payload

    def to_dict(self) -> dict:
        """Convert node to dictionary representation."""
        return {
            "feed_vkh": self.hex_feed_vkh,
            "payment_vkh": self.hex_payment_vkh,
            "verification_key": self.verify_key_bytes.hex(),
        }

    @classmethod
    def from_signing_key(cls, signing_key: PaymentSigningKey) -> "SimulatedNode":
        """Create node from existing signing key.

        Args:
            signing_key: Payment signing key

        Returns:
            SimulatedNode: New node instance
        """
        node = cls.__new__(cls)  # Create uninitialized instance
        node.signing_key = signing_key
        node.verification_key = signing_key.to_verification_key()
        node.feed_vkh = node.verification_key.hash()
        node.payment_vkh = node.verification_key.hash()
        # Create nacl verify key for signature verification
        node._nacl_verify_key = VerifyKey(node.verification_key.payload)
        return node
