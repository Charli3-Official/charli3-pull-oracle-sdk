import asyncio
from dataclasses import dataclass
from typing import Annotated, List

from opshin import sha256
import aiohttp
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


def validate_signature_ser(value: str) -> str:
    """Validate that a hex string corresponds to a Ed25519 Signature."""
    try:
        signature = Ed25519Signature.from_primitive(value)
        return signature.payload.hex()
    except (ValueError, AssertionError, TypeError) as err:
        raise ValueError(
            "Should be a valid Ed25519 Signature (64 bytes) in hex format",
        ) from err


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


class OdvMessageRequest(BaseModel):
    odv_validity_start: Annotated[str, BeforeValidator(validate_timestamp)]
    odv_validity_end: Annotated[str, BeforeValidator(validate_timestamp)]
    oracle_nft_policy_id_hex: Annotated[str, BeforeValidator(validate_policy_id)]

    @classmethod
    def ser(
        cls,
        odv_validity_start: int,
        odv_validity_end: int,
        oracle_nft_policy_id: ScriptHash,
    ) -> "OdvMessageRequest":
        return cls(
            odv_validity_start=str(odv_validity_start),
            odv_validity_end=str(odv_validity_end),
            oracle_nft_policy_id_hex=oracle_nft_policy_id.payload.hex(),
        )


class OdvMessageResponse(BaseModel):
    feed: Annotated[str, BeforeValidator(validate_positive_int)]
    timestamp: Annotated[str, BeforeValidator(validate_timestamp)]
    signature_hex: Annotated[str, BeforeValidator(validate_signature_ser)]


@dataclass
class NodeNetworkId:
    root_url: str
    pub_key: VerificationKey


class OdvApiClient:
    """
    Use as context manager: async with OdvApiClient() as client
    """

    def __init__(
        self,
        headers: dict[str, str] = {
            "Content-type": "application/json",
            "Accepts": "application/json",
        },
        timeout_seconds: int = 120,  # Ideally timeout should be set to half of tx validity interval length
    ) -> None:
        self._headers = headers
        self._timeout = aiohttp.ClientTimeout(timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "OdvApiClient":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError(
                "Client session not initialized. Use async with OdvClientAPI() as client:"
            )
        return self._session

    async def odv_message_request(
        self, req: OdvMessageRequest, node: NodeNetworkId
    ) -> OracleNodeMessage:
        session = self._get_session()
        async with session.request(
            "POST",
            f"{node.root_url}/odv-message",
            data=req.model_dump_json(),
            headers=self._headers,
            timeout=self._timeout,
        ) as resp:
            if not resp.ok:
                raise UnsuccessfulResponse(resp.status)
            json_payload = await resp.read()
            resp_obj = OdvMessageResponse.model_validate_json(json_payload)
            node_msg = OracleNodeMessage(
                feed=int(resp_obj.feed),
                timestamp=int(resp_obj.timestamp),
                oracle_nft_policy_id=bytes.fromhex(req.oracle_nft_policy_id_hex),
            )
            if not node_msg.check_node_signature(
                node.pub_key,
                Ed25519Signature.from_primitive(resp_obj.signature_hex),
            ):
                raise InvalidNodeSignature(node.pub_key.payload.hex())
            return node_msg

    async def odv_message_requests(
        self, req: OdvMessageRequest, nodes: List[NodeNetworkId]
    ) -> List[OracleNodeMessage]:
        return await asyncio.gather(
            *(self.odv_message_request(req, node) for node in nodes)
        )


class UnsuccessfulResponse(Exception):
    """Used when the response status is more than 400"""


class InvalidNodeSignature(Exception):
    """Verification of node message Ed25519 Signature failed"""
