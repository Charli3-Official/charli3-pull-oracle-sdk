from dataclasses import dataclass
from typing import Annotated

from opshin import sha256
from pycardano import (
    PlutusData,
    ScriptHash,
    VerificationKey,
    BIP32ED25519PublicKey,
    ConstrainedBytes,
)
from pydantic import BaseModel, BeforeValidator
import nacl.exceptions


class Ed25519Signature(ConstrainedBytes):
    """Ed25519 signatures are only 512-bits (64 bytes)"""

    MAX_SIZE = MIN_SIZE = 64


def validate_policy_id(value: str) -> str:
    """Validate that a hex string corresponds to a plutus script hash."""
    try:
        policy_id = ScriptHash.from_primitive(value)
        return policy_id.payload.hex()
    except (ValueError, AssertionError, TypeError) as err:
        raise ValueError(
            "Policy Id should be a valid script hash (28 bytes) in hex format",
        ) from err


def validate_positive_int(value: str) -> str:
    """Validate that a string can be converted to a positive integer."""
    try:
        num = int(value)
        if num <= 0:
            raise ValueError(num)
        return value
    except ValueError as err:
        raise ValueError("Value must be a positive integer") from err


def validate_timestamp(value: str) -> str:
    """Validate that a string represents a valid POSIX timestamp in milliseconds."""
    try:
        ts = int(value)
        # Basic sanity checks for millisecond timestamp
        # Lower bound: 2020-01-01 (~1577836800000)
        # Upper bound: 2100-01-01 (~4102444800000)
        if not (1577836800000 <= ts <= 4102444800000):
            raise ValueError(ts)
        return value
    except ValueError as err:
        raise ValueError(
            "timestamp must be a valid POSIX time in milliseconds"
        ) from err


@dataclass
class OracleNodeMessage(PlutusData):
    CONSTR_ID = 0
    feed: int
    timestamp: int
    oracle_nft_policy_id: bytes

    def check_node_signature(
        self, node_pub_key: VerificationKey, signature: Ed25519Signature
    ) -> bool:
        hash_digest = sha256(self.to_cbor())
        try:
            BIP32ED25519PublicKey(
                node_pub_key.payload[:32], node_pub_key.payload[32:]
            ).verify(signature.payload, hash_digest.digest())
            return True
        except nacl.exceptions.BadSignatureError:
            return False


class OracleNodeMessageSerializer(BaseModel):
    feed: Annotated[str, BeforeValidator(validate_positive_int)]
    timestamp: Annotated[str, BeforeValidator(validate_timestamp)]
    oracle_nft_policy_id_hex: Annotated[str, BeforeValidator(validate_policy_id)]

    @classmethod
    def ser(cls, node_message: OracleNodeMessage) -> "OracleNodeMessageSerializer":
        return cls(
            feed=str(node_message.feed),
            timestamp=str(node_message.timestamp),
            oracle_nft_policy_id_hex=node_message.oracle_nft_policy_id.hex(),
        )

    @property
    def deser(self) -> OracleNodeMessage:
        return OracleNodeMessage(
            feed=int(self.feed),
            timestamp=int(self.timestamp),
            oracle_nft_policy_id=bytes.fromhex(self.oracle_nft_policy_id_hex),
        )


class OdvClientAPI:
    pass
