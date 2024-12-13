"""Core transactions encompassing common blockchain query operations."""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse

import click
from pycardano import (
    Address,
    Asset,
    AssetName,
    BlockFrostChainContext,
    MultiAsset,
    NativeScript,
    OgmiosV6ChainContext,
    ScriptHash,
    Transaction,
    UTxO,
)
from pycardano.backend.kupo import KupoChainContextExtension

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.formatting import (
    print_confirmation_message_prompt,
)
from charli3_offchain_core.cli.config.keys import KeyManager
from charli3_offchain_core.cli.config.network import NetworkConfig, OgmiosKupoConfig
from charli3_offchain_core.cli.config.update_settings import PlatformTxConfig
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.models.oracle_datums import OracleSettingsVariant
from charli3_offchain_core.oracle.transactions.exceptions import (
    UTxONotFoundError,
    ValidationError,
)
from charli3_offchain_core.platform.auth.token_finder import PlatformAuthFinder

logger = logging.getLogger(__name__)


class TransactionResult(NamedTuple):
    tx_id: str
    status: ProcessStatus


class MultisigResult(NamedTuple):
    output_path: Path
    threshold: int


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

    async def required_single_signature(self, script: NativeScript) -> bool:
        """
        Verify if a single signature matches the platform's multisig configuration.
        """
        vk = self.key_manager[1]

        try:
            platform_multisig_config = self.platform_auth_finder.get_script_config(
                script
            )
            signers = platform_multisig_config.signers
            if not signers:
                raise ValueError("No signers found in configuration")

            return len(signers) == 1 and signers[0] == vk.hash()

        except ValueError as e:
            logger.error("Signature verification failed %s", e)
            return False

    async def fetch_reference_script_utxo(self) -> UTxO:
        """Find and validate reference script UTxO."""
        try:
            addr = self.tx_config.contract_address
            utxos = await self.chain_query.get_utxos(addr)
            script_utxos = [utxo for utxo in utxos if utxo.output.script]

            if not script_utxos:
                raise ValueError("No UTxO with reference script found")

            return script_utxos[0]
        except Exception as e:
            logger.error("Error finding auth Script UTxO: %s", str(e))
            raise

    async def fetch_auth_utxo_and_script(
        self,
    ) -> tuple[UTxO | None, NativeScript]:
        auth_utxo = await self.platform_auth_finder.find_auth_utxo(
            policy_id=self.tx_config.tokens.platform_auth_policy,
            platform_address=self.tx_config.multi_sig.platform_addr,
        )
        auth_native_script = await self.platform_auth_finder.get_platform_script(
            self.tx_config.multi_sig.platform_addr
        )
        return auth_utxo, auth_native_script

    async def _process_single_signature(
        self, tx_manager: Transaction
    ) -> TransactionResult:
        """Handle single signature transaction processing."""

        print_confirmation_message_prompt(
            "The transaction requires a single signature. Would you like to continue?"
        )
        self._update_status(ProcessStatus.SIGNING_TRANSACTION, "Signing transaction...")
        try:
            status, _ = await self.transaction_manager.sign_and_submit(
                tx_manager, [self.key_manager[0]]
            )
            if status == ProcessStatus.TRANSACTION_CONFIRMED:
                return TransactionResult(str(tx_manager.id), status)

            self._update_status(ProcessStatus.FAILED)
            raise click.ClickException(f"Deployment failed: {status}")
        except Exception as e:
            logger.error("Deployment failed: %s", str(e))
            raise click.ClickException("Transaction signing failed.") from e

    async def _process_multisig(
        self, tx_manager: Transaction, output: Path | None
    ) -> MultisigResult:
        """Handle multisig transaction processing."""

        print_confirmation_message_prompt(
            "PlatformAuth NFT being used requires multisigatures and thus will be stored. Would you like to continue?"
        )
        deployed_core_utxo = await self.get_core_settings_utxo()
        threshold = deployed_core_utxo.output.datum.datum.required_node_signatures_count
        output_path = output or Path("tx_oracle_update_settings.json")

        with output_path.open("w") as f:
            json.dump(
                {
                    "transaction": tx_manager.to_cbor_hex(),
                    "script_address": str(self.tx_config.contract_address),
                    "signed_by": [],
                    "threshold": threshold,
                },
                f,
            )

        return MultisigResult(output_path, threshold)

    async def get_core_settings_utxo(self) -> UTxO:
        if not hasattr(self, "core_settings_asset"):
            self.core_settings_asset = self.get_core_settings_asset

        try:
            utxo = await self.retrieve_utxo_by_asset(
                self.core_settings_asset, self.tx_config.contract_address
            )

            if utxo is None:
                raise UTxONotFoundError(
                    f"Core settings UTxO not found for asset: {self.core_settings_asset}"
                )

            utxo.output.datum = self.parse_settings_datum(utxo)
            return utxo

        except ValidationError as e:
            raise ValidationError(f"Invalid UTxO data for core settings: {e!s}") from e

        except Exception as e:
            raise UTxONotFoundError(
                f"Error retrieving core settings UTxO: {e!s}"
            ) from e

    @property
    def get_core_settings_asset(self) -> MultiAsset:
        name = self.tx_config.token_names.core_settings
        asset_name = AssetName(name.encode())

        minting_policy = ScriptHash.from_primitive(self.tx_config.tokens.oracle_policy)
        asset = Asset({asset_name: 1})

        return MultiAsset({minting_policy: asset})

    def parse_settings_datum(self, utxo: UTxO | None) -> OracleSettingsVariant:

        if utxo is None or utxo.output.datum is None:
            raise ValueError("Invalid core settings UTxO")

        if isinstance(utxo.output.datum, OracleSettingsVariant):
            return utxo.output.datum
        try:
            if hasattr(utxo.output.datum, "cbor"):
                return OracleSettingsVariant.from_cbor(utxo.output.datum.cbor)
            raise ValueError("Datum missing CBOR")
        except Exception as e:
            logger.error("Error %s", e)
