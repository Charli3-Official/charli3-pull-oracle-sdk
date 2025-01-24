"""CLI commands for oracle ODV client simulation."""

from pathlib import Path

import click

from charli3_offchain_core.cli.aggregate_txs.base import TransactionContext, tx_options
from charli3_offchain_core.cli.config.formatting import print_header, print_progress
from charli3_offchain_core.cli.config.odv_client import OdvClientConfig
from charli3_offchain_core.cli.config.utils import async_command
from charli3_offchain_core.cli.odv_client.api import OdvApiClient, OdvMessageRequest


@click.group()
def client() -> None:
    """Oracle ODV client commands."""


@client.command()
@tx_options
@async_command
async def send(
    config: Path,
) -> None:
    """Send oracle client requests for ODV flow."""
    try:
        print_header("Send oracle client requests for ODV flow")

        # Load configuration and contracts
        print_progress("Loading configuration")
        odv_config = OdvClientConfig.from_yaml(config)
        ctx = TransactionContext(odv_config.tx_config)

        # Run simulation
        async with OdvApiClient() as odv_client:
            print_progress("Sending odv requests")
            validity_window = ctx.tx_manager.calculate_validity_window(
                odv_config.odv_validity_length
            )
            message_req = OdvMessageRequest(
                oracle_nft_policy_id_hex=odv_config.tx_config.policy_id,
                odv_validity_start=str(validity_window.validity_start),
                odv_validity_end=str(validity_window.validity_end),
            )
            _node_messages = await odv_client.odv_message_requests(
                message_req, odv_config.nodes
            )

    except Exception as e:
        raise click.ClickException(f"Odv Client simulation failed: {e}") from e
