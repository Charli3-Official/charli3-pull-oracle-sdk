import json
import logging
from pathlib import Path

import click
from pycardano import Transaction

from charli3_offchain_core.cli.config.formatting import (
    print_confirmation_message_prompt,
    print_hash_info,
    print_platform_auth_config_prompt,
    print_status,
)

from ..platform.auth.orchestrator import (
    ProcessStatus,
)
from .config.utils import async_command
from .setup import setup_platform_from_config

logger = logging.getLogger(__name__)


@click.group()
def platform() -> None:
    """Platform authorization commands."""
    pass


@platform.group()
def token() -> None:
    """Platform authorization commands."""
    pass


@token.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to platform configuration YAML",
)
@click.option(
    "--metadata",
    type=click.Path(exists=True, path_type=Path),
    help="Optional metadata JSON file",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Output file for transaction data",
)
@async_command
async def mint(
    config: Path,
    metadata: Path | None,
    output: Path | None = None,
) -> None:
    """Build and sign/submit platform auth token transaction."""
    try:
        (
            auth_config,
            payment_sk,
            payment_vk,
            _,
            default_addr,
            _,
            _,
            orchestrator,
            meta_data,
        ) = setup_platform_from_config(config, metadata)

        if not print_platform_auth_config_prompt(auth_config):
            raise click.Abort()

        result = await orchestrator.build_tx(
            sender_address=default_addr,
            signing_key=payment_sk,
            multisig_threshold=auth_config.multisig.threshold,
            multisig_parties=auth_config.multisig.parties,
            metadata=meta_data,
            network=auth_config.network.network,
            is_mock=False,
        )

        if result.status != ProcessStatus.TRANSACTION_BUILT:
            raise click.ClickException(f"Failed to create transaction: {result.error}")

        # Handle based on threshold
        if auth_config.multisig.threshold > 1:
            output = output or Path("tx_platform_mint.json")
            data = {
                "transaction": result.transaction.to_cbor_hex(),
                "policy_id": result.policy_id,
                "signed_by": [],
                "platform_address": str(result.platform_address),
                "threshold": auth_config.multisig.threshold,
            }

            if print_confirmation_message_prompt(
                "Would you like to sign the transaction now?"
            ):
                signed_tx, status = await orchestrator.handle_tx(
                    result.transaction, payment_sk, submit=False
                )
                result.status = status
                if status == ProcessStatus.TRANSACTION_SIGNED:
                    data["transaction"] = signed_tx.to_cbor_hex()
                    data["signed_by"].append(str(payment_vk.payload.hex()))
                else:
                    raise click.ClickException("Transaction failed: ")

            with output.open("w") as f:
                json.dump(data, f)

            if result.status == ProcessStatus.TRANSACTION_SIGNED:
                print_status("Status", "Tx built and signed successfully", success=True)
                print_hash_info("Output file", str(output))
                print_hash_info(
                    "Reminder",
                    "Tx requires more than 1 signatures for successful submission",
                )

        else:
            submitted_tx, status = await orchestrator.handle_tx(
                result.transaction, payment_sk, submit=True
            )

            if status == ProcessStatus.COMPLETED:
                print_status(
                    "Platform authorization token", "Minted successfully", success=True
                )
                print_hash_info("Transaction ID", submitted_tx.id)
                print_hash_info("Platform Address", result.platform_address)
                print_hash_info("Policy ID", result.policy_id)
            else:
                raise click.ClickException("Transaction failed")

    except click.Abort:
        click.echo("Process aborted by the user.")
    except Exception as e:
        logger.error("Failed to process transaction", exc_info=e)
        raise click.ClickException(str(e)) from e


@token.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to platform configuration YAML",
)
@click.option(
    "--tx-file",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to signed transaction JSON file",
)
@async_command
async def submit_tx(
    config: Path,
    tx_file: Path,
) -> None:
    """Submit a fully signed platform auth token transaction."""
    try:
        (
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            orchestrator,
            _,
        ) = setup_platform_from_config(config, None)

        with tx_file.open() as f:
            data = json.load(f)

        if len(data.get("signed_by", [])) < data.get("threshold", 1):
            raise click.ClickException(
                "Transaction does not have enough signatures to meet threshold"
            )

        tx = Transaction.from_cbor(data["transaction"])

        submitted_tx, status = await orchestrator.handle_tx(tx, None, submit=True)

        if status == ProcessStatus.COMPLETED:
            print_status(
                "Platform authorization token",
                "Transaction submitted successfully",
                success=True,
            )
            print_hash_info("Transaction ID", submitted_tx.id)
            print_hash_info("Platform Address", data["platform_address"])
            print_hash_info("Policy ID", data["policy_id"])
        else:
            raise click.ClickException("Transaction submission failed")
    except click.Abort:
        click.echo("Process aborted by the user.")
    except Exception as e:
        logger.error("Failed to submit transaction", exc_info=e)
        raise click.ClickException(str(e)) from e


@token.command()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to platform configuration YAML",
)
@click.option(
    "--tx-file",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to transaction JSON file to sign",
)
@async_command
async def sign_tx(
    config: Path,
    tx_file: Path,
) -> None:
    """Sign a platform auth token transaction and update the file."""
    try:
        (
            _,
            payment_sk,
            payment_vk,
            _,
            _,
            _,
            _,
            orchestrator,
            _,
        ) = setup_platform_from_config(config, None)

        with tx_file.open() as f:
            data = json.load(f)

        signer_id = payment_vk.payload.hex()
        if signer_id in data.get("signed_by", []):
            raise click.ClickException("Transaction already signed by this key")

        if len(data.get("signed_by", [])) >= data.get("threshold", 1):
            raise click.ClickException(
                "Transaction already has required number of signatures"
            )

        transaction = Transaction.from_cbor(data["transaction"])

        signed_tx, status = await orchestrator.handle_tx(
            transaction, payment_sk, submit=False
        )

        if status == ProcessStatus.TRANSACTION_SIGNED:
            data["transaction"] = signed_tx.to_cbor_hex()
            data["signed_by"].append(signer_id)

            with tx_file.open("w") as f:
                json.dump(data, f)

            print_status("Transaction", "Signed successfully", success=True)
            print_hash_info("Signer", signer_id)
            print_hash_info(
                "Signatures", f"{len(data['signed_by'])}/{data['threshold']}"
            )

            if len(data["signed_by"]) >= data["threshold"]:
                print_hash_info(
                    "Reminder",
                    "Transaction has all required signatures and is ready for submission",
                )
        else:
            raise click.ClickException("Transaction signing failed")

    except click.Abort:
        click.echo("Process aborted by the user.")
    except Exception as e:
        logger.error("Failed to sign transaction", exc_info=e)
        raise click.ClickException(str(e)) from e
