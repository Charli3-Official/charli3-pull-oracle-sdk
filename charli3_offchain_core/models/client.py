from pydantic import BaseModel, model_serializer

from charli3_offchain_core.models.base import TxValidityInterval
from charli3_offchain_core.models.message import SignedOracleNodeMessage


class OdvFeedRequest(BaseModel):
    """Request feed from oracle node"""

    oracle_nft_policy_id: str
    tx_validity_interval: TxValidityInterval


class OdvTxSignatureRequest(BaseModel):
    """Request signature from oracle node"""

    node_messages: dict[str, SignedOracleNodeMessage]
    tx_cbor: str

    @model_serializer
    def serialize(self) -> dict[str, dict]:
        return {
            "node_messages": {k: v.model_dump() for k, v in self.node_messages.items()},
            "tx_cbor": self.tx_cbor,
        }
