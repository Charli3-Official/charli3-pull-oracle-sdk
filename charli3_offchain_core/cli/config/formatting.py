"""CLI output enhancements for oracle deployment."""

from enum import Enum
from typing import Any

import click


class CliColor(str, Enum):
    """CLI color scheme"""

    SUCCESS = "green"
    ERROR = "red"
    WARNING = "yellow"
    INFO = "blue"
    HEADER = "cyan"
    ADDRESS = "bright_blue"
    HASH = "bright_black"
    PROGRESS = "yellow"
    TITLE = "bright_cyan"


def print_header(text: str) -> None:
    """Print styled header text."""
    click.echo()
    click.secho(f"=== {text} ===", fg=CliColor.HEADER, bold=True)
    click.echo()


def print_address_info(label: str, address: str) -> None:
    """Print formatted address information."""
    click.echo(
        f"{click.style(label, fg=CliColor.INFO)}: "
        f"{click.style(address, fg=CliColor.ADDRESS)}"
    )


def print_hash_info(label: str, hash_value: str) -> None:
    """Print formatted hash information."""
    click.echo(
        f"{click.style(label, fg=CliColor.INFO)}: "
        f"{click.style(hash_value, fg=CliColor.HASH)}"
    )


def print_status(status: str, message: str, success: bool = True) -> None:
    """Print status message with appropriate styling."""
    icon = "✓" if success else "✗"
    color = CliColor.SUCCESS if success else CliColor.ERROR
    click.secho(f"{icon} {status}: {message}", fg=color)


def print_progress(message: str) -> None:
    """Print progress message."""
    click.secho(f"⟳ {message}...", fg=CliColor.PROGRESS)


def format_deployment_summary(result: Any) -> None:
    """Format and print deployment summary."""
    print_header("Deployment Summary")

    if result.reference_scripts and result.reference_scripts.manager_tx:
        print_status("Manager Reference Script", "Created")
        print_hash_info("Transaction Hash", str(result.reference_scripts.manager_tx.id))

    if result.start_result:
        print_header("Oracle UTxOs Created")
        print_status("Settings UTxO", "Created")
        print_status("Reward Account UTxO", "Created")
        print_status(
            "Reward Transport UTxOs",
            f"{len(result.start_result.reward_transport_utxos)} created",
        )
        print_status(
            "Aggregation State UTxOs",
            f"{len(result.start_result.agg_state_utxos)} created",
        )
        print_hash_info(
            "Start Transaction Hash", str(result.start_result.transaction.id)
        )


def format_status_update(status: str, message: str) -> None:
    """Format deployment status updates with colors."""
    status_colors = {
        "NOT_STARTED": CliColor.INFO,
        "CHECKING_REFERENCE_SCRIPTS": CliColor.INFO,
        "CREATING_MANAGER_REFERENCE": CliColor.PROGRESS,
        "BUILDING_START_TX": CliColor.PROGRESS,
        "SUBMITTING_START_TX": CliColor.WARNING,
        "WAITING_CONFIRMATION": CliColor.WARNING,
        "COMPLETED": CliColor.SUCCESS,
        "FAILED": CliColor.ERROR,
    }

    click.echo()
    click.secho(f"[{status}]", fg=status_colors.get(status, CliColor.INFO), bold=True)
    click.secho(f"└─ {message}", fg=CliColor.INFO)


def print_confirmation_prompt(addresses: dict[str, str]) -> bool:
    """Print colored confirmation prompt for addresses."""
    print_header("Deployment Addresses")
    for label, address in addresses.items():
        print_address_info(label, address)

    click.echo()
    return click.confirm(
        click.style("Continue with these addresses?", fg=CliColor.WARNING, bold=True)
    )


# Example usage in cli/oracle.py:
def enhanced_deploy_output(config: Any, addresses: Any) -> None:
    """Example of enhanced CLI output for deployment."""
    print_header("Loading Configuration")
    print_progress("Loading base contracts from blueprint")
    print_progress("Parameterizing contracts")

    # Display addresses
    address_info = {
        "Admin Address": addresses.admin_address,
        "Script Address": addresses.script_address,
    }
    if not print_confirmation_prompt(address_info):
        raise click.Abort()

    print_progress("Initializing deployment orchestrator")
    print_progress("Starting oracle deployment")


def print_confirmation_message_prompt(message: str) -> bool:
    """Print colored confirmation prompt for message."""
    return click.confirm(click.style(message, fg=CliColor.WARNING, bold=True))


def print_platform_auth_config_prompt(auth_config: any) -> bool:
    """Format and display platform authorization details with a confirmation prompt."""

    print_header("Platform Authorization Config Details")
    print_hash_info("Network", auth_config.network.network)
    print_hash_info("Multisig Threshold", str(auth_config.multisig.threshold))

    for i, party in enumerate(auth_config.multisig.parties, start=1):
        print_address_info(f"PKH {i}", party)

    return print_confirmation_message_prompt("Proceed with token minting?")
