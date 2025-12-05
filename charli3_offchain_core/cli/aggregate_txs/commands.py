"""Oracle transaction CLI commands."""

import click

from .odv_aggregate import odv_aggregate


@click.group()
def aggregate_tx() -> None:
    """Oracle transaction commands."""


aggregate_tx.add_command(odv_aggregate)
