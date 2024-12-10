"""Update settings CLI"""

import json
import logging
from collections.abc import Callable
from pathlib import Path

import click

from charli3_offchain_core.cli.config.formatting import (
    format_status_update,
    print_allowed_datum_changes,
    print_confirmation_message_prompt,
    print_hash_info,
    print_information,
    print_progress,
    print_status,
    print_title,
)
from charli3_offchain_core.cli.config.update_settings import PlatformTxConfig
from charli3_offchain_core.cli.config.utils import async_command
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.oracle.transactions.update_settings import UpdateCoreSettings

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
    try:
        # Load and validate configuration
        print_title("Update Oracle Settings")
        use_config_file = print_confirmation_message_prompt(
            "Do you want to load the configuration using the current configuration file?"
        )
        if not use_config_file:
            return
        print_progress("Loading configuration")

        # Load Update-Settings configuraion files
        plat_tx_config = PlatformTxConfig.from_yaml(config)
        update_settings = UpdateCoreSettings(plat_tx_config, format_status_update)
        sk, _, _, addr = update_settings.key_manager

        # Fetch deployed core UTxO
        deployed_core_utxo = await update_settings.get_core_settings_utxo

        # Display detected changes
        changes_allowed = await print_allowed_datum_changes(
            deployed_core_utxo.output.datum.datum, plat_tx_config
        )
        if not changes_allowed:
            print_information("The requested changes are already present.")
            return

        # Confirm proceeding with changes
        if not print_confirmation_message_prompt(
            "Do you want to proceed with the changes above?"
        ):
            return

        # Generate modified core UTxO and validation
        modified_core_utxo = await update_settings.modified_core_utxo

        # Retrieve auth UTxO and associated reference script
        auth_utxo = await update_settings.platform_auth_finder.find_auth_utxo(
            policy_id=update_settings.tx_config.tokens.platform_auth_policy,
            platform_address=update_settings.tx_config.multi_sig.platform_addr,
        )
        auth_native_script = await update_settings.get_native_script

        # Fetch contract reference UTxO
        contract_reference_utxo = await update_settings.get_contract_reference_utxo

        # Update Status
        update_settings._update_status(
            ProcessStatus.BUILDING_TRANSACTION,
            "Builidng transaction...",
        )

        # Build transaction
        tx_manager = await update_settings.transaction_manager.build_script_tx(
            script_inputs=[
                (
                    deployed_core_utxo,
                    update_settings.REDEEMER,
                    contract_reference_utxo,
                ),
                (auth_utxo, None, auth_native_script),
            ],
            script_outputs=[
                modified_core_utxo.output,
                auth_utxo.output,
            ],
            change_address=addr,
            signing_key=sk,
        )

        # Handle transaction signing based on requirements
        if await update_settings.required_single_signature:
            update_settings._update_status(
                ProcessStatus.SIGNING_TRANSACTION,
                "Signing transaction...",
            )
            try:
                status, _ = await update_settings.transaction_manager.sign_and_submit(
                    tx_manager, [sk]
                )
                if status == ProcessStatus.TRANSACTION_CONFIRMED:
                    print_status(
                        "Status",
                        "Tx built and signed successfully",
                        success=True,
                    )
                    print_hash_info("Transaction ID", str(tx_manager.id))
                else:
                    update_settings._update_status(ProcessStatus.FAILED)
                    raise click.ClickException(f"Deployment failed: {status}")
            except Exception as e:
                logger.error("Deployment failed: %s", str(e))
                raise click.ClickException("Transaction signing failed.") from e

        elif print_confirmation_message_prompt(
            "PlatformAuth NFT being used requires multisigatures and thus will be stored. Would you like to continue?"
        ):
            output_path = output or Path("tx_oracle_update_settings.json")
            threshold = (
                deployed_core_utxo.output.datum.datum.required_node_signatures_count
            )
            with output_path.open("w") as f:
                json.dump(
                    {
                        "transaction": tx_manager.to_cbor_hex(),
                        "script_address": str(
                            update_settings.tx_config.contract_address
                        ),
                        "signed_by": [],
                        "threshold": threshold,
                    },
                    f,
                )
            print_status("Transaction", "saved successfully", success=True)
            print_hash_info("Output file", str(output_path))
            print_hash_info(
                "Next steps",
                f"Transaction requires {threshold} signatures",
            )
    except Exception as e:
        logger.error("Deployment failed", exc_info=e)
        raise click.ClickException(str(e)) from e
