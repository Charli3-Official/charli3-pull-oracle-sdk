"""CLI commands for oracle deployment and management."""

import json
import logging
from pathlib import Path

import click

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.governance import add_nodes, update_settings
from charli3_offchain_core.cli.transaction import (
    create_sign_tx_command,
    create_submit_tx_command,
)
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.oracle.config import (
    OracleScriptConfig,
)
from charli3_offchain_core.oracle.lifecycle.orchestrator import LifecycleOrchestrator

from ..constants.status import ProcessStatus
from .base import (
    create_chain_query,
    derive_deployment_addresses,
    load_keys_with_validation,
)
from .config.deployment import DeploymentConfig
from .config.formatting import (
    format_deployment_summary,
    oracle_success_callback,
    print_confirmation_message_prompt,
    print_confirmation_prompt,
    print_hash_info,
    print_header,
    print_progress,
    print_status,
)
from .config.utils import async_command
from .setup import setup_management_from_config, setup_oracle_from_config

logger = logging.getLogger(__name__)


@click.group()
def oracle() -> None:
    """Oracle deployment and management commands."""


oracle.add_command(
    create_sign_tx_command(
        status_signed_value=ProcessStatus.TRANSACTION_SIGNED,
    )
)

oracle.add_command(
    create_submit_tx_command(
        status_success_value=ProcessStatus.TRANSACTION_CONFIRMED,
        success_callback=oracle_success_callback,
    )
)

oracle.add_command(update_settings)
oracle.add_command(add_nodes)


@oracle.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to deployment configuration YAML",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Output file for transaction data",
)
@async_command
async def deploy(config: Path, output: Path | None) -> None:  # noqa
    """Deploy new oracle instance using configuration file."""
    try:
        print_header("Deployment Configuration")
        print_progress("Loading configuration")

        # Setup configuration and components
        setup = setup_oracle_from_config(config)
        (
            deployment_config,
            oracle_config,
            payment_sk,
            _payment_vk,
            addresses,
            _chain_query,
            tx_manager,
            orchestrator,
            platform_auth_finder,
            configs,
        ) = setup

        if not print_confirmation_prompt(
            {
                "Admin Address": addresses.admin_address,
                "Script Address": addresses.script_address,
                "Platform Address": addresses.platform_address,
            }
        ):
            raise click.Abort()

        # Validate platform auth
        print_progress("Validating platform auth UTxO...")
        platform_utxo = await platform_auth_finder.find_auth_utxo(
            policy_id=deployment_config.tokens.platform_auth_policy,
            platform_address=addresses.platform_address,
        )
        if not platform_utxo:
            raise click.ClickException(
                f"No UTxO found with platform auth NFT (policy: {deployment_config.tokens.platform_auth_policy})"
            )

        platform_script = await platform_auth_finder.get_platform_script(
            addresses.platform_address
        )
        platform_multisig_config = platform_auth_finder.get_script_config(
            platform_script
        )
        logger.info(
            f"Using platform UTxO: {platform_utxo.input.transaction_id}#{platform_utxo.input.index}"
        )

        # Handle reference scripts
        reference_result, needs_reference = await orchestrator.handle_reference_scripts(
            script_config=configs["script"],
            script_address=addresses.script_address,
            admin_address=addresses.admin_address,
            signing_key=payment_sk,
        )

        if needs_reference:
            if not print_confirmation_message_prompt(
                "Reference Script was not found! Would you like to proceed with reference script creation now?"
            ):
                raise click.Abort()
            await orchestrator.submit_reference_script_tx(reference_result, payment_sk)
        else:
            print_progress("Reference script already exists, Proceeding...")

        # Build deployment transaction
        result = await orchestrator.build_tx(
            oracle_config,
            platform_script=platform_script,
            admin_address=addresses.admin_address,
            script_address=addresses.script_address,
            aggregation_liveness_period=deployment_config.timing.aggregation_liveness,
            time_absolute_uncertainty=deployment_config.timing.time_uncertainty,
            iqr_fence_multiplier=deployment_config.timing.iqr_multiplier,
            deployment_config=configs["deployment"],
            fee_config=configs["fee"],
            nodes_config=deployment_config.nodes,
            signing_key=payment_sk,
            platform_utxo=platform_utxo,
        )

        if result.status != ProcessStatus.TRANSACTION_BUILT:
            raise click.ClickException(f"Deployment failed: {result.error}")

        # Handle transaction signing based on threshold
        if platform_multisig_config.threshold == 1:
            if print_confirmation_message_prompt(
                "You can deploy the oracle with the configured Platform Auth NFT right away. Would you like to continue?"
            ):
                status, _ = await tx_manager.sign_and_submit(
                    result.start_result.transaction,
                    [payment_sk],
                    wait_confirmation=True,
                )
                if status == ProcessStatus.TRANSACTION_CONFIRMED:
                    format_deployment_summary(result)
                else:
                    raise click.ClickException(f"Deployment failed: {status}")
        elif print_confirmation_message_prompt(
            "PlatformAuth NFT being used requires multisigatures and thus will be stored. Would you like to continue?"
        ):
            output_path = output or Path("tx_oracle_deploy.json")
            with output_path.open("w") as f:
                json.dump(
                    {
                        "transaction": result.start_result.transaction.to_cbor_hex(),
                        "script_address": str(addresses.script_address),
                        "signed_by": [],
                        "threshold": platform_multisig_config.threshold,
                    },
                    f,
                )
            print_status("Transaction", "saved successfully", success=True)
            print_hash_info("Output file", str(output_path))
            print_hash_info(
                "Next steps",
                f"Transaction requires {platform_multisig_config.threshold} signatures",
            )

    except Exception as e:
        logger.error("Deployment failed", exc_info=e)
        raise click.ClickException(str(e)) from e


