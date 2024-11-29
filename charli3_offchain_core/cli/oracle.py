"""CLI commands for oracle deployment and management."""

import json
import logging
from pathlib import Path

import click
from pycardano import BlockFrostChainContext, NativeScript, Transaction, UTxO
from pycardano.backend.kupo import KupoChainContextExtension

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.oracle.config import (
    OracleScriptConfig,
)
from charli3_offchain_core.oracle.deployment.orchestrator import (
    DeploymentResult,
    DeploymentStatus,
)

from .base import (
    create_chain_context,
    derive_deployment_addresses,
    load_keys_with_validation,
    validate_deployment_config,
)
from .config.deployment import DeploymentConfig
from .config.formatting import (
    format_deployment_summary,
    print_confirmation_message_prompt,
    print_confirmation_prompt,
    print_hash_info,
    print_header,
    print_progress,
    print_status,
)
from .config.keys import KeyManager
from .config.utils import async_command
from .setup import setup_oracle_from_config

logger = logging.getLogger(__name__)


@click.group()
def oracle() -> None:
    """Oracle deployment and management commands."""
    pass


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
async def deploy(config: Path, output: Path | None) -> None:  # noqa: C901
    """Deploy new oracle instance using configuration file.

    This command will:
    1. Load configuration from YAML file
    2. Create reference scripts if needed
    3. Create oracle UTxOs with proper datums
    4. Mint oracle NFTs
    """

    async def validate_platform_auth() -> tuple[UTxO, NativeScript, dict]:
        logger.info("Validating platform auth UTxO...")
        platform_utxo = await platform_auth_finder.find_auth_utxo(
            policy_id=deployment_config.tokens.platform_auth_policy,
            platform_address=addresses.platform_address,
        )

        if not platform_utxo:
            logger.error(
                "No UTxO found with platform auth NFT (policy: %s)",
                deployment_config.tokens.platform_auth_policy,
            )
            raise click.ClickException("Platform auth validation failed")

        platform_script = await platform_auth_finder.get_platform_script(
            addresses.platform_address
        )
        platform_multisig_config = platform_auth_finder.get_script_config(
            platform_script
        )
        logger.info(
            "Using platform UTxO: %s#%s",
            platform_utxo.input.transaction_id,
            platform_utxo.input.index,
        )
        return platform_utxo, platform_script, platform_multisig_config

    async def handle_deployment() -> None:
        reference_script_result, is_reference_script_required = (
            await orchestrator.handle_reference_scripts(
                script_config=configs["script"],
                script_address=addresses.script_address,
                admin_address=addresses.admin_address,
                signing_key=keys.payment_sk,
            )
        )

        if is_reference_script_required and not print_confirmation_message_prompt(
            "Reference Script was not found! Would you like to proceed with reference script creation now?"
        ):
            raise click.Abort()

        if is_reference_script_required:
            await orchestrator.submit_reference_script_tx(
                result=reference_script_result,
                signing_key=keys.payment_sk,
            )
        else:
            print_progress("Reference script already exists, Proceeding...")

    async def handle_transaction_signing(
        result: DeploymentResult, threshold: int
    ) -> None:
        if threshold == 1:
            if not print_confirmation_message_prompt(
                "You can deploy the oracle with the platform auth right away. Would you like to continue?"
            ):
                raise click.Abort()

            status, _ = await tx_manager.sign_and_submit(
                result.start_result.transaction,
                [keys.payment_sk],
                wait_confirmation=True,
            )
            if status == DeploymentStatus.CONFIRMED:
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
                        "threshold": threshold,
                    },
                    f,
                )
            print_status("Transaction", "saved successfully", success=True)
            print_hash_info("Output file", str(output_path))
            print_hash_info(
                "Next steps", f"Transaction requires {threshold} signatures"
            )

    try:
        # Setup and validation
        print_header("Deployment Configuration")
        print_progress("Loading configuration")
        setup = setup_oracle_from_config(config)
        (
            deployment_config,
            _,
            _,
            addresses,
            keys,
            chain_query,
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

        # Platform auth and deployment
        platform_utxo, platform_script, platform_multisig_config = (
            await validate_platform_auth()
        )
        await handle_deployment()

        # Build and handle transaction
        result = await orchestrator.build_tx(
            platform_auth_policy_id=bytes.fromhex(
                deployment_config.tokens.platform_auth_policy
            ),
            fee_token=configs["fee_token"],
            platform_script=platform_script,
            admin_address=addresses.admin_address,
            script_address=addresses.script_address,
            closing_period_length=deployment_config.timing.closing_period,
            reward_dismissing_period_length=deployment_config.timing.reward_dismissing_period,
            aggregation_liveness_period=deployment_config.timing.aggregation_liveness,
            time_absolute_uncertainty=deployment_config.timing.time_uncertainty,
            iqr_fence_multiplier=deployment_config.timing.iqr_multiplier,
            deployment_config=configs["deployment"],
            fee_config=configs["fee"],
            signing_key=keys.payment_sk,
            platform_utxo=platform_utxo,
        )
        if result.status != DeploymentStatus.TRANSACTION_BUILT:
            raise click.ClickException(f"Deployment failed: {result.error}")

        await handle_transaction_signing(result, platform_multisig_config.threshold)

    except Exception as e:
        logger.error("Deployment failed", exc_info=e)
        raise click.ClickException(str(e)) from e


@oracle.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to platform configuration YAML",
)
@click.option(
    "--tx-file",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to signed transaction JSON file",
)
@async_command
async def submit_tx(
    config: Path,
    tx_file: Path,
) -> None:
    """Submit a fully signed oracle deployment transaction."""
    with tx_file.open() as f:
        data = json.load(f)

    if len(data.get("signed_by", [])) < data.get("threshold", 1):
        raise click.ClickException(
            "Transaction does not have enough signatures to meet threshold"
        )

    deployment_config = DeploymentConfig.from_yaml(config)
    validate_deployment_config(deployment_config)

    chain_context = create_chain_context(deployment_config)
    chain_query = ChainQuery(
        blockfrost_context=(
            chain_context if isinstance(chain_context, BlockFrostChainContext) else None
        ),
        kupo_ogmios_context=(
            chain_context
            if isinstance(chain_context, KupoChainContextExtension)
            else None
        ),
    )
    tx_manager = TransactionManager(chain_query)

    tx = Transaction.from_cbor(data["transaction"])

    # Match platform's handle_tx pattern - use sign_and_submit with empty signing keys
    status, submitted_tx = await tx_manager.sign_and_submit(
        tx, [], wait_confirmation=True
    )

    if status == "confirmed":
        print_status(
            "Oracle deployment", "Transaction submitted successfully", success=True
        )
        if "script_address" in data:
            print_hash_info("Script Address", data["script_address"])
    else:
        raise click.ClickException(
            f"Transaction submission failed with status: {status}"
        )


