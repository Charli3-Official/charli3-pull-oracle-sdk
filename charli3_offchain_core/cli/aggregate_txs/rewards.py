"""CLI commands for Oracle reward calculation and distribution."""

import logging
from pathlib import Path

import click
from pycardano import UTxO

from charli3_offchain_core.models.oracle_datums import RewardAccountDatum
from charli3_offchain_core.oracle.aggregate.builder import (
    OracleTransactionBuilder,
    RewardsResult,
)
from charli3_offchain_core.oracle.exceptions import TransactionError
from charli3_offchain_core.oracle.utils import state_checks

from ..config.formatting import print_confirmation_prompt, print_header, print_progress
from ..config.utils import async_command
from .base import TransactionContext, TxConfig, tx_options

logger = logging.getLogger(__name__)


@click.group()
def rewards() -> None:
    """Reward calculation and distribution commands."""
    pass


@rewards.command()
@tx_options
@click.option(
    "--batch-size",
    type=int,
    default=8,
    help="Maximum number of transports to process",
)
@click.option(
    "--wait/--no-wait",
    default=True,
    help="Wait for transaction confirmation",
)
@async_command
async def process(config: Path, batch_size: int, wait: bool) -> None:
    """Process pending rewards for ODV transactions.

    Example:
        charli3 tx rewards process --config tx-config.yaml --batch-size 4
    """
    try:
        # Load configuration and initialize context
        print_header("Reward Processing")
        print_progress("Loading configuration...")
        tx_config = TxConfig.from_yaml(config)
        ctx = TransactionContext(tx_config)

        # Load keys
        print_progress("Loading keys...")
        signing_key, change_address = ctx.load_keys()

        # Initialize builder
        builder = OracleTransactionBuilder(
            tx_manager=ctx.tx_manager,
            script_address=ctx.script_address,
            policy_id=ctx.policy_id,
            fee_token_hash=ctx.fee_token_policy_id,
            fee_token_name=ctx.fee_token_name,
        )

        # Build rewards transaction
        print_progress("Building rewards transaction...")
        result = await builder.build_rewards_tx(
            signing_key=signing_key,
            max_inputs=batch_size,
            change_address=change_address,
        )

        if not result.consensus_values:
            click.echo("No pending rewards to process")
            return

        # Display transaction details
        if not print_confirmation_prompt(
            {
                "Transports to Process": len(result.new_transports),
                "Total Nodes": len(result.reward_distribution.node_rewards),
                "Platform Fee": result.reward_distribution.platform_fee,
            }
        ):
            raise click.Abort()

        # Submit transaction
        print_progress("Submitting rewards transaction...")
        status, tx = await ctx.tx_manager.sign_and_submit(
            result.transaction, [signing_key], wait_confirmation=wait
        )

        click.secho(f"\n✓ Transaction {status}!", fg="green")
        click.echo(f"Transaction ID: {tx.id}")

        # Display reward details
        if status == "confirmed":
            _print_reward_summary(result)

    except TransactionError as e:
        logger.error("Transaction failed", exc_info=e)
        raise click.ClickException(f"Transaction failed: {e!s}") from e
    except Exception as e:
        logger.error("Reward processing failed", exc_info=e)
        raise click.ClickException(str(e)) from e


@rewards.command()
@tx_options
@async_command
async def status(config: Path) -> None:
    """Show current reward status and distributions.

    Example:
        charli3 tx rewards status --config tx-config.yaml
    """
    try:
        # Load configuration and initialize context
        print_header("Reward Status Check")
        print_progress("Loading configuration...")
        tx_config = TxConfig.from_yaml(config)
        ctx = TransactionContext(tx_config)

        # Get UTxO status
        print_progress("Checking reward status...")
        script_utxos = await ctx.chain_query.get_utxos(ctx.script_address)

        # Filter reward-related UTxOs
        pending_transports = state_checks.filter_pending_transports(script_utxos)
        reward_accounts = state_checks.filter_reward_accounts(script_utxos)

        # Display status
        _print_reward_status(pending_transports, reward_accounts)

    except Exception as e:
        logger.error("Status check failed", exc_info=e)
        raise click.ClickException(str(e)) from e


@rewards.command()
@tx_options
@click.option(
    "--node-id",
    type=int,
    required=True,
    help="Node ID to check rewards for",
)
@async_command
async def check_node(config: Path, node_id: int) -> None:
    """Check rewards for specific node.

    Example:
        charli3 tx rewards check-node --config tx-config.yaml --node-id 1
    """
    try:
        print_header(f"Node {node_id} Reward Check")
        print_progress("Loading configuration...")
        tx_config = TxConfig.from_yaml(config)
        ctx = TransactionContext(tx_config)

        # Get reward account
        print_progress("Checking reward account...")
        script_utxos = await ctx.chain_query.get_utxos(ctx.script_address)
        reward_accounts = state_checks.filter_reward_accounts(script_utxos)

        if not reward_accounts:
            click.echo("No reward account found")
            return

        # Display node rewards
        _print_node_rewards(reward_accounts[0], node_id)

    except Exception as e:
        logger.error("Node check failed", exc_info=e)
        raise click.ClickException(str(e)) from e


def _print_reward_summary(result: RewardsResult) -> None:
    """Print summary of processed rewards."""
    click.echo("\nReward Processing Summary:")
    click.echo("-" * 40)
    click.echo(f"Processed Transports: {len(result.new_transports)}")
    click.echo(f"Total Consensus Values: {len(result.consensus_values)}")

    click.echo("\nReward Distribution:")
    for node_id, amount in result.reward_distribution.node_rewards.items():
        click.echo(f"Node {node_id}: {amount}")

    click.echo(f"\nPlatform Fee: {result.reward_distribution.platform_fee}")
    click.echo(f"Total Distributed: {result.reward_distribution.total_distributed}")


def _print_reward_status(
    pending_transports: list[UTxO], reward_accounts: list[UTxO]
) -> None:
    """Print current reward status."""
    click.echo("\nReward Status:")
    click.echo("-" * 40)
    click.echo(f"Pending Transport UTxOs: {len(pending_transports)}")

    if pending_transports:
        click.echo("\nPending Transports:")
        for utxo in pending_transports:
            click.echo(f"- {utxo.input.transaction_id}#{utxo.input.index}")

    if reward_accounts:
        click.echo("\nReward Account Status:")
        account = reward_accounts[0].output.datum.variant.datum
        _print_reward_account_status(account)


def _print_reward_account_status(account: RewardAccountDatum) -> None:
    """Print reward account details."""
    total_rewards = 0
    nodes_with_rewards = 0

    for i in range(0, len(account.nodes_to_rewards), 2):
        _ = account.nodes_to_rewards[i]
        amount = account.nodes_to_rewards[i + 1]
        total_rewards += amount
        nodes_with_rewards += 1

    click.echo(f"Total Accumulated Rewards: {total_rewards}")
    click.echo(f"Nodes with Rewards: {nodes_with_rewards}")


def _print_node_rewards(reward_account: UTxO, node_id: int) -> None:
    """Print rewards for specific node."""
    account = reward_account.output.datum.variant.datum

    click.echo("\nNode Reward Status:")
    click.echo("-" * 40)

    # Find node's rewards
    for i in range(0, len(account.nodes_to_rewards), 2):
        if account.nodes_to_rewards[i] == node_id:
            amount = account.nodes_to_rewards[i + 1]
            click.echo(f"Current Reward Balance: {amount}")
            return

    click.echo("No rewards found for this node")
