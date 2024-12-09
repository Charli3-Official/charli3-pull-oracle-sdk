from opshin.builder import PlutusContract
from pycardano import UTxO

from charli3_offchain_core.blockchain.transactions import TransactionManager

from ..exceptions import TransactionError, ValidationError


async def get_script_utxos(script_address:str,tx_manager:TransactionManager) -> list[UTxO]:
        """Get and validate UTxOs at script address."""
        try:
            utxos = await tx_manager.chain_query.get_utxos(script_address)
            if not utxos:
                raise ValidationError("No UTxOs found at script address")
            return utxos
        except Exception as e:
            raise TransactionError(f"Failed to get script UTxOs: {e}") from e

def get_reference_script_utxo(utxos: list[UTxO]) -> UTxO:
    """Find and validate reference script UTxO."""

    for utxo in utxos:
        if utxo.output.script:
            return utxo

    raise ValidationError("No reference script UTxO found")
