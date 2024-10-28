"""Reference script transaction builders for oracle deployment."""

import logging
from dataclasses import dataclass

from pycardano import (
    Address,
    ExtendedSigningKey,
    PaymentSigningKey,
    Transaction,
    UTxO,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import OracleConfiguration
from charli3_offchain_core.oracle.config import OracleScriptConfig
from charli3_offchain_core.oracle.deployment.reference_script_finder import (
    ReferenceScriptFinder,
)

logger = logging.getLogger(__name__)


@dataclass
class ReferenceScriptResult:
    """Result of reference script operations"""

    manager_utxo: UTxO | None
    nft_utxo: UTxO | None
    manager_tx: Transaction | None
    nft_tx: Transaction | None


class ReferenceScriptBuilder:
    """Builds reference script transactions for oracle deployment"""

    def __init__(
        self,
        chain_query: ChainQuery,
        contracts: OracleContracts,
        tx_manager: TransactionManager,
    ) -> None:
        self.chain_query = chain_query
        self.contracts = contracts
        self.tx_manager = tx_manager
        self.script_finder = ReferenceScriptFinder(chain_query, contracts)

    async def prepare_reference_scripts(
        self,
        config: OracleConfiguration,
        script_config: OracleScriptConfig,
        reference_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        platform_utxo: UTxO,
    ) -> ReferenceScriptResult:
        """
        Prepare reference scripts for oracle deployment.

        Args:
            config: Oracle configuration
            script_config: Reference script configuration
            reference_address: Address for reference scripts
            signing_key: Signing key for transactions
            platform_utxo: Platform auth UTxO for NFT script

        Returns:
            ReferenceScriptResult with UTxOs and transactions
        """
        result = ReferenceScriptResult(None, None, None, None)

        # Handle manager script
        if script_config.create_manager_reference:
            result.manager_utxo = await self.script_finder.find_manager_reference(
                reference_address, config
            )

            if not result.manager_utxo:
                logger.info("Creating new manager reference script")
                manager_contract = self.contracts.apply_spend_params(config)
                result.manager_tx = await self.tx_manager.build_reference_script_tx(
                    script=manager_contract.cbor_hex,
                    address=reference_address,
                    signing_key=signing_key,
                    reference_ada=script_config.reference_ada_amount,
                )

        # Handle NFT script
        if script_config.create_nft_reference:
            logger.info("Creating NFT reference script")
            nft_contract = self.contracts.apply_mint_params(
                platform_utxo.output,
                config,
                self.contracts.spend.script_hash,
            )
            result.nft_tx = await self.tx_manager.build_reference_script_tx(
                script=nft_contract.script,
                address=reference_address,
                signing_key=signing_key,
                reference_ada=script_config.reference_ada_amount,
            )

        return result

    async def submit_reference_scripts(
        self,
        result: ReferenceScriptResult,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
    ) -> None:
        """Submit prepared reference script transactions"""
        if result.manager_tx:
            logger.info("Submitting manager reference script transaction")
            await self.tx_manager.sign_and_submit(
                result.manager_tx,
                [signing_key],
            )

        if result.nft_tx:
            logger.info("Submitting NFT reference script transaction")
            await self.tx_manager.sign_and_submit(
                result.nft_tx,
                [signing_key],
            )
