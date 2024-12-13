"""CLI commands for oracle deployment and management."""

import json
import logging
from pathlib import Path

import click

from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.oracle.governance.orchestrator import GovernanceOrchestrator

from ..constants.status import ProcessStatus
from .config.formatting import (
    print_confirmation_message_prompt,
    print_hash_info,
    print_header,
    print_status,
)
from .config.utils import async_command
from .setup import setup_management_from_config

logger = logging.getLogger(__name__)


@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to deployment configuration YAML",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Output file for transaction data",
)
@click.command()
@async_command
async def update_settings(config: Path, output: Path | None) -> None:
    """UpdataSettings
    charli3 oracle update-settings --config platform-config.yaml
    """
    try:
        print_header("Oracle Update Settings")
        (
            management_config,
            payment_sk,
            oracle_addresses,
            chain_query,
            tx_manager,
            platform_auth_finder,
        ) = setup_management_from_config(config)

        platform_utxo = await platform_auth_finder.find_auth_utxo(
            policy_id=management_config.tokens.platform_auth_policy,
            platform_address=oracle_addresses.platform_address,
        )

        if not platform_utxo:
            raise click.ClickException("No platform auth UTxO found")

        platform_script = await platform_auth_finder.get_platform_script(
            oracle_addresses.platform_address
        )
        platform_config = platform_auth_finder.get_script_config(platform_script)

        orchestrator = GovernanceOrchestrator(
            chain_query=chain_query,
            tx_manager=tx_manager,
            script_address=oracle_addresses.script_address,
            status_callback=format_status_update,
        )

        result = await orchestrator.update_oracle(
            oracle_policy=management_config.tokens.oracle_policy,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=oracle_addresses.admin_address,
            signing_key=payment_sk,
        )
        if result.status == ProcessStatus.CANCELLED_BY_USER:
            print_status("Update Status", "Operation cancelled by user", success=True)
            return
        if result.status != ProcessStatus.TRANSACTION_BUILT:
            raise click.ClickException(f"Update failed: {result.error}")

        if platform_config.threshold == 1:
            if print_confirmation_message_prompt("Proceed with oracle update?"):
                status, _ = await tx_manager.sign_and_submit(
                    result.transaction, [payment_sk], wait_confirmation=True
                )
                if status != ProcessStatus.TRANSACTION_CONFIRMED:
                    raise click.ClickException(f"Update failed: {status}")
                print_status("Update", "completed successfully", success=True)
        elif print_confirmation_message_prompt("Store multisig update transaction?"):
            output_path = output or Path("tx_oracle_update_settings.json")
            with output_path.open("w") as f:
                json.dump(
                    {
                        "transaction": result.transaction.to_cbor_hex(),
                        "signed_by": [],
                        "threshold": platform_config.threshold,
                    },
                    f,
                )
            print_status("Transaction", "saved successfully", success=True)
            print_hash_info("Output file", str(output_path))

    except Exception as e:
        logger.error("Update failed", exc_info=e)
        raise click.ClickException(str(e)) from e
