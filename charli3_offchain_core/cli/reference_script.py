import logging
from pathlib import Path

import click

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.base import (
    create_chain_query,
    derive_deployment_addresses,
    load_keys_with_validation,
)
from charli3_offchain_core.cli.config.deployment import DeploymentConfig
from charli3_offchain_core.cli.config.formatting import oracle_success_callback
from charli3_offchain_core.cli.config.reference_script import ReferenceScriptConfig
from charli3_offchain_core.cli.config.utils import async_command
from charli3_offchain_core.cli.transaction import (
    create_sign_tx_command,
    create_submit_tx_command,
)
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.oracle.config import OracleScriptConfig
from charli3_offchain_core.oracle.deployment.reference_script_finder import (
    ReferenceScriptFinder,
)

logger = logging.getLogger(__name__)


@click.group()
def reference_script() -> None:
    """Oracle reference script deployment and management commands."""


reference_script.add_command(
    create_sign_tx_command(
        status_signed_value=ProcessStatus.TRANSACTION_SIGNED,
    )
)

reference_script.add_command(
    create_submit_tx_command(
        status_success_value=ProcessStatus.TRANSACTION_CONFIRMED,
        success_callback=oracle_success_callback,
    )
)


@reference_script.command()
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
    """Create oracle manager reference script separately."""
    try:
        # Load configuration and contracts
        click.echo("Loading configuration...")
        deployment_config = DeploymentConfig.from_yaml(config)
        contracts = OracleContracts.from_blueprint(deployment_config.blueprint_path)
        ref_script_config = ReferenceScriptConfig.from_yaml(config)

        # Load keys and initialize components
        keys = load_keys_with_validation(deployment_config, contracts)
        addresses = derive_deployment_addresses(deployment_config, contracts)

        # Initialize chain query
        chain_query = create_chain_query(deployment_config.network)

        tx_manager = TransactionManager(chain_query)

        # Create script config
        script_config = OracleScriptConfig(
            create_manager_reference=True, reference_ada_amount=53000000
        )

        # Check for existing script
        ref_script_finder = ReferenceScriptFinder(
            chain_query, contracts, ref_script_config
        )
        if not force:
            click.echo("Checking for existing reference script...")
            existing = await ref_script_finder.find_manager_reference()
            if existing:
                click.echo(
                    f"Found existing reference script at: {existing.output.address}"
                )
                if not click.confirm("Continue with creation?"):
                    return

        # Create and submit transaction
        click.echo("\nCreating reference script...")

        result = await tx_manager.build_reference_script_tx(
            script=contracts.spend.contract,
            reference_script_address=ref_script_finder.reference_script_address,
            admin_address=addresses.admin_address,
            signing_key=keys.payment_sk,
            reference_ada=script_config.reference_ada_amount,
        )

        status, tx = await tx_manager.sign_and_submit(result, [keys.payment_sk])
        if status == "confirmed":
            click.secho("\n✓ Reference script created successfully!", fg="green")
            click.echo(f"Transaction: {tx.id}")
        else:
            raise click.ClickException(f"Transaction failed with status: {status}")

    except Exception as e:
        logger.error("Reference script creation failed", exc_info=e)
        raise click.ClickException(str(e)) from e


if __name__ == "__main__":
    reference_script(_anyio_backend="asyncio")
