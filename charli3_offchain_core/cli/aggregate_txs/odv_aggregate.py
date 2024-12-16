"""CLI commands for Oracle Data Verification (ODV) operations."""

import json
import logging
from pathlib import Path
from typing import Any

import click
from pycardano import UTxO, VerificationKeyHash

from charli3_offchain_core.models.oracle_datums import AggregateMessage
from charli3_offchain_core.oracle.aggregate.builder import (
    OdvResult,
    OracleTransactionBuilder,
)
from charli3_offchain_core.oracle.exceptions import TransactionError

from ..config.formatting import print_confirmation_prompt, print_header, print_progress
from ..config.utils import async_command
from .base import TransactionContext, TxConfig, tx_options

logger = logging.getLogger(__name__)


@click.group()
def odv_aggregate() -> None:
    """ODV (On-Demand Validation) transaction commands."""


@odv_aggregate.command()
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
        charli3 tx odv_aggregate submit --config tx-config.yaml --feeds-file feeds.json
    """
    try:
        # Load configuration and initialize context
        print_header("ODV Transaction Submission")

        # Load and validate configuration
        print_progress("Loading configuration...")
        tx_config = TxConfig.from_yaml(config)
        ctx = TransactionContext(tx_config)

        # Load and validate feed data
        print_progress("Loading feeds data...")
        with feeds_file.open() as f:
            feed_data = json.load(f)
            validate_feed_data(feed_data)
            message = process_feed_data(feed_data)

        # Load keys
        print_progress("Loading keys...")
        signing_key, change_address = ctx.load_keys()

        # Initialize transaction builder
        builder = OracleTransactionBuilder(
            tx_manager=ctx.tx_manager,
            script_address=ctx.script_address,
            policy_id=ctx.policy_id,
            fee_token_hash=ctx.fee_token_policy_id,
            fee_token_name=ctx.fee_token_name,
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
                "Required Fees": result.transaction.transaction_body.fee,
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


@odv_aggregate.command()
@tx_options
@async_command
async def status(config: Path) -> None:
    """Show current ODV transaction status.

    Example:
        charli3 tx odv_aggregate status --config tx-config.yaml
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
    click.echo(f"Transport UTxO: {result.transport_output}")
    click.echo(f"AggState UTxO: {result.agg_state_output}")
    click.echo(f"Total Fees Paid: {result.transaction.transaction_body.fee}")


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


def validate_feed_data(feed_data: dict) -> None:
    """Validate feed data format and content.

    Expected format:
    {
        "node_feeds_sorted_by_feed": {
            "vkh1": feed_value1,
            "vkh2": feed_value2,
            ...
        },
        "node_feeds_count": integer,
        "timestamp": integer
    }
    """
    required_fields = ["node_feeds_sorted_by_feed", "node_feeds_count", "timestamp"]
    if not all(field in feed_data for field in required_fields):
        raise ValueError("Missing required fields in feed data")

    if not isinstance(feed_data["node_feeds_sorted_by_feed"], dict):
        raise ValueError("node_feeds_sorted_by_feed must be a dictionary")

    if not isinstance(feed_data["node_feeds_count"], int):
        raise ValueError("node_feeds_count must be an integer")

    if not isinstance(feed_data["timestamp"], int):
        raise ValueError("timestamp must be an integer")

    # Validate each node feed
    node_feeds = feed_data["node_feeds_sorted_by_feed"]

    # Check if count matches
    if len(node_feeds) != feed_data["node_feeds_count"]:
        raise ValueError("node_feeds_count doesn't match number of feeds")

    # Validate VKHs and feed values
    for vkh, feed_value in node_feeds.items():
        if not isinstance(vkh, str):
            raise ValueError(f"Invalid VKH format: {vkh}")
        try:
            # VKH should be a valid hex string
            bytes.fromhex(vkh)
        except ValueError as exc:
            raise ValueError(f"Invalid VKH hex format: {vkh}") from exc

        if not isinstance(feed_value, int):
            raise ValueError(f"Invalid feed value for VKH {vkh}")


def process_feed_data(feed_data: dict[str, Any]) -> AggregateMessage:
    """Process feed data directly into AggregateMessage.

    Instead of creating an intermediate dictionary, directly construct
    the AggregateMessage object.
    """
    # Convert string VKHs and build the feeds dictionary
    feeds = {}
    for vkh_str, feed_value in feed_data["node_feeds_sorted_by_feed"].items():
        vkh = VerificationKeyHash(bytes.fromhex(vkh_str))
        feeds[vkh] = feed_value  # NodeFeed is just an int

    # Directly create AggregateMessage
    return AggregateMessage(
        node_feeds_sorted_by_feed=feeds,
        node_feeds_count=feed_data["node_feeds_count"],
        timestamp=feed_data["timestamp"],
    )
