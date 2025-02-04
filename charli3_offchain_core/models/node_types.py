from dataclasses import dataclass

from opshin import sha256
from pycardano import (
    BIP32ED25519PublicKey,
    ConstrainedBytes,
    ExtendedSigningKey,
    PlutusData,
    SigningKey,
    VerificationKey,
)

from charli3_offchain_core.models.extension_types import PosixTime


class Ed25519Signature(ConstrainedBytes):
    """Ed25519 signature constrained to 64 bytes."""

    MAX_SIZE = MIN_SIZE = 64

    @classmethod
    def from_hex(cls, hex_str: str) -> "Ed25519Signature":
        """Create signature from hex string."""
        try:
            return cls.from_primitive(hex_str)
        except (ValueError, AssertionError, TypeError) as err:
            raise ValueError("Invalid Ed25519 signature format") from err


@dataclass
class OracleNodeMessage(PlutusData):
    """Oracle node message containing feed data."""

    CONSTR_ID = 0
    feed: int
    timestamp: PosixTime
    oracle_nft_policy_id: bytes

    def get_message_digest(self) -> bytes:
        """Get message digest for signing."""
        return sha256(self.to_cbor()).digest()

    def sign(self, key: SigningKey | ExtendedSigningKey) -> Ed25519Signature:
        """Create message signature using signing key."""
        return Ed25519Signature.from_primitive(key.sign(self.get_message_digest()))


@dataclass
class SignedOracleNodeMessage:
    """Container for signed oracle message"""

    message: OracleNodeMessage
    signature: Ed25519Signature | None = None
    verification_key: VerificationKey | None = None

    def validate(self) -> bool:
        if not (self.signature and self.verification_key):
            return False

        try:
            return BIP32ED25519PublicKey(
                self.verification_key.payload[:32], self.verification_key.payload[32:]
            ).verify(self.signature.payload, self.message.get_message_digest())
        except Exception as e:
            print(f"Validation error: {e!s}")
            return False

    def to_json(self) -> dict:
        return {
            "feed": str(self.message.feed),
            "timestamp": self.message.timestamp,
            "oracle_nft_policy_id": self.message.oracle_nft_policy_id.hex(),
            "signature": self.signature.payload.hex() if self.signature else None,
            "verification_key": (
                self.verification_key.to_primitive().hex()
                if self.verification_key
                else None
            ),
        }

    @classmethod
    def from_json(cls, data: dict) -> "SignedOracleNodeMessage":
        return cls(
            message=OracleNodeMessage(
                feed=int(data["feed"]),
                timestamp=data["timestamp"],
                oracle_nft_policy_id=bytes.fromhex(data["oracle_nft_policy_id"]),
            ),
            signature=(
                Ed25519Signature.from_hex(data["signature"])
                if data.get("signature")
                else None
            ),
            verification_key=(
                VerificationKey.from_primitive(bytes.fromhex(data["verification_key"]))
                if data.get("verification_key")
                else None
            ),
        )
