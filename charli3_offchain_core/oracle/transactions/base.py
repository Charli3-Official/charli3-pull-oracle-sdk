"""Core transactions encompassing common blockchain query operations."""

import logging
from collections.abc import Callable
from urllib.parse import urlparse

from pycardano import (
    Address,
    BlockFrostChainContext,
    MultiAsset,
    NativeScript,
    OgmiosV6ChainContext,
    UTxO,
)
from pycardano.backend.kupo import KupoChainContextExtension

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.keys import KeyManager
from charli3_offchain_core.cli.config.network import NetworkConfig, OgmiosKupoConfig
from charli3_offchain_core.cli.config.update_settings import PlatformTxConfig
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.oracle.transactions.exceptions import UTxONotFoundError
from charli3_offchain_core.platform.auth.token_finder import PlatformAuthFinder

logger = logging.getLogger(__name__)


class BaseTransaction:
    """Common queries used for smart contracts"""

    def __init__(
        self,
        tx_config: PlatformTxConfig,
        status_callback: Callable[[ProcessStatus, str], None] | None = None,
    ) -> None:
        self.tx_config = tx_config
        self.chain_query = self.get_chain_query(self.tx_config.network)
        self.platform_auth_finder = PlatformAuthFinder(self.chain_query)
        self.transaction_manager = TransactionManager(self.chain_query)
        self.key_manager = KeyManager.load_from_config(tx_config.network.wallet)
        self.status_callback = status_callback
        self.current_status = ProcessStatus.NOT_STARTED

    def _update_status(self, status: ProcessStatus, message: str = "") -> None:
        """Update process status and notify callback."""
        self.current_status = status
        if self.status_callback:
            self.status_callback(status, message)

    async def retrieve_utxo_by_asset(
        self, multi_asset: MultiAsset, address: Address
    ) -> UTxO | None:
        """Retrieve a UTxO associated with a specific NFT."""
        try:
            utxos = await self.chain_query.get_utxos(address)
            return next(
                (utxo for utxo in utxos if self._has_asset(utxo, multi_asset)),
                None,
            )
        except Exception as e:
            logger.error("Error finding auth NFT: %s", str(e))
            return None

    def _has_asset(self, utxo: UTxO, multi_asset: MultiAsset) -> bool:
        if not utxo.output.amount.multi_asset:
            return False
        utxo_assets = utxo.output.amount.multi_asset
        for policy_id, assets in multi_asset.items():
            if policy_id not in utxo_assets:
                return False

            utxo_policy_assets = utxo_assets[policy_id]
            for asset_name, amount in assets.items():
                if asset_name not in utxo_policy_assets:
                    return False
                if utxo_policy_assets[asset_name] != amount:
                    return False
        return True

    def parse_ogmios_url(self, url: str) -> tuple[str, int, bool]:
        parsed = urlparse(url)

        secure = parsed.scheme in ("wss", "https")

        host = parsed.hostname or parsed.netloc.split(":")[0]
        port = parsed.port or (443 if secure else 1337)
        return host, port, secure

    def get_chain_query(self, network_config: NetworkConfig) -> ChainQuery:
        blockfrost = None
        ogmios_kupo = None
        try:
            if isinstance(network_config.blockfrost, BlockFrostChainContext):
                blockfrost = BlockFrostChainContext(
                    project_id=network_config.blockfrost.project_id,
                    base_url=network_config.blockfrost.api_url,
                )
            if isinstance(network_config.ogmios_kupo, OgmiosKupoConfig):
                ogmios_wss = network_config.ogmios_kupo.ogmios_url
                host, port, secure = self.parse_ogmios_url(ogmios_wss)

                ogmios = OgmiosV6ChainContext(
                    host=host, port=port, secure=secure, network=network_config.network
                )
                kupo_url = network_config.ogmios_kupo.kupo_url
                ogmios_kupo = KupoChainContextExtension(ogmios, kupo_url)

            if blockfrost is None and ogmios_kupo is None:
                raise ValueError(
                    "At least one of BlockFrost or Ogmios+Kupo must be configured"
                )

            return ChainQuery(blockfrost, ogmios_kupo)

        except ValueError as ve:
            raise ve
        except Exception as err:
            raise ValueError("Error initializing chain query") from err

    @property
    async def get_contract_reference_utxo(self) -> UTxO:
        """Get the reference script UTxO for core settings"""
        utxo = await self.chain_query.get_reference_script_utxo(
            self.tx_config.contract_address,
            self.tx_config.contract_reference,
            self.tx_config.contract_address.payment_part,
        )

        if utxo is None:
            raise UTxONotFoundError(
                f"Reference script UTxO not found for contract: {self.tx_config.contract_address}"
            )

        return utxo

    @property
    async def get_native_script(self) -> NativeScript:
        return await self.platform_auth_finder.get_platform_script(
            self.tx_config.multi_sig.platform_addr
        )

    @property
    async def required_single_signature(self) -> bool:
        """
        Verify if a single signature matches the platform's multisig configuration.
        """
        vk = self.key_manager[1]

        try:
            platform_addr = self.tx_config.multi_sig.platform_addr
            if platform_addr is None:
                raise ValueError("platform_addr is None and cannot be used.")

            try:
                platform_script = await self.platform_auth_finder.get_platform_script(
                    platform_addr
                )
            except Exception as err:
                raise ValueError("Failed to retrieve platform script") from err

            platform_multisig_config = self.platform_auth_finder.get_script_config(
                platform_script
            )
            signers = platform_multisig_config.signers
            if not signers:
                raise ValueError("No signers found in configuration")

            return len(signers) == 1 and signers[0] == vk.hash()

        except ValueError as e:
            logger.error("Signature verification failed %s", e)
            return False
