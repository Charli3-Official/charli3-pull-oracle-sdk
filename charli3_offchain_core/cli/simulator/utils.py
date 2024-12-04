"""Utilities for oracle simulation."""

import json
import time

import click
from pycardano import VerificationKeyHash

from charli3_offchain_core.cli.simulator.models import (
    SimulationConfig,
    SimulationResult,
)
from charli3_offchain_core.models.oracle_datums import AggregateMessage


def create_aggregate_message(feed_data: dict) -> AggregateMessage:
    """Create aggregate message from node feeds.

    Args:
        feed_data: Dictionary of node feed data

    Returns:
        AggregateMessage for ODV submission
    """
    # Extract timestamp from first feed (they should all be the same)
    timestamp = feed_data[0]["timestamp"]

    # Create list of (vkh_hex, feed) tuples
    feeds = []
    for _, data in feed_data.items():
        # Convert verification key to VKH
        vkh = VerificationKeyHash(bytes.fromhex(data["verification_key"]))
        feed = data["feed"]
        feeds.append((vkh, feed))

    # Sort by feed value
    feeds.sort(key=lambda x: x[1])

    return AggregateMessage(
        node_feeds_sorted_by_feed=feeds,
        node_feeds_count=len(feeds),
        timestamp=timestamp,
    )


def print_simulation_config(config: "SimulationConfig") -> None:
    """Print simulation configuration.

    Args:
        config: Simulation configuration to display
    """
    click.echo("\nSimulation Configuration")
    click.echo("=======================")
    click.echo(f"Nodes: {config.node_count}")
    click.echo(f"Required Signatures: {config.required_signatures}")
    click.echo(f"Base Feed: {config.base_feed}")
    click.echo(f"Variance: {config.variance*100}%")
    click.echo(f"Wait Time: {config.wait_time} seconds")


def print_simulation_results(result: "SimulationResult") -> None:
    """Pretty print simulation results.

    Args:
        result: Simulation results to display
    """
    click.echo("\nSimulation Results")
    click.echo("=================")

    # Show ODV details
    click.echo("\nODV Transaction:")
    click.echo(f"ID: {result.odv_tx}")

    click.echo("\nNode Feeds:")
    for node_id, feed_data in result.feeds.items():
        click.echo(
            f"Node {node_id}: value={feed_data['feed']}, "
            f"ts={feed_data['timestamp']}"
        )

    # Show rewards
    click.echo("\nReward Distribution:")
    for node_id, amount in result.rewards.reward_distribution.node_rewards.items():
        click.echo(f"Node {node_id}: {amount}")

    click.echo(f"\nPlatform Fee: {result.rewards.reward_distribution.platform_fee}")
    click.echo(
        f"Total Distributed: {result.rewards.reward_distribution.total_distributed}"
    )


def save_simulation_results(result: "SimulationResult", output_file: str) -> None:
    """Save simulation results to JSON file.

    Args:
        result: Simulation results to save
        output_file: Path to output JSON file
    """
    output = {
        "timestamp": int(time.time() * 1000),
        "odv_transaction": result.odv_tx,
        "nodes": [node.to_dict() for node in result.nodes],
        "feeds": result.feeds,
        "rewards": {
            "distribution": result.rewards.reward_distribution.node_rewards,
            "platform_fee": result.rewards.reward_distribution.platform_fee,
            "total_distributed": result.rewards.reward_distribution.total_distributed,
        },
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
