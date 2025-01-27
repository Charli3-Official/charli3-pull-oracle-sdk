"""CLI commands for oracle ODV client simulation."""

from pathlib import Path

import click

from charli3_offchain_core.cli.aggregate_txs.base import TransactionContext, tx_options
from charli3_offchain_core.cli.aggregate_txs.odv_aggregate import _print_odv_summary
from charli3_offchain_core.cli.config.formatting import (
    print_header,
    print_progress,
    print_status,
)
from charli3_offchain_core.cli.config.odv_client import OdvClientConfig
from charli3_offchain_core.cli.config.utils import async_command
from charli3_offchain_core.cli.odv_client.api import OdvApiClient, OdvMessageRequest
from charli3_offchain_core.oracle.aggregate.builder import OracleTransactionBuilder
from charli3_offchain_core.oracle.exceptions import TransactionError
from charli3_offchain_core.oracle.utils.common import make_aggregate_message


@click.group()
def client() -> None:
    """Oracle ODV client commands."""


@client.command()
@tx_options
@click.option(
    "--wait/--no-wait",
    default=True,
    help="Wait for transaction confirmation",
)
@async_command
async def send(config: Path, wait: bool) -> None:
    """Send oracle client requests for ODV flow."""
    try:
        print_header("Send oracle client requests for ODV flow")

        # Load configuration and contracts
        print_progress("Loading configuration")
        odv_config = OdvClientConfig.from_yaml(config)
        ctx = TransactionContext(odv_config.tx_config)

        # Load primary signing key
        signing_key, change_address = ctx.load_keys()

        # Initialize transaction builder
        builder = OracleTransactionBuilder(
            tx_manager=ctx.tx_manager,
            script_address=ctx.script_address,
            policy_id=ctx.policy_id,
            fee_token_hash=ctx.fee_token_policy_id,
            fee_token_name=ctx.fee_token_name,
        )

        # Run simulation
        async with OdvApiClient() as odv_client:
            # First round of communication with oracle nodes
            print_progress("Sending odv message requests")
            validity_window = ctx.tx_manager.calculate_validity_window(
                odv_config.odv_validity_length
            )
            message_req = OdvMessageRequest(
                oracle_nft_policy_id_hex=odv_config.tx_config.policy_id,
                odv_validity_start=str(validity_window.validity_start),
                odv_validity_end=str(validity_window.validity_end),
            )
            node_messages = await odv_client.odv_message_requests(
                message_req, odv_config.nodes
            )
            aggregate_msg = make_aggregate_message(
                feed_data={
                    node.pub_key.hash(): msg.feed
                    for node, msg in zip(odv_config.nodes, node_messages)
                },
                timestamp=validity_window.current_time,
            )
            # Build ODV transaction
            print_progress("Building ODV Aggregate transaction")
            result = await builder.build_odv_tx(
                message=aggregate_msg,
                signing_key=signing_key,
                change_address=change_address,
                validity_window=validity_window,
            )
            # Second round of communication with oracle nodes
            print_progress("Sending odv tx requests")
            node_witnesses = await odv_client.odv_tx_requests(
                node_messages, result.transaction, odv_config.nodes
            )
            result.transaction.transaction_witness_set.vkey_witnesses.extend(
                node_witnesses
            )

        print_progress("Submitting odv tx")
        tx_status, _ = await ctx.tx_manager.sign_and_submit(
            result.transaction, [signing_key], wait_confirmation=wait
        )

        # Get transaction ID from the original transaction
        tx_id = result.transaction.id

        if tx_status == "confirmed":
            print_status(
                "ODV aggregation completed successfully",
                f"tx id {tx_id}",
                success=True,
            )
        else:
            raise click.ClickException(f"Transaction failed with status: {tx_status}")

        # Display additional details
        if tx_status == "confirmed":
            _print_odv_summary(result)

    except TransactionError as e:
        raise click.ClickException(f"Transaction failed: {e}") from e

    except Exception as e:
        raise click.ClickException(f"Odv Client simulation failed: {e}") from e
