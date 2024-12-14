""" Common utility functions for oracle operations. """

from pycardano import ScriptHash, UTxO

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.oracle.utils.asset_checks import validate_token_quantities
from charli3_offchain_core.oracle.utils.state_checks import (
    filter_empty_agg_states,
    filter_empty_transports,
    filter_oracle_settings_utxo,
    filter_reward_accounts,
)

from ..exceptions import StateValidationError, TransactionError, ValidationError


async def get_script_utxos(
    script_address: str, tx_manager: TransactionManager
) -> list[UTxO]:
    """Get and validate UTxOs at script address."""
    try:
        utxos = await tx_manager.chain_query.get_utxos(script_address)
        if not utxos:
            raise ValidationError("No UTxOs found at script address")
        return utxos
    except Exception as e:
        raise TransactionError(f"Failed to get script UTxOs: {e}") from e


def get_reference_script_utxo(utxos: list[UTxO]) -> UTxO:
    """Find reference script UTxO.

    Args:
        utxos: List of UTxOs to search

    Returns:
        UTxO: Reference script UTxO

    Raises:
        StateValidationError: If no reference script UTxO is found
    """
    for utxo in utxos:
        if utxo.output.script:
            return utxo

    raise ValidationError("No reference script UTxO found")


def get_oracle_utxos(
    utxos: list[UTxO], oracle_policy: str
) -> tuple[UTxO, UTxO | None, list[UTxO], list[UTxO]]:
    """Return oracle UTxOs from the utxos list by filtering them based on policy hash."""

    policy_hash = ScriptHash(bytes.fromhex(oracle_policy))

    settings_utxo = filter_oracle_settings_utxo(utxos, policy_hash)
    if not settings_utxo:
        raise StateValidationError(f"Oracle {oracle_policy} not found")

    if not validate_token_quantities(settings_utxo, {"CoreSettings": 1}):
        raise StateValidationError("Invalid settings token quantities")

    reward_accounts = filter_reward_accounts(utxos)
    reward_transports = filter_empty_transports(utxos)
    agg_states = filter_empty_agg_states(utxos)

    return (
        settings_utxo,
        next(iter(reward_accounts), None),
        reward_transports or [],
        agg_states or [],
    )
