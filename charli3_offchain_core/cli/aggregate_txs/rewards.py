"""CLI commands for Oracle reward calculation and distribution."""

import logging
from pathlib import Path

import click

from charli3_offchain_core.oracle.aggregate.builder import (
    OracleTransactionBuilder,
    # RewardsResult,
)
from charli3_offchain_core.oracle.exceptions import TransactionError

from ..config.formatting import print_header, print_progress
from ..config.utils import async_command
from .base import TransactionContext, TxConfig, tx_options

logger = logging.getLogger(__name__)


@click.group()
def rewards() -> None:
    """Reward calculation and distribution commands."""


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
            reward_token_hash=ctx.reward_token_hash,
            reward_token_name=ctx.reward_token_name,
        )

        # Build rewards transaction
        print_progress("Building rewards transaction...")
        result = await builder.build_rewards_tx(
            signing_key=signing_key,
            max_inputs=batch_size,
            change_address=change_address,
        )

        # print_rewards_preview(result)

        if not click.confirm("\nProceed with reward processing?"):
            raise click.Abort()

        # Submit transaction
        print_progress("Submitting rewards transaction...")
        tx_status, _ = await ctx.tx_manager.sign_and_submit(
            result.transaction, [signing_key], wait_confirmation=wait
        )

        click.secho(f"\n✓ Transaction {tx_status}!", fg="green")
        click.echo(f"Transaction ID: {result.transaction.id}")

        # Display detailed results
        # if tx_status == "confirmed":
        #     _print_reward_summary(result)

    except TransactionError as e:
        if "No pending transport UTxOs found" in str(e.__cause__):
            logger.info(
                "No rewards to process at this time - this is normal if no ODV aggregate transactions are pending"
            )
            return
        logger.error("Transaction failed: %s", e)

    except Exception as e:
        logger.error("Reward processing failed", exc_info=e)
        raise click.ClickException(str(e)) from e


# def print_rewards_preview(result: RewardsResult) -> None:
#     """Print detailed preview of rewards processing."""
#     click.echo("\nReward Processing Details:")
#     click.echo("-" * 40)

#     # Print summary
#     click.echo(f"Transports to Process: {len(result.pending_transports)}")
#     total_rewards = sum(result.reward_distribution.values())
#     click.echo(f"Total Node Rewards: {total_rewards}")
#     click.echo(f"Platform Fee: {result.platform_fee}")
#     click.echo(f"Total Distribution: {result.total_distributed}")

#     # Print transport details
#     for detail in result.transport_details:
#         click.echo(f"\nTransport {detail['tx_hash']}#{detail['index']}:")
#         click.echo(f"  Oracle Feed: {detail['oracle_feed']}")
#         click.echo(f"  Participating Nodes: {detail['node_count']}")
#         click.echo(f"  Reward per Node: {detail['reward_per_node']}")
#         click.echo(f"  Platform Fee: {detail['platform_fee']}")
#         click.echo(f"  Total Amount: {detail['total_amount']}")
#         click.echo(f"  Timestamp: {detail['timestamp']}")

#         if logger.isEnabledFor(logging.DEBUG):
#             click.echo("\n  Node Feeds:")
#             for node_vkh, feed in detail["node_feeds"].items():
#                 click.echo(f"    {node_vkh}: {feed}")

#     # Print reward distribution
#     if result.reward_distribution:
#         click.echo("\nProposed Reward Distribution:")
#         click.echo("-" * 40)
#         for node_vkh, amount in result.reward_distribution.items():
#             click.echo(f"  {node_vkh}: {amount}")


# def _print_reward_summary(result: RewardsResult) -> None:
#     """Print final reward processing summary."""
#     click.echo("\nReward Processing Summary:")
#     click.echo("-" * 40)
#     click.echo(f"Transaction ID: {result.transaction.id}")
#     click.echo(f"Processed Transports: {len(result.pending_transports)}")

#     total_rewards = sum(result.reward_distribution.values())
#     click.echo(f"Total Node Rewards: {total_rewards}")
#     click.echo(f"Platform Fee: {result.platform_fee}")
#     click.echo(f"Total Distribution: {result.total_distributed}")

#     if result.reward_distribution:
#         click.echo("\nFinal Reward Distribution:")
#         for node_vkh, amount in result.reward_distribution.items():
#             click.echo(f"  {node_vkh}: {amount}")
