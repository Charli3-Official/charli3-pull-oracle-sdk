"""CLI commands for oracle deployment and management."""

import logging
from pathlib import Path

import click
from pycardano import BlockFrostChainContext
from pycardano.backend.kupo import KupoChainContextExtension

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import (
    Asset,
    FeeConfig,
    NoDatum,
    OracleConfiguration,
    RewardPrices,
)
from charli3_offchain_core.oracle.config import (
    OracleDeploymentConfig,
    OracleScriptConfig,
)
from charli3_offchain_core.oracle.deployment.orchestrator import (
    DeploymentResult,
    DeploymentStatus,
    OracleDeploymentOrchestrator,
)

from .base import (
    create_chain_context,
    derive_deployment_addresses,
    load_keys_with_validation,
    validate_deployment_config,
    validate_platform_auth_utxo,
)
from .config.deployment import DeploymentConfig
from .config.formatting import (
    format_deployment_summary,
    format_status_update,
    print_confirmation_prompt,
    print_header,
    print_progress,
)
from .config.utils import async_command

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
@async_command
async def deploy(config: Path) -> None:
    """Deploy new oracle instance using configuration file.

    This command will:
    1. Load configuration from YAML file
    2. Create reference scripts if needed
    3. Create oracle UTxOs with proper datums
    4. Mint oracle NFTs

    Example:
    \b
    charli3 oracle deploy --config deploy-testnet.yaml
    """
    try:
        # Load and validate configuration
        print_header("Deployment Configuration")
        print_progress("Loading configuration")
        deployment_config = DeploymentConfig.from_yaml(config)
        validate_deployment_config(deployment_config)

        # Load base contracts
        print_progress("Loading base contracts from blueprint")
        base_contracts = OracleContracts.from_blueprint(
            deployment_config.blueprint_path
        )
        logger.debug("Base contract hash: %s", base_contracts.spend.script_hash)

        # Create oracle configuration
        print_progress("Creating oracle configuration")
        oracle_config = OracleConfiguration(
            platform_auth_nft=bytes.fromhex(
                deployment_config.tokens.platform_auth_policy
            ),
            closing_period_length=deployment_config.timing.closing_period,
            reward_dismissing_period_length=deployment_config.timing.reward_dismissing_period,
            fee_token=Asset(
                policy_id=bytes.fromhex(deployment_config.tokens.fee_token_policy),
                name=bytes.fromhex(deployment_config.tokens.fee_token_name),
            ),
        )

        # Parameterize contracts
        logger.info("Parameterizing contracts...")
        parameterized_contracts = OracleContracts(
            spend=base_contracts.apply_spend_params(oracle_config),
            mint=base_contracts.mint,  # Mint policy is parameterized later with UTxO
        )
        logger.info(
            "Parameterized contract hash: %s", parameterized_contracts.spend.script_hash
        )

        # Load keys and derive addresses using parameterized contracts
        keys = load_keys_with_validation(deployment_config, parameterized_contracts)
        addresses = derive_deployment_addresses(
            deployment_config, parameterized_contracts
        )

        # Display addresses and get confirmation
        if not print_confirmation_prompt(
            {
                "Admin Address": addresses.admin_address,
                "Script Address": addresses.script_address,
            }
        ):
            raise click.Abort()

        # Initialize deployment
        print_progress("Initializing deployment components")
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

        # Create configurations
        script_config = OracleScriptConfig(
            create_manager_reference=deployment_config.create_reference,
            reference_ada_amount=55_000_000,
        )

        oracle_deployment_config = OracleDeploymentConfig(
            network=deployment_config.network.network,
            reward_transport_count=deployment_config.transport_count,
        )

        fee_token = Asset(
            policy_id=bytes.fromhex(deployment_config.tokens.fee_token_policy),
            name=bytes.fromhex(deployment_config.tokens.fee_token_name),
        )

        fee_config = FeeConfig(
            rate_nft=NoDatum(),
            reward_prices=RewardPrices(
                node_fee=deployment_config.fees.node_fee,
                platform_fee=deployment_config.fees.platform_fee,
            ),
        )

        # Validate platform auth UTxO
        logger.info("Validating platform auth UTxO...")
        utxos = await chain_query.get_utxos(addresses.admin_address)
        platform_utxo = validate_platform_auth_utxo(
            utxos, deployment_config.tokens.platform_auth_policy
        )
        logger.info(
            "Using platform UTxO: %s#%s",
            platform_utxo.input.transaction_id,
            platform_utxo.input.index,
        )

        # Deploy oracle using parameterized contracts
        logger.info("Initializing deployment orchestrator...")
        orchestrator = OracleDeploymentOrchestrator(
            chain_query=chain_query,
            contracts=parameterized_contracts,  # Using parameterized contracts
            tx_manager=tx_manager,
            status_callback=format_status_update,
        )

        print_progress("Starting oracle deployment")
        result: DeploymentResult = await orchestrator.deploy_oracle(
            platform_auth_policy_id=bytes.fromhex(
                deployment_config.tokens.platform_auth_policy
            ),
            fee_token=fee_token,
            script_config=script_config,
            admin_address=addresses.admin_address,
            script_address=addresses.script_address,
            closing_period_length=deployment_config.timing.closing_period,
            reward_dismissing_period_length=deployment_config.timing.reward_dismissing_period,
            aggregation_liveness_period=deployment_config.timing.aggregation_liveness,
            time_absolute_uncertainty=deployment_config.timing.time_uncertainty,
            iqr_fence_multiplier=deployment_config.timing.iqr_multiplier,
            deployment_config=oracle_deployment_config,
            fee_config=fee_config,
            signing_key=keys.payment_sk,
            platform_utxo=platform_utxo,
        )

        # Display results
        if result.status == DeploymentStatus.COMPLETED:
            format_deployment_summary(result)
        else:
            raise click.ClickException(f"Deployment failed: {result.error}")

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
            reference_ada_amount=55_000_000,
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
