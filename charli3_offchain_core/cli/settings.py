"""Update settings CLI"""

import logging
from collections.abc import Callable
from pathlib import Path

import click

from charli3_offchain_core.cli.config.formatting import (
    format_status_update,
    get_configuration_method,
    print_hash_info,
    print_progress,
    print_status,
    print_title,
)
from charli3_offchain_core.cli.config.update_settings import PlatformTxConfig
from charli3_offchain_core.cli.config.utils import async_command
from charli3_offchain_core.oracle.transactions.update_settings import (
    TransactionResult,
    UpdateCoreSettings,
)

logger = logging.getLogger(__name__)


def tx_options(f: Callable) -> Callable:
    """Common transaction command options.

    Args:
        f: Function to decorate

    Returns:
        Decorated function with common options
    """
    f = click.option(
        "--config",
        type=click.Path(exists=True, path_type=Path),
        required=True,
        help="Path to transaction configuration YAML",
    )(f)
    f = click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")(f)
    return f


@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Output file for transaction data",
)
@click.command()
@async_command
@tx_options
async def update_settings(config: Path, verbose: bool, output: Path | None) -> None:
    """UpdataSettings
    charli3 oracle update-settings --config platform-config.yaml
    """
    print_progress("Loading configuration")
    plat_tx_config = PlatformTxConfig.from_yaml(config)
    settings_manager = UpdateCoreSettings(plat_tx_config, format_status_update)

    try:
        # Load current settings
        deployed_core_utxo = await settings_manager.get_core_settings_utxo()

        # Title
        print_title("Update Oracle Settings")

        # Get modified_settings based on user choice
        config_method = get_configuration_method()

        if config_method == "Load settings from configuration file":
            modified_core_utxo = await settings_manager.allowed_datum_changes_from_file(
                deployed_core_utxo
            )
        else:
            modified_core_utxo = await settings_manager.manual_settings_menu(
                deployed_core_utxo
            )
        # Process the update
        result = await settings_manager.process_update(modified_core_utxo, output)

        # Handle result
        if isinstance(result, TransactionResult):
            print_status("Status", "Tx built and signed successfully", success=True)
            print_hash_info("Transaction ID", str(result.tx_id))
        else:  # MultisigResult
            print_status("Transaction", "saved successfully", success=True)
            print_hash_info("Output file", str(result.output_path))
            print_hash_info(
                "Next steps", f"Transaction requires {result.threshold} signatures"
            )

    except Exception as e:
        logger.error("Update Settings failed", exc_info=e)
        raise click.ClickException(str(e)) from e
