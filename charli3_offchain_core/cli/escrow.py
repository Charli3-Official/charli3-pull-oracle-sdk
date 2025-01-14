"""CLI commands for escrow deployment and management."""

import logging
from pathlib import Path

import click
from pycardano import Address, plutus_script_hash

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.base import create_chain_query
from charli3_offchain_core.cli.config.escrow import EscrowConfig
from charli3_offchain_core.cli.config.formatting import (
    print_confirmation_message_prompt,
    print_header,
    print_information,
    print_progress,
    print_status,
)
from charli3_offchain_core.cli.config.keys import KeyManager
from charli3_offchain_core.cli.config.utils import async_command
from charli3_offchain_core.contracts.aiken_loader import RewardEscrowContract

logger = logging.getLogger(__name__)


@click.group()
def escrow() -> None:
    """Escrow deployment and management commands."""


@escrow.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to deployment configuration YAML",
)
@click.option(
    "--force/--no-force",
    default=False,
    help="Force creation even if script exists",
)
@async_command
async def create_reference_script(config: Path, force: bool) -> None:
    """Create escrow manager reference script."""
    try:
        print_header("Create Escrow Manager reference script")

        # Load configuration and contracts
        print_progress("Loading configuration")
        escrow_config = EscrowConfig.from_yaml(config)
        escrow_script = RewardEscrowContract.from_blueprint(
            escrow_config.blueprint_path
        )

        # Load keys and initialize components
        (payment_sk, _, _, wallet_addr) = KeyManager.load_from_config(
            escrow_config.network.wallet
        )
        script_address = escrow_config.reference_script_addr
        if script_address is None:
            script_address = Address(
                payment_part=escrow_script.escrow_manager.script_hash,
                network=escrow_config.network.network,
            )

        # Initialize chain query
        chain_query = create_chain_query(escrow_config.network)

        tx_manager = TransactionManager(chain_query)

        # Check for existing script
        if not force:
            print_progress("Checking for existing reference script")
            utxos = await chain_query.get_utxos(script_address)
            reference_utxos = [
                utxo
                for utxo in utxos
                if utxo.output.script
                and plutus_script_hash(utxo.output.script)
                == escrow_script.escrow_manager.script_hash
            ]
            if reference_utxos:
                for ref_utxo in reference_utxos:
                    print_information(
                        f"Found existing reference script utxo - {ref_utxo.input.transaction_id.payload.hex()}:{ref_utxo.input.index}"
                    )
                if not print_confirmation_message_prompt("Continue with creation?"):
                    return

        # Create and submit transaction
        print_progress("Creating reference script")

        result = await tx_manager.build_reference_script_tx(
            script=escrow_script.escrow_manager.contract,
            script_address=script_address,
            admin_address=wallet_addr,
            signing_key=payment_sk,
            reference_ada=6107270,
        )

        status, _tx = await tx_manager.sign_and_submit(result, [payment_sk])
        if status == "confirmed":
            print_status(
                "Reference script created successfully",
                f"tx id {result.id}",
                success=True,
            )
        else:
            raise click.ClickException(f"Transaction failed with status: {status}")

    except Exception as e:
        logger.error("Reference script creation failed", exc_info=e)
        raise click.ClickException(str(e)) from e


if __name__ == "__main__":
    escrow(_anyio_backend="asyncio")
