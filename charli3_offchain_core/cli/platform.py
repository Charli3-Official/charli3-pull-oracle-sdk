import json
import logging
from pathlib import Path

import click

from charli3_offchain_core.cli.config.formatting import (
    format_status_update,
    print_address_info,
    print_hash_info,
    print_header,
    print_progress,
    print_status,
)

from ..blockchain.chain_query import ChainQuery
from ..blockchain.transactions import TransactionManager
from ..platform.auth.orchestrator import (
    AuthStatus,
    PlatformAuthOrchestrator,
)
from .base import create_chain_context
from .config.keys import KeyManager
from .config.platform import PlatformAuthConfig
from .config.utils import async_command

logger = logging.getLogger(__name__)


@click.group()
def platform() -> None:
    """Platform authorization commands."""
    pass


@platform.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to platform configuration YAML",
)
@click.option(
    "--metadata",
    type=click.Path(exists=True, path_type=Path),
    help="Optional metadata JSON file",
)
@async_command
async def mint_auth(
    config: Path,
    metadata: Path | None,
) -> None:
    """Mint platform authorization token."""
    try:
        # Load and display configuration
        print_header("Platform Auth Configuration")
        print_progress("Loading configuration")
        auth_config = PlatformAuthConfig.from_yaml(config)

        payment_sk, payment_vk, stake_vk, default_addr = KeyManager.load_from_config(
            auth_config.network.wallet
        )

        # Load metadata if provided
        meta_data = None
        if metadata:
            print_progress("Loading metadata file")
            with metadata.open() as f:
                meta_data = json.load(f)

        chain_context = create_chain_context(auth_config)
        chain_query = ChainQuery(chain_context)
        tx_manager = TransactionManager(chain_query)

        def status_callback(status: AuthStatus, message: str) -> None:
            format_status_update(status.name, message)

        orchestrator = PlatformAuthOrchestrator(
            chain_query=chain_query,
            tx_manager=tx_manager,
            status_callback=status_callback,
        )

        # Display configuration details
        print_header("Platform Authorization Details:")
        print_hash_info("Network", auth_config.network.network)
        print_hash_info("Multisig Threshold", str(auth_config.multisig.threshold))
        for i, party in enumerate(auth_config.multisig.parties, start=1):
            print_address_info(f"PKH {i}", party)

        if not click.confirm("\nProceed with token minting?"):
            click.echo("Minting process aborted by the user.")
            return

        print_progress("Minting platform authorization token")
        result = await orchestrator.create_platform_auth(
            sender_address=default_addr,
            signing_key=payment_sk,
            multisig_threshold=auth_config.multisig.threshold,
            multisig_parties=auth_config.multisig.parties,
            metadata=meta_data,
            network=auth_config.network.network,
            is_mock=False,
        )

        if result.status == AuthStatus.COMPLETED:
            print_status(
                "Platform authorization token", "Minted successfully", success=True
            )
            print_hash_info("Transaction ID", result.transaction.id)
            print_hash_info("Platform Address", result.platform_address)
            print_hash_info("Policy ID", result.policy_id)
            click.echo(
                "\nPlease update your deployment configuration with this policy ID"
            )

        else:
            raise click.ClickException(f"Token minting failed: {result.error}")

    except click.Abort:
        click.echo("Minting process aborted by the user.")
    except Exception as e:
        logger.error("Failed to mint token", exc_info=e)
        raise click.ClickException(str(e)) from e