@oracle.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to deployment configuration YAML",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Output file for transaction data",
)
@async_command
async def pause(config: Path, output: Path | None) -> None:
    """Pause an oracle instance using configuration file."""
    try:
        print_header("Oracle Pause")
        (
            management_config,
            _oracle_config,
            payment_sk,
            oracle_addresses,
            chain_query,
            tx_manager,
            platform_auth_finder,
        ) = setup_management_from_config(config)

        platform_utxo = await platform_auth_finder.find_auth_utxo(
            policy_id=management_config.tokens.platform_auth_policy,
            platform_address=oracle_addresses.platform_address,
        )
        if not platform_utxo:
            raise click.ClickException("No platform auth UTxO found")

        platform_script = await platform_auth_finder.get_platform_script(
            oracle_addresses.platform_address
        )
        platform_config = platform_auth_finder.get_script_config(platform_script)

        orchestrator = LifecycleOrchestrator(
            chain_query=chain_query,
            tx_manager=tx_manager,
            script_address=oracle_addresses.script_address,
            status_callback=format_status_update,
        )
        result = await orchestrator.pause_oracle(
            oracle_policy=management_config.tokens.oracle_policy,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=oracle_addresses.admin_address,
            signing_key=payment_sk,
        )

        if result.status != ProcessStatus.TRANSACTION_BUILT:
            raise click.ClickException(f"Pause failed: {result.error}")

        if platform_config.threshold == 1:
            if print_confirmation_message_prompt("Proceed with oracle pause?"):
                status, _ = await tx_manager.sign_and_submit(
                    result.transaction, [payment_sk], wait_confirmation=True
                )
                if status != ProcessStatus.TRANSACTION_CONFIRMED:
                    raise click.ClickException(f"Pause failed: {status}")
                print_status("Pause", "completed successfully", success=True)
        elif print_confirmation_message_prompt("Store multisig pause transaction?"):
            output_path = output or Path("tx_oracle_pause.json")
            with output_path.open("w") as f:
                json.dump(
                    {
                        "transaction": result.transaction.to_cbor_hex(),
                        "signed_by": [],
                        "threshold": platform_config.threshold,
                    },
                    f,
                )
            print_status("Transaction", "saved successfully", success=True)
            print_hash_info("Output file", str(output_path))

    except Exception as e:
        logger.error("Pause failed", exc_info=e)
        raise click.ClickException(str(e)) from e


@oracle.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to deployment configuration YAML",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Output file for transaction data",
)
@async_command
async def resume(config: Path, output: Path | None) -> None:
    """Resume a paused oracle instance using configuration file."""
    try:
        print_header("Oracle Resume")
        (
            management_config,
            _oracle_config,
            payment_sk,
            oracle_addresses,
            chain_query,
            tx_manager,
            platform_auth_finder,
        ) = setup_management_from_config(config)

        platform_utxo = await platform_auth_finder.find_auth_utxo(
            policy_id=management_config.tokens.platform_auth_policy,
            platform_address=oracle_addresses.platform_address,
        )
        if not platform_utxo:
            raise click.ClickException("No platform auth UTxO found")

        platform_script = await platform_auth_finder.get_platform_script(
            oracle_addresses.platform_address
        )
        platform_config = platform_auth_finder.get_script_config(platform_script)

        orchestrator = LifecycleOrchestrator(
            chain_query=chain_query,
            tx_manager=tx_manager,
            script_address=oracle_addresses.script_address,
            status_callback=format_status_update,
        )

        result = await orchestrator.resume_oracle(
            oracle_policy=management_config.tokens.oracle_policy,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=oracle_addresses.admin_address,
            signing_key=payment_sk,
        )

        if result.status != ProcessStatus.TRANSACTION_BUILT:
            raise click.ClickException(f"Resume failed: {result.error}")

        if platform_config.threshold == 1:
            if print_confirmation_message_prompt("Proceed with oracle resume?"):
                status, _ = await tx_manager.sign_and_submit(
                    result.transaction, [payment_sk], wait_confirmation=True
                )
                if status != ProcessStatus.TRANSACTION_CONFIRMED:
                    raise click.ClickException(f"Resume failed: {status}")
                print_status("Resume", "completed successfully", success=True)
        elif print_confirmation_message_prompt("Store multisig resume transaction?"):
            output_path = output or Path("tx_oracle_resume.json")
            with output_path.open("w") as f:
                json.dump(
                    {
                        "transaction": result.transaction.to_cbor_hex(),
                        "signed_by": [],
                        "threshold": platform_config.threshold,
                    },
                    f,
                )
            print_status("Transaction", "saved successfully", success=True)
            print_hash_info("Output file", str(output_path))

    except Exception as e:
        logger.error("Resume failed", exc_info=e)
        raise click.ClickException(str(e)) from e


