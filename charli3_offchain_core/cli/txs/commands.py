"""Oracle transaction CLI commands."""

import click

from .odv import odv
from .rewards import rewards


@click.group()
def tx() -> None:
    """Oracle transaction commands."""
    pass


tx.add_command(odv)
tx.add_command(rewards)
