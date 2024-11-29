"""CLI commands for oracle simulation."""

from pathlib import Path

import click

from charli3_offchain_core.cli.config.utils import async_command
from charli3_offchain_core.cli.simulator.oracle import OracleSimulator, SimulationConfig
from charli3_offchain_core.cli.simulator.utils import (
    print_simulation_config,
    print_simulation_results,
    save_simulation_results,
)
from charli3_offchain_core.cli.txs.base import TxConfig


@click.group()
def simulator() -> None:
    """Oracle simulator commands."""


@simulator.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Transaction config file",
)
@click.option(
    "--node-count",
    type=int,
    default=4,
    help="Number of test nodes",
)
@click.option(
    "--required-sigs",
    type=int,
    help="Required signature count (defaults to n-1)",
)
@click.option(
    "--feed-value",
    type=int,
    required=True,
    help="Base feed value",
)
@click.option(
    "--variance",
    type=float,
    default=0.01,
    help="Feed value variance (0-1)",
)
@click.option(
    "--wait-time",
    type=int,
    default=60,
    help="Seconds to wait between ODV and rewards",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Save results to JSON file",
)
@async_command
async def run(
    config: Path,
    node_count: int,
    required_sigs: int | None,
    feed_value: int,
    variance: float,
    wait_time: int,
    output: Path | None,
) -> None:
    """Run complete oracle simulation."""
    # Load config and create simulator
    tx_config = TxConfig.from_yaml(config)
    sim_config = SimulationConfig(
        node_count=node_count,
        required_signatures=required_sigs,
        base_feed=feed_value,
        variance=variance,
        wait_time=wait_time,
    )

    simulator = OracleSimulator(tx_config, sim_config)

    # Show configuration
    print_simulation_config(sim_config)

    try:
        # Run simulation
        click.echo("\nStarting Simulation...")
        result = await simulator.run_simulation()

        # Show results
        print_simulation_results(result)

        # Save if requested
        if output:
            click.echo(f"\nSaving results to {output}")
            save_simulation_results(result, output)

    except Exception as e:
        raise click.ClickException(f"Simulation failed: {e}") from e
