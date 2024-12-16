"""Oracle transaction CLI commands."""

import click

from .odv_aggregate import odv_aggregate
from .rewards import rewards


@click.group()
def tx() -> None:
    """Oracle transaction commands."""


tx.add_command(odv_aggregate)
tx.add_command(rewards)
