"""Main CLI entry point for Charli3 ODV tools."""

import click

from charli3_offchain_core.cli.config.utils import setup_logging
from charli3_offchain_core.cli.oracle import oracle
from charli3_offchain_core.cli.txs import tx


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """Charli3 Oracle Data Verification (ODV) CLI tools."""
    setup_logging(verbose)


# Add command groups
cli.add_command(oracle)
cli.add_command(tx)


if __name__ == "__main__":
    cli(_anyio_backend="asyncio", verbose="True")