@oracle.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to deployment configuration YAML",
)
@click.option(
    "--pair-count",
    type=int,
    help="Number of AggregationState + RewardTransport token pairs to burn (defaults to all available pairs)",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Output file for transaction data",
)
@async_command
async def remove(config: Path, output: Path | None, pair_count: int | None) -> None:
    """Remove an oracle instance permanently using configuration file."""
    try:
        print_header("Oracle Remove")
        (
            management_config,
            _,
            payment_sk,
            oracle_addresses,
            chain_query,
            tx_manager,
            platform_auth_finder,
        ) = setup_management_from_config(config)

        platform_utxo = await platform_auth_finder.find_auth_utxo(
            policy_id=management_config.tokens.platform_auth_policy,
            platform_address=oracle_addresses.platform_address,
        )
        if not platform_utxo:
            raise click.ClickException("No platform auth UTxO found")

        platform_script = await platform_auth_finder.get_platform_script(
            oracle_addresses.platform_address
        )
        platform_config = platform_auth_finder.get_script_config(platform_script)

        orchestrator = LifecycleOrchestrator(
            chain_query=chain_query,
            tx_manager=tx_manager,
            script_address=oracle_addresses.script_address,
            status_callback=format_status_update,
        )
        result = await orchestrator.remove_oracle(
            oracle_policy=management_config.tokens.oracle_policy,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            pair_count=pair_count,
            change_address=oracle_addresses.admin_address,
            signing_key=payment_sk,
        )

        if result.status != ProcessStatus.TRANSACTION_BUILT:
            raise click.ClickException(f"Remove failed: {result.error}")

        if platform_config.threshold == 1:
            if print_confirmation_message_prompt(
                "Proceed with oracle removal? This action cannot be undone."
            ):
                status, _ = await tx_manager.sign_and_submit(
                    result.transaction, [payment_sk], wait_confirmation=True
                )
                if status != ProcessStatus.TRANSACTION_CONFIRMED:
                    raise click.ClickException(f"Remove failed: {status}")
                print_status("Remove", "completed successfully", success=True)
        elif print_confirmation_message_prompt("Store multisig remove transaction?"):
            output_path = output or Path("tx_oracle_remove.json")
            with output_path.open("w") as f:
                json.dump(
                    {
                        "transaction": result.transaction.to_cbor_hex(),
                        "signed_by": [],
                        "threshold": platform_config.threshold,
                    },
                    f,
                )
            print_status("Transaction", "saved successfully", success=True)
            print_hash_info("Output file", str(output_path))

    except Exception as e:
        logger.error("Remove failed", exc_info=e)
        raise click.ClickException(str(e)) from e


@oracle.command()
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

        # Load keys and initialize components
        keys = load_keys_with_validation(deployment_config, contracts)
        addresses = derive_deployment_addresses(deployment_config, contracts)

        # Initialize chain query
        chain_query = create_chain_query(deployment_config.network)

        tx_manager = TransactionManager(chain_query)

        # Create script config
        script_config = OracleScriptConfig(
            create_manager_reference=True,
            reference_ada_amount=68205750,
        )

        # Check for existing script
        if not force:
            click.echo("Checking for existing reference script...")
            existing = await chain_query.get_utxos(addresses.script_address)
            if existing:
                click.echo(
                    f"Found existing reference script at: {addresses.script_address}"
                )
                if not click.confirm("Continue with creation?"):
                    return

        # Create and submit transaction
        click.echo("\nCreating reference script...")

        result = await tx_manager.build_reference_script_tx(
            script=contracts.spend.contract,
            script_address=addresses.script_address,
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
    oracle(_anyio_backend="asyncio")
