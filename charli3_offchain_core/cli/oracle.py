"""CLI commands for oracle deployment and management."""

import logging
from pathlib import Path

import click
from pycardano import (
    BlockFrostChainContext,
    Network,
)
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
from charli3_offchain_core.oracle.deployment.reference_script_builder import (
    ReferenceScriptBuilder,
    ReferenceScriptResult,
)

from .base import (
    create_chain_context,
    derive_deployment_addresses,
    format_status_update,
    load_keys_with_validation,
    validate_deployment_config,
    validate_platform_auth_utxo,
)
from .config.deployment import DeploymentConfig
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
        # Load configuration
        click.echo("Loading configuration...")
        deployment_config = DeploymentConfig.from_yaml(config)
        contracts = OracleContracts.from_blueprint(deployment_config.blueprint_path)

        # Validate configuration
        validate_deployment_config(deployment_config)

        # Load keys with validation
        keys = load_keys_with_validation(deployment_config, contracts)
        addresses = derive_deployment_addresses(deployment_config, contracts)

        # Show derived addresses
        click.echo("\nDeployment Addresses:")
        click.echo(f"Admin Address: {addresses.admin_address}")
        click.echo(f"Script Address: {addresses.script_address}")

        if not click.confirm("Continue with these addresses?"):
            raise click.Abort()

        # Initialize chain context based on backend
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

        # Create orchestrator
        orchestrator = OracleDeploymentOrchestrator(
            chain_query=chain_query,
            contracts=contracts,
            tx_manager=tx_manager,
            status_callback=format_status_update,
        )

        # Create configurations
        script_config = OracleScriptConfig(
            create_manager_reference=deployment_config.create_reference,
            create_nft_reference=deployment_config.create_nft_reference,
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

        # Get and validate platform auth UTxO
        utxos = await chain_query.get_utxos(addresses.admin_address)
        platform_utxo = validate_platform_auth_utxo(
            utxos, deployment_config.tokens.platform_auth_policy
        )

        # Deploy oracle
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

        # Show final results
        if result.status == DeploymentStatus.COMPLETED:
            click.secho("\nDeployment completed successfully!", fg="green", bold=True)

            if result.reference_scripts.manager_tx:
                click.echo("✓ Manager reference script created")
                click.echo(f"  Address: {addresses.script_address}")
                click.echo(f"  TxHash: {result.reference_scripts.manager_tx.id}")

            if result.reference_scripts.nft_tx:
                nft_contract = contracts.apply_mint_params(
                    platform_utxo.output, config, contracts.spend.script_hash
                )
                nft_address = (
                    nft_contract.mainnet_addr
                    if deployment_config.network.network == Network.MAINNET
                    else nft_contract.testnet_addr
                )
                click.echo("✓ NFT reference script created")
                click.echo(f"  Address: {nft_address}")
                click.echo(f"  TxHash: {result.reference_scripts.nft_tx.id}")

            if result.start_result:
                click.echo("\nOracle UTxOs:")
                click.echo("✓ Settings UTxO created")
                click.echo("✓ Reward Account UTxO created")
                click.echo(
                    f"✓ {len(result.start_result.reward_transport_utxos)} Reward Transport UTxOs created"
                )
                click.echo(
                    f"✓ {len(result.start_result.agg_state_utxos)} Aggregation State UTxOs created"
                )
                click.echo(
                    f"\nStart Transaction Hash: {result.start_result.transaction.id}"
                )
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
    help="Force creation even if scripts exist",
)
@click.option(
    "--manager/--no-manager",
    default=True,
    help="Create manager reference script",
)
@click.option(
    "--nft/--no-nft",
    default=False,
    help="Create NFT policy reference script",
)
@async_command
async def create_reference_scripts(
    config: Path,
    force: bool,
    manager: bool,
    nft: bool,
) -> None:
    """Create oracle reference scripts separately.

    This command creates reference scripts without deploying a full oracle.
    Useful for creating shared reference scripts that can be reused.

    Example:
    \b
    charli3 oracle create-reference-scripts \\
        --config deploy-testnet.yaml \\
        --manager \\
        --nft
    """
    try:
        # Load configuration
        click.echo("Loading configuration...")
        deployment_config = DeploymentConfig.from_yaml(config)
        contracts = OracleContracts.from_blueprint(deployment_config.blueprint_path)

        # Load signing key
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

        # Create oracle configuration
        config = OracleConfiguration(
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

        # Initialize script builder with status updates
        script_builder = ReferenceScriptBuilder(
            chain_query=chain_query,
            contracts=contracts,
            tx_manager=tx_manager,
        )

        # Get platform auth UTxO for NFT script if needed
        platform_utxo = None
        if nft:
            utxos = await chain_query.get_utxos(addresses.admin_address)
            if not utxos:
                raise click.ClickException(
                    "No UTxOs found at reference address for NFT script creation"
                )
            platform_utxo = utxos[0]

        # Create script config
        script_config = OracleScriptConfig(
            create_manager_reference=manager,
            create_nft_reference=nft,
            reference_ada_amount=55_000_000,  # 55 ADA for reference scripts
        )

        # Check existing scripts if not forcing
        if not force and manager:
            click.echo("Checking for existing manager reference script...")
            existing_manager = (
                await script_builder.script_finder.find_manager_reference(config)
            )
            if existing_manager:
                manager_contract = contracts.apply_spend_params(config)
                script_address = (
                    manager_contract.mainnet_addr
                    if deployment_config.network.network == Network.MAINNET
                    else manager_contract.testnet_addr
                )
                click.echo(
                    "✓ Found existing manager reference script at: "
                    f"{script_address}\n"
                    f"  UTxO: {existing_manager.input.transaction_id}#{existing_manager.input.index}"
                )
                manager = False

        if not (manager or nft):
            click.echo("No reference scripts to create!")
            return

        # Create reference scripts
        click.echo("\nPreparing reference script transactions...")

        result = await script_builder.prepare_reference_scripts(
            config=config,
            script_config=script_config,
            script_address=addresses.script_address,
            admin_address=addresses.admin_address,
            signing_key=keys.payment_sk,
            platform_utxo=platform_utxo,
        )

        # Submit transactions
        click.echo("\nSubmitting transactions...")

        try:
            if result.manager_tx:
                click.echo("Creating manager reference script...")
                status, _ = await tx_manager.sign_and_submit(
                    result.manager_tx, [keys.payment_sk]
                )
                click.echo(
                    f"✓ Manager reference script created: {result.manager_tx.id}, status: {status}"
                )

            if result.nft_tx:
                click.echo("Creating NFT reference script...")
                status, _ = await tx_manager.sign_and_submit(
                    result.nft_tx, [keys.payment_sk]
                )
                click.echo(
                    f"✓ NFT reference script created: {result.nft_tx.id}, status: {status}"
                )

        except Exception as e:
            raise click.ClickException(f"Failed to submit transactions: {e}") from e

        click.secho("\nReference script creation completed!", fg="green")

    except Exception as e:
        logger.error("Reference script creation failed", exc_info=e)
        raise click.ClickException(str(e)) from e


def show_reference_script_info(
    result: ReferenceScriptResult,
    force: bool,
    manager: bool,
    nft: bool,
) -> None:
    """Display reference script information."""
    click.echo("\nReference Script Details:")
    click.echo("-" * 50)

    if manager:
        if result.manager_utxo:
            click.echo("\nManager Reference Script:")
            click.echo(
                f"✓ UTxO: {result.manager_utxo.input.transaction_id}#{result.manager_utxo.input.index}"
            )
            click.echo(f"✓ Address: {result.manager_utxo.output.address}")
            click.echo(
                f"✓ Ada: {result.manager_utxo.output.amount.coin / 1_000_000:.6f}"
            )
        elif force:
            click.echo("\nManager Reference Script: Not created (force-skipped)")
        else:
            click.echo("\nManager Reference Script: Not needed")

    if nft:
        if result.nft_utxo:
            click.echo("\nNFT Reference Script:")
            click.echo(
                f"✓ UTxO: {result.nft_utxo.input.transaction_id}#{result.nft_utxo.input.index}"
            )
            click.echo(f"✓ Address: {result.nft_utxo.output.address}")
            click.echo(f"✓ Ada: {result.nft_utxo.output.amount.coin / 1_000_000:.6f}")
        elif force:
            click.echo("\nNFT Reference Script: Not created (force-skipped)")
        else:
            click.echo("\nNFT Reference Script: Not needed")


if __name__ == "__main__":
    oracle(_anyio_backend="asyncio")
