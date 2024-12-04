"""CLI commands for Oracle Data Verification (ODV) operations."""

import json
import logging
from pathlib import Path

import click
from pycardano import UTxO

from charli3_offchain_core.models.oracle_datums import AggregateMessage
from charli3_offchain_core.oracle.exceptions import TransactionError
from charli3_offchain_core.oracle.transactions.builder import (
    OdvResult,
    OracleTransactionBuilder,
)

from ..config.formatting import print_confirmation_prompt, print_header, print_progress
from ..config.utils import async_command
from .base import TransactionContext, TxConfig, tx_options

logger = logging.getLogger(__name__)


@click.group()
def odv() -> None:
    """ODV (On-Demand Validation) transaction commands."""
    pass


@odv.command()
@tx_options
@click.option(
    "--feeds-file",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="JSON file containing node feeds and signatures",
)
@click.option(
    "--wait/--no-wait",
    default=True,
    help="Wait for transaction confirmation",
)
@async_command
async def submit(config: Path, feeds_file: Path, wait: bool) -> None:
    """Submit ODV transaction with aggregated feeds.

    Example:
        charli3 tx odv submit --config tx-config.yaml --feeds-file feeds.json
    """
    try:
        # Load configuration and initialize context
        print_header("ODV Transaction Submission")
        print_progress("Loading configuration...")
        tx_config = TxConfig.from_yaml(config)
        ctx = TransactionContext(tx_config)

        # Load feed data
        print_progress("Loading feeds data...")
        with feeds_file.open() as f:
            feed_data = json.load(f)
            message = AggregateMessage.from_dict(feed_data)

        # Load keys
        print_progress("Loading keys...")
        signing_key, change_address = ctx.load_keys()

        # Initialize transaction builder
        builder = OracleTransactionBuilder(
            tx_manager=ctx.tx_manager,
            script_address=ctx.script_address,
            policy_id=ctx.policy_id,
        )

        # Build ODV transaction
        print_progress("Building ODV transaction...")
        result = await builder.build_odv_tx(
            message=message,
            signing_key=signing_key,
            change_address=change_address,
        )

        # Display transaction details
        if not print_confirmation_prompt(
            {
                "Node Count": len(message.node_feeds_sorted_by_feed),
                "Required Fees": result.fees,
                "Transaction Size": len(result.transaction.to_cbor()),
            }
        ):
            raise click.Abort()

        # Submit transaction
        print_progress("Submitting transaction...")
        tx_status, tx = await ctx.tx_manager.sign_and_submit(
            result.transaction, [signing_key], wait_confirmation=wait
        )

        click.secho(f"\n✓ Transaction {tx_status}!", fg="green")
        click.echo(f"Transaction ID: {tx.id}")

        # Display additional details
        if tx_status == "confirmed":
            _print_odv_summary(result)

    except TransactionError as e:
        logger.error("Transaction failed", exc_info=e)
        raise click.ClickException(f"Transaction failed: {e!s}") from e
    except Exception as e:
        logger.error("ODV submission failed", exc_info=e)
        raise click.ClickException(str(e)) from e


@odv.command()
@tx_options
@async_command
async def status(config: Path) -> None:
    """Show current ODV transaction status.

    Example:
        charli3 tx odv status --config tx-config.yaml
    """
    try:
        print_header("ODV Status Check")
        print_progress("Loading configuration...")
        tx_config = TxConfig.from_yaml(config)
        ctx = TransactionContext(tx_config)

        # Get UTxO counts
        print_progress("Checking UTxO status...")
        script_utxos = await ctx.chain_query.get_utxos(ctx.script_address)

        empty_pairs = sum(1 for utxo in script_utxos if _is_empty_transport_pair(utxo))
        pending_pairs = sum(1 for utxo in script_utxos if _is_pending_transport(utxo))

        # Display status
        click.echo("\nODV Status:")
        click.echo("-" * 40)
        click.echo(f"Available Empty Pairs: {empty_pairs}")
        click.echo(f"Pending Validation: {pending_pairs}")

        if pending_pairs > 0:
            click.echo("\nPending Transactions:")
            for utxo in script_utxos:
                if _is_pending_transport(utxo):
                    _print_pending_transport(utxo)

    except Exception as e:
        logger.error("Status check failed", exc_info=e)
        raise click.ClickException(str(e)) from e


def _print_odv_summary(result: OdvResult) -> None:
    """Print summary of ODV transaction result."""
    click.echo("\nTransaction Summary:")
    click.echo("-" * 40)
    click.echo(
        f"Transport UTxO: {result.transport_output.input.transaction_id}#{result.transport_output.input.index}"
    )
    click.echo(
        f"AggState UTxO: {result.agg_state_output.input.transaction_id}#{result.agg_state_output.input.index}"
    )
    click.echo(f"Total Fees Paid: {result.fees}")


def _print_pending_transport(utxo: UTxO) -> None:
    """Print details of pending transport UTxO."""
    datum = utxo.output.datum.variant.datum
    click.echo(f"\nUTxO: {utxo.input.transaction_id}#{utxo.input.index}")
    click.echo(f"Message Timestamp: {datum.message.timestamp}")
    click.echo(f"Node Count: {len(datum.message.node_feeds_sorted_by_feed)}")


def _is_empty_transport_pair(utxo: UTxO) -> bool:
    """Check if UTxO is part of empty transport pair."""
    if not utxo.output.datum:
        return False
    return utxo.output.datum.variant.datum.type == "NoRewards"


def _is_pending_transport(utxo: UTxO) -> bool:
    """Check if UTxO is pending transport."""
    if not utxo.output.datum:
        return False
    return utxo.output.datum.variant.datum.type == "RewardConsensusPending"
