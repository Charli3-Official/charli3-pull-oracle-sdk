"""CLI output enhancements for oracle deployment."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, NamedTuple

import click
from pycardano import Transaction

from charli3_offchain_core.cli.config.update_settings import PlatformTxConfig
from charli3_offchain_core.models.oracle_datums import OracleSettingsDatum

from ...constants.colors import CliColor
from ...constants.status import ProcessStatus


def print_header(text: str) -> None:
    """Print styled header text."""
    click.echo()
    click.secho(f"=== {text} ===", fg=CliColor.HEADER, bold=True)
    click.echo()


def print_information(text: str) -> None:
    """Print styled information text."""
    click.secho(f"=== {text} ===", fg=CliColor.INFO, bold=True)


def print_title(text: str) -> None:
    """Print styled title text."""
    click.secho(f"=== {text} ===", fg=CliColor.TITLE, bold=True)


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


def format_status_update(status: ProcessStatus, message: str) -> None:
    """Format and display deployment status updates."""
    colors = {
        ProcessStatus.NOT_STARTED: CliColor.INFO,
        ProcessStatus.CHECKING_REFERENCE_SCRIPTS: CliColor.INFO,
        ProcessStatus.CREATING_SCRIPT: CliColor.WARNING,
        ProcessStatus.BUILDING_TRANSACTION: CliColor.INFO,
        ProcessStatus.SUBMITTING_TRANSACTION: CliColor.WARNING,
        ProcessStatus.WAITING_CONFIRMATION: CliColor.WARNING,
        ProcessStatus.TRANSACTION_SIGNED: CliColor.SUCCESS,
        ProcessStatus.TRANSACTION_SUBMITTED: CliColor.SUCCESS,
        ProcessStatus.COMPLETED: CliColor.SUCCESS,
        ProcessStatus.FAILED: CliColor.ERROR,
    }

    click.secho(f"\n[{status}]", fg=colors.get(status, CliColor.INFO), bold=True)
    click.secho(message, fg=colors.get(status, CliColor.INFO))


def print_confirmation_prompt(addresses: dict[str, str]) -> bool:
    """Print colored confirmation prompt for addresses."""
    print_header("Deployment Addresses")
    for label, address in addresses.items():
        print_address_info(label, address)

    click.echo()
    return click.confirm(
        click.style("Continue with these addresses?", fg=CliColor.WARNING, bold=True)
    )


def oracle_success_callback(tx: Transaction, data: dict) -> None:
    print_status(
        "Oracle deployment",
        "Transaction submitted successfully",
        success=True,
    )
    if "script_address" in data:
        print_hash_info("Script Address", data["script_address"])


def platform_success_callback(tx: Transaction, data: dict) -> None:
    print_status(
        "Platform authorization token",
        "Transaction submitted successfully",
        success=True,
    )
    print_hash_info("Transaction ID", tx.id)
    print_hash_info("Platform Address", data["platform_address"])
    print_hash_info("Policy ID", data["policy_id"])


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


def print_changes(changes: dict[str, int]) -> None:
    """Print the final changes that will be applied."""
    print_header("Changes to be Applied")
    for option, value in changes.items():
        print_information(f"Option {option}", f"New value: {value}")


class ConfigOptions(str, Enum):
    """Available configuration options"""

    OPTION_A = "A"
    OPTION_B = "B"
    OPTION_C = "C"
    OPTION_D = "D"


update_settings_options = {
    ConfigOptions.OPTION_A: "Option A",
    ConfigOptions.OPTION_B: "Option B",
    ConfigOptions.OPTION_C: "Option C",
    ConfigOptions.OPTION_D: "Option D",
}


@dataclass
class ChangeDetail:
    """Represents a change in datum settings."""

    field_name: str
    previous_value: Any
    new_value: Any

    def __str__(self) -> str:
        return (
            f"Change detected in {self.field_name}:\n"
            f"  Previous: {self.previous_value}\n"
            f"  New: {self.new_value}"
        )


class DatumComparison(NamedTuple):
    """Defines a comparison between old and new datum values."""

    field_name: str
    previous_value: Any
    new_value: Any
    is_equal: bool


async def print_allowed_datum_changes(
    deployed_core_settings_datum: OracleSettingsDatum, tx_config: PlatformTxConfig
) -> bool:
    """
    Compare and display changes between deployed core settings and current transaction config.
    Uses styled output to highlight changes.

    Args:
        deployed_core_settings_datum: The current deployed settings
        tx_config: The new transaction configuration
    """
    # Define comparisons
    comparisons = [
        DatumComparison(
            "Aggregation Liveness Period",
            deployed_core_settings_datum.aggregation_liveness_period,
            tx_config.timing.aggregation_liveness,
            deployed_core_settings_datum.aggregation_liveness_period
            == tx_config.timing.aggregation_liveness,
        ),
        DatumComparison(
            "Time Absolute Uncertainty",
            deployed_core_settings_datum.time_absolute_uncertainty,
            tx_config.timing.time_uncertainty,
            deployed_core_settings_datum.time_absolute_uncertainty
            == tx_config.timing.time_uncertainty,
        ),
        DatumComparison(
            "IQR Fence Multiplier",
            deployed_core_settings_datum.iqr_fence_multiplier,
            tx_config.timing.iqr_multiplier,
            deployed_core_settings_datum.iqr_fence_multiplier
            == tx_config.timing.iqr_multiplier,
        ),
        DatumComparison(
            "Required Node Signatures Count",
            deployed_core_settings_datum.required_node_signatures_count,
            tx_config.multi_sig.threshold,
            deployed_core_settings_datum.required_node_signatures_count
            == tx_config.multi_sig.threshold,
        ),
    ]

    changes_found = False

    for comparison in comparisons:
        if not comparison.is_equal:
            if not changes_found:
                print_information("Configuration Changes Detected")
                changes_found = True

            change = ChangeDetail(
                comparison.field_name, comparison.previous_value, comparison.new_value
            )
            click.echo(str(change))
            click.echo()

    if not changes_found:
        print_information("No Configuration Changes Detected")

    return changes_found
