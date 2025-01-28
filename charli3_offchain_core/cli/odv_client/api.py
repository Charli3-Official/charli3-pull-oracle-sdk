import asyncio
from dataclasses import dataclass
from typing import Annotated, Any

import aiohttp
import nacl.exceptions
from opshin import sha256
from pycardano import (
    BIP32ED25519PublicKey,
    ConstrainedBytes,
    ExtendedSigningKey,
    PlutusData,
    ScriptHash,
    SigningKey,
    Transaction,
    VerificationKey,
)
from pycardano.witness import VerificationKeyWitness
from pydantic import BaseModel, BeforeValidator

from charli3_offchain_core.cli.config.odv_client import NodeNetworkId


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

    def sign(self, signing_key: SigningKey | ExtendedSigningKey) -> Ed25519Signature:
        hash_digest = sha256(self.to_cbor())
        signature = signing_key.sign(hash_digest.digest())
        return Ed25519Signature.from_primitive(signature)


@dataclass
class SignedOracleNodeMessage:
    message: OracleNodeMessage
    verification_key: VerificationKey
    signature: Ed25519Signature


class SignedOracleNodeMessageSerializer(BaseModel):
    feed: str
    timestamp: int
    oracle_nft_policy_id: str
    verification_key: str
    signature: str

    @classmethod
    def ser(
        cls, node_message: SignedOracleNodeMessage
    ) -> "SignedOracleNodeMessageSerializer":
        return cls(
            feed=str(node_message.message.feed),
            timestamp=(node_message.message.timestamp),
            oracle_nft_policy_id=node_message.message.oracle_nft_policy_id.hex(),
            verification_key=node_message.verification_key.to_primitive().hex(),
            signature=node_message.signature.to_primitive().hex(),
        )


class TxValidityIntervalSerializer(BaseModel):
    start: int
    end: int


class OdvMessageRequest(BaseModel):
    tx_validity_interval: TxValidityIntervalSerializer
    oracle_nft_policy_id: Annotated[str, BeforeValidator(validate_policy_id)]

    @classmethod
    def ser(
        cls,
        odv_validity_start: int,
        odv_validity_end: int,
        oracle_nft_policy_id: ScriptHash,
    ) -> "OdvMessageRequest":
        return cls(
            tx_validity_interval=TxValidityIntervalSerializer(
                start=odv_validity_start, end=odv_validity_end
            ),
            oracle_nft_policy_id=oracle_nft_policy_id.payload.hex(),
        )


class OdvTxRequest(BaseModel):
    nodes_messages: dict[str, SignedOracleNodeMessageSerializer]
    tx_cbor: str

    @classmethod
    def ser(
        cls,
        nodes: list[NodeNetworkId],
        nodes_messages: list[SignedOracleNodeMessage],
        tx: Transaction,
    ) -> "OdvTxRequest":
        return cls(
            nodes_messages={
                node.pub_key.to_primitive().hex(): SignedOracleNodeMessageSerializer.ser(
                    msg
                )
                for node, msg in zip(nodes, nodes_messages)
            },
            tx_cbor=tx.to_cbor_hex(),
        )


class OdvMessageResponse(BaseModel):
    # TODO feed is str or int
    # TODO timestamp is str or int
    feed: int
    timestamp: int
    # TODO verification_key
    signature: Annotated[str, BeforeValidator(validate_signature_ser)]


class OdvTxResponse(BaseModel):
    signed_tx_cbor: str


class OdvApiClient:
    """
    Use as context manager: async with OdvApiClient() as client
    """

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 120,  # Ideally timeout should be set to half of tx validity interval length
    ) -> None:
        if headers is None:
            self._headers = {
                "Content-type": "application/json",
                "Accepts": "application/json",
            }
        self._timeout = aiohttp.ClientTimeout(timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "OdvApiClient":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
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
    ) -> SignedOracleNodeMessage:
        session = self._get_session()
        async with session.request(
            "POST",
            f"{node.root_url}/odv/feed",
            data=req.model_dump_json(),
            headers=self._headers,
            timeout=self._timeout,
        ) as resp:
            if not resp.ok:
                raise UnsuccessfulResponseError(resp.status)
            json_payload = await resp.read()
            resp_obj = OdvMessageResponse.model_validate_json(json_payload)
            node_msg = OracleNodeMessage(
                feed=(resp_obj.feed),
                timestamp=(resp_obj.timestamp),
                oracle_nft_policy_id=bytes.fromhex(req.oracle_nft_policy_id),
            )
            signature = Ed25519Signature.from_primitive(resp_obj.signature)
            if not node_msg.check_node_signature(
                node.pub_key,
                signature,
            ):
                raise InvalidNodeSignatureError(node.pub_key.payload.hex())
            return SignedOracleNodeMessage(
                message=node_msg, signature=signature, verification_key=node.pub_key
            )

    async def odv_tx_request(
        self,
        req: OdvTxRequest,
        tx: Transaction,
        node: NodeNetworkId,
    ) -> VerificationKeyWitness:
        session = self._get_session()
        async with session.request(
            "POST",
            f"{node.root_url}/odv/aggregation/sign",
            data=req.model_dump_json(),
            headers=self._headers,
            timeout=self._timeout,
        ) as resp:
            if not resp.ok:
                raise UnsuccessfulResponseError(resp.status)
            json_payload = await resp.read()
            resp_obj = OdvTxResponse.model_validate_json(json_payload)
            signed_tx: Transaction = Transaction.from_cbor(resp_obj.signed_tx_cbor)
            if signed_tx.id != tx.id:
                raise InvalidTxError(
                    f"expected {tx.id.payload.hex()}, but got {signed_tx.id.payload.hex()}"
                )
            signature = (signed_tx.transaction_witness_set.vkey_witnesses or [None])[0]
            if signature is None:
                raise InvalidNodeSignatureError("No signature provided")
            return signature

    async def odv_message_requests(
        self, req: OdvMessageRequest, nodes: list[NodeNetworkId]
    ) -> list[SignedOracleNodeMessage]:
        return await asyncio.gather(
            *(self.odv_message_request(req, node) for node in nodes)
        )

    async def odv_tx_requests(
        self,
        nodes_messages: list[SignedOracleNodeMessage],
        tx: Transaction,
        nodes: list[NodeNetworkId],
    ) -> list[VerificationKeyWitness]:
        req = OdvTxRequest.ser(nodes, nodes_messages, tx)
        return await asyncio.gather(
            *(self.odv_tx_request(req, tx, node) for node in nodes)
        )


class UnsuccessfulResponseError(Exception):
    """Used when the response status is more than 400"""


class InvalidNodeSignatureError(Exception):
    """Verification of node message Ed25519 Signature failed"""


class InvalidTxError(Exception):
    """Verification of tx id failed"""
