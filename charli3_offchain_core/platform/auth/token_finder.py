"""Platform authorization NFT finding utilities."""

import logging

from pycardano import (
    ScriptHash,
    UTxO,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery

logger = logging.getLogger(__name__)


class PlatformAuthFinder:
    """Utility for finding platform authorization NFTs"""

    def __init__(self, chain_query: ChainQuery) -> None:
        self.chain_query = chain_query

    async def find_auth_utxo(
        self, policy_id: bytes, platform_address: str
    ) -> UTxO | None:
        """Find platform authorization NFT UTxO."""
        try:
            policy_hash = ScriptHash(bytes.fromhex(policy_id))
            utxos = await self.chain_query.get_utxos(platform_address)
            return next(
                (utxo for utxo in utxos if self._has_policy_token(utxo, policy_hash)),
                None,
            )
        except Exception as e:
            logger.error("Error finding auth NFT: %s", str(e))
            return None

    def _has_policy_token(self, utxo: UTxO, policy_hash: ScriptHash) -> bool:
        """Check if UTxO contains token from policy."""
        return (
            utxo.output.amount.multi_asset is not None
            and policy_hash in utxo.output.amount.multi_asset
        )