@oracle.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to platform configuration YAML",
)
@click.option(
    "--tx-file",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to signed transaction JSON file",
)
@async_command
async def sign_tx(
    config: Path,
    tx_file: Path,
) -> None:
    """Sign an oracle deployment transaction."""
    with tx_file.open() as f:
        data = json.load(f)

    # Load config and validate
    deployment_config = DeploymentConfig.from_yaml(config)
    validate_deployment_config(deployment_config)

    # Load keys
    payment_sk, payment_vk, _, _ = KeyManager.load_from_config(
        deployment_config.network.wallet
    )

    # Initialize chain components
    chain_context = create_chain_context(deployment_config)
    chain_query = ChainQuery(
        blockfrost_context=(
            chain_context if isinstance(chain_context, BlockFrostChainContext) else None
        ),
        kupo_ogmios_context=(
            chain_context
            if isinstance(chain_context, KupoChainContextExtension)
            else None
        ),
    )
    tx_manager = TransactionManager(chain_query)

    # Sign transaction
    print_progress("Signing transaction")
    tx = Transaction.from_cbor(data["transaction"])

    # Check if signature already exists
    signer_id = payment_vk.payload.hex()
    if signer_id in data["signed_by"]:
        print_status(
            "Already Signed", "Transaction already signed by this key", success=True
        )
        raise click.Abort()

    tx_manager.sign_tx(tx, payment_sk)

    # Save updated transaction
    data["transaction"] = tx.to_cbor_hex()
    data["signed_by"].append(signer_id)

    with tx_file.open("w") as f:
        json.dump(data, f)

    print_status("Transaction", "Signed successfully", success=True)
    print_hash_info(
        "Signatures",
        f"{len(data['signed_by'])}/{data['threshold']} required signatures",
    )


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

        # Initialize chain context
        chain_context = create_chain_context(deployment_config)

        # Initialize core components
        chain_query = ChainQuery(
            blockfrost_context=(
                chain_context
                if isinstance(chain_context, BlockFrostChainContext)
                else None
            ),
            kupo_ogmios_context=(
                chain_context
                if isinstance(chain_context, KupoChainContextExtension)
                else None
            ),
        )

        tx_manager = TransactionManager(chain_query)

        # Create script config
        script_config = OracleScriptConfig(
            create_manager_reference=True,
            reference_ada_amount=64_000_000,
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
