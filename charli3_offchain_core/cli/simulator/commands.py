"""CLI commands for oracle simulation."""

from pathlib import Path

import click

from charli3_offchain_core.cli.config.utils import async_command
from charli3_offchain_core.cli.simulator.models import SimulationConfig
from charli3_offchain_core.cli.simulator.oracle import OracleSimulator
from charli3_offchain_core.cli.simulator.utils import (
    print_simulation_config,
    print_simulation_results,
    save_simulation_results,
)
from charli3_offchain_core.cli.txs.base import tx_options


@click.group()
def simulator() -> None:
    """Oracle simulator commands."""


@simulator.command()
@tx_options
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Save results to JSON file",
)
@async_command
async def run(
    config: Path,
    output: Path | None,
) -> None:
    """Run complete oracle simulation using configuration file."""
    # Load simulation config
    sim_config = SimulationConfig.from_yaml(config)

    # Create simulator
    oracle_simulator = OracleSimulator(sim_config)

    # Show configuration
    print_simulation_config(sim_config.simulation)

    try:
        # Run simulation
        click.echo("\nStarting Simulation...")
        result = await oracle_simulator.run_simulation()

        # Show results
        print_simulation_results(result)

        # Save if requested
        if output:
            click.echo(f"\nSaving results to {output}")
            save_simulation_results(result, output)

    except Exception as e:
        raise click.ClickException(f"Simulation failed: {e}") from e
