"""Main CLI entry point for Charli3 ODV tools."""

import click

from charli3_offchain_core.cli.aggregate_txs import aggregate_tx
from charli3_offchain_core.cli.config.utils import setup_logging
from charli3_offchain_core.cli.node_keys.generate_node_keys_command import (
    generate_node_keys_command,
)
from charli3_offchain_core.cli.odv_client.commands import client
from charli3_offchain_core.cli.odv_simulator.commands import simulator
from charli3_offchain_core.cli.oracle import oracle
from charli3_offchain_core.cli.platform import platform


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """Charli3 Oracle Data Verification (ODV) CLI tools."""
    setup_logging(verbose)


# Add command groups
cli.add_command(oracle)
cli.add_command(client)
cli.add_command(aggregate_tx)
cli.add_command(platform)
cli.add_command(simulator)
cli.add_command(generate_node_keys_command, name="generate-node-keys")


if __name__ == "__main__":
    cli(_anyio_backend="asyncio", verbose="True")
