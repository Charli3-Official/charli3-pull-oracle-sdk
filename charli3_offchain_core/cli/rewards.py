"""CLI commands for oracle rewards. """

import json
import logging
from pathlib import Path

import click

from charli3_offchain_core.blockchain.exceptions import CollateralError
from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.oracle.exceptions import (
    ADABalanceNotFoundError,
    NodeCollectCancelled,
    NodeNotRegisteredError,
    NoRewardsAvailableError,
)
from charli3_offchain_core.oracle.rewards.orchestrator import RewardOrchestrator

from ..constants.status import ProcessStatus
from .config.formatting import (
    print_confirmation_message_prompt,
    print_hash_info,
    print_header,
    print_progress,
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
async def node_collect(config: Path, output: Path | None) -> None:
    """Node Operator Withdrawal Transaction: Individual Rewards Collection"""
    try:
        print_progress("Loading Node Collect Configuration")
        (
            management_config,
            _,
            loaded_key,
            oracle_addresses,
            chain_query,
            tx_manager,
            _,
        ) = setup_management_from_config(config)

        orchestrator = RewardOrchestrator(
            chain_query=chain_query,
            tx_manager=tx_manager,
            script_address=oracle_addresses.script_address,
            status_callback=format_status_update,
        )

        result = await orchestrator.collect_node_oracle(
            oracle_policy=management_config.tokens.oracle_policy,
            user_address=oracle_addresses.admin_address,
            tokens=management_config.tokens,
            loaded_key=loaded_key,
            network=management_config.network.network,
        )
        if isinstance(result.error, NodeNotRegisteredError):
            user_message = (
                f"The payment verification key hash (VKH) derived from the configuration "
                f"is not associated with any node in the oracle contract.\n"
                f"Payment Verification Key Hash (VKH): {result.error}\n"
                f"Oracle contract address: {oracle_addresses.script_address}\n"
                "Please ensure the mnemonic in the configuration file is correct and "
                "corresponds to a registered node."
            )
            print_status(result.status, user_message, False)
            return

        if isinstance(result.error, NoRewardsAvailableError):
            user_message = (
                f"No rewards available for payment VKH {result.error} under contract"
                f" {oracle_addresses.script_address}. "
                "Please verify your account balance and try again later."
            )
            print_status(result.status, user_message, True)
            return

        if isinstance(result.error, NodeCollectCancelled):
            print_status(
                "Collect Node Status", "Operation cancelled by user", success=True
            )
            return
        if isinstance(result.error, ADABalanceNotFoundError | CollateralError):
            user_message = (
                "Your wallet appears to be empty.\n"
                "ADA is required for transaction fees.\n"
                f"Wallet address: {loaded_key.address}"
            )

            print_status(result.status, user_message, success=False)

            return

        if result.status != ProcessStatus.TRANSACTION_BUILT:
            raise click.ClickException(f"Collect Node failed: {result.error}")

        if result.transaction and print_confirmation_message_prompt(
            "Proceed signing and submitting Node-Collect tx?"
        ):
            status, _ = await tx_manager.sign_and_submit(
                result.transaction, [loaded_key.payment_sk], wait_confirmation=True
            )
            if status != ProcessStatus.TRANSACTION_CONFIRMED:
                raise click.ClickException(f"Collect nodes failed: {status}")
            print_status("Collect nodes", "completed successfully", success=True)

    except Exception as e:
        logger.error("Collect nodes failed", exc_info=e)
        raise click.ClickException(str(e)) from e


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
async def platform_collect(config: Path, output: Path | None) -> None:
    """Platform Withdrawal Transaction: Individual Rewards Collection"""
    try:
        print_header("Platform Collect")
        (
            management_config,
            _,
            loaded_key,
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

        orchestrator = RewardOrchestrator(
            chain_query=chain_query,
            tx_manager=tx_manager,
            script_address=oracle_addresses.script_address,
            status_callback=format_status_update,
        )

        result = await orchestrator.collect_platform_oracle(
            oracle_policy=management_config.tokens.oracle_policy,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            user_address=oracle_addresses.admin_address,
            tokens=management_config.tokens,
            signing_key=loaded_key.payment_sk,
            network=management_config.network.network,
        )
        if result.status == ProcessStatus.CANCELLED_BY_USER:
            print_status(
                "Collect Platform Status", "Operation cancelled by user", success=True
            )
            return
        if result.status == ProcessStatus.VERIFICATION_FAILURE:
            print_status(
                "Collect Platform Status",
                "On-chain validation does not meet the requirements.",
                success=False,
            )
            return
        if result.status != ProcessStatus.TRANSACTION_BUILT:
            raise click.ClickException(f"Platform Collect failed: {result.error}")

        if platform_config.threshold == 1:
            if print_confirmation_message_prompt("Proceed with Platform Collect?"):
                status, _ = await tx_manager.sign_and_submit(
                    result.transaction, [loaded_key.payment_sk], wait_confirmation=True
                )
                if status != ProcessStatus.TRANSACTION_CONFIRMED:
                    raise click.ClickException(f"Platfrom Collect failed: {status}")
                print_status("Platform Collect", "completed successfully", success=True)
        elif print_confirmation_message_prompt("Store multisig update transaction?"):
            output_path = output or Path("tx_oracle_platform_collect.json")
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
        logger.error("Platform Collect failed", exc_info=e)
        raise click.ClickException(str(e)) from e
