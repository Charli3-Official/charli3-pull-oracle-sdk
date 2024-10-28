"""Reference script finding and validation utilities."""

import logging

from opshin.builder import PlutusContract
from pycardano import Address, PlutusV3Script, UTxO

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import OracleConfiguration

logger = logging.getLogger(__name__)


class ReferenceScriptFinder:
    """Utility for finding and validating oracle reference scripts"""

    def __init__(self, chain_query: ChainQuery, contracts: OracleContracts) -> None:
        self.chain_query = chain_query
        self.contracts = contracts

    async def find_manager_reference(
        self,
        script_address: Address,
        config: OracleConfiguration,
    ) -> UTxO | None:
        """
        Find existing oracle manager reference script with matching configuration.

        Args:
            script_address: Address to search for reference scripts
            config: Oracle configuration to match

        Returns:
            UTxO containing matching reference script if found, None otherwise
        """
        try:
            # Get UTxOs at script address
            utxos = await self.chain_query.get_utxos(script_address)

            # Filter for reference scripts
            reference_utxos = [utxo for utxo in utxos if utxo.output.script is not None]

            if not reference_utxos:
                return None

            # Get parameterized manager contract for comparison
            target_contract = self.contracts.apply_spend_params(config)
            target_hash = target_contract.script_hash

            # Find matching script
            for utxo in reference_utxos:
                script = utxo.output.script
                if await self._validate_manager_script(script, target_hash):
                    logger.info(
                        "Found matching manager reference script: %s",
                        utxo.output.script,
                    )
                    return utxo

            logger.info("No matching manager reference script found")
            return None

        except Exception as e:  # pylint: disable=broad-except
            logger.error("Error finding manager reference script: %s", e)
            return None

    async def _validate_manager_script(
        self,
        script: PlutusV3Script,
        target_hash: bytes,
    ) -> bool:
        """
        Validate if a script matches the target script hash.

        Args:
            script: Script to validate
            target_hash: Expected script hash

        Returns:
            True if script matches target
        """
        try:
            # We can validate by comparing script hashes
            script_hash = PlutusContract(script).script_hash
            return script_hash == target_hash

        except Exception as e:  # pylint: disable=broad-except
            logger.error("Error validating manager script: %s", e)
            return False
