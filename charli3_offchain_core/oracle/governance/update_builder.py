"""Close oracle transaction builder."""

import logging
from enum import Enum
from typing import Any

import click
from pycardano import (
    Address,
    ExtendedSigningKey,
    NativeScript,
    PaymentSigningKey,
    Redeemer,
    UTxO,
    VerificationKeyHash,
)

from charli3_offchain_core.cli.config.formatting import (
    CliColor,
    print_confirmation_message_prompt,
    print_header,
    print_information,
    print_progress,
    print_status,
)
from charli3_offchain_core.models.oracle_datums import (
    OracleSettingsDatum,
    OracleSettingsVariant,
)
from charli3_offchain_core.models.oracle_redeemers import (
    UpdateSettings,
)
from charli3_offchain_core.oracle.exceptions import (
    SettingsValidationError,
    UpdateCancelled,
    UpdatingError,
)
from charli3_offchain_core.oracle.utils.common import get_reference_script_utxo
from charli3_offchain_core.oracle.utils.state_checks import (
    get_oracle_settings_by_policy_id,
)

from .base import BaseBuilder, GovernanceTxResult

logger = logging.getLogger(__name__)


class SettingOption(Enum):
    AGGREGATION_LIVENESS = ("1", "Aggregation Liveness Period")
    TIME_UNCERTAINTY = ("2", "Time Absolute Uncertainty")
    IQR_MULTIPLIER = ("3", "IQR Fence Multiplier")
    UTXO_BUFFER = ("4", "UTxO size safety buffer")
    THRESHOLD = ("5", "Required Node Signature Count")
    DONE = ("6", "Done")

    def __init__(self, id: str, label: str) -> None:
        self.id = id
        self.label = label


class UpdateBuilder(BaseBuilder):
    REDEEMER = Redeemer(UpdateSettings())
    FEE_BUFFER = 10_000

    async def build_tx(
        self,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        policy_hash: Any,
        utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> GovernanceTxResult:
        """Build the update transaction."""
        try:
            _, settings_utxo = get_oracle_settings_by_policy_id(utxos, policy_hash)
            script_utxo = get_reference_script_utxo(utxos)

            if not script_utxo:
                raise ValueError("Reference script UTxO not found")

            try:
                modified_settings_utxo = await manual_settings_menu(settings_utxo)
            except (UpdateCancelled, click.Abort):
                return GovernanceTxResult()

            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (settings_utxo, self.REDEEMER, script_utxo),
                    (platform_utxo, None, platform_script),
                ],
                script_outputs=[modified_settings_utxo.output, platform_utxo.output],
                fee_buffer=self.FEE_BUFFER,
                change_address=change_address,
                signing_key=signing_key,
                required_signers=required_signers,
            )
            return GovernanceTxResult(
                transaction=tx, settings_utxo=modified_settings_utxo
            )
        except SettingsValidationError as e:
            raise UpdatingError(f"Failed to build close transaction: {e!s}") from e


async def get_setting_value(
    option: SettingOption,
    current_value: int,
    deployed_settings: Any,
    current_settings: dict,
) -> int:
    """Prompt user for new setting value with validation."""
    while True:
        try:
            # Build help text based on option
            help_text = []
            if option == SettingOption.THRESHOLD:
                help_text.append(f"max: {deployed_settings.datum.nodes.length}")
            elif option == SettingOption.TIME_UNCERTAINTY:
                help_text.append("must be positive")
            elif option == SettingOption.UTXO_BUFFER:
                help_text.append("must not be negative")
            elif option == SettingOption.AGGREGATION_LIVENESS:
                current_time_uncertainty = current_settings[
                    SettingOption.TIME_UNCERTAINTY
                ]
                help_text.append(
                    f"must be greater than time uncertainty: {current_time_uncertainty}"
                )
            elif option == SettingOption.IQR_MULTIPLIER:
                help_text.append("must be greater than 100")

            prompt_text = (
                f"Enter new value for {option.label} (current: {current_value})"
            )
            if help_text:
                prompt_text += f" ({', '.join(help_text)})"

            new_value = click.prompt(
                click.style(prompt_text, fg=CliColor.WARNING, bold=True), type=int
            )

            validate_setting(option, new_value, current_settings, deployed_settings)
            return new_value
        except SettingsValidationError as e:
            print_status("Validation Error", str(e), success=False)
            continue


async def manual_settings_menu(deployed_core_utxo: UTxO) -> UTxO:  # noqa
    """Interactive menu for manual settings updates."""
    deployed_core_settings = deployed_core_utxo.output.datum
    initial_settings = {
        SettingOption.AGGREGATION_LIVENESS: deployed_core_settings.datum.aggregation_liveness_period,
        SettingOption.TIME_UNCERTAINTY: deployed_core_settings.datum.time_absolute_uncertainty,
        SettingOption.IQR_MULTIPLIER: deployed_core_settings.datum.iqr_fence_multiplier,
        SettingOption.THRESHOLD: deployed_core_settings.datum.required_node_signatures_count,
        SettingOption.UTXO_BUFFER: deployed_core_settings.datum.utxo_size_safety_buffer,
    }
    current_settings = initial_settings.copy()
    invalid_settings = set()

    while True:
        # Print current settings
        print_header("Current Settings")
        for option in SettingOption:
            if option != SettingOption.DONE:
                is_valid = option not in invalid_settings
                print_status(
                    option.label, str(current_settings[option]), success=is_valid
                )

        # Show validation errors if any exist
        if invalid_settings:
            print_header("Validation Errors")
            for option in invalid_settings:
                try:
                    validate_setting(
                        option,
                        current_settings[option],
                        current_settings,
                        deployed_core_settings,
                    )
                except SettingsValidationError as e:
                    print_status(option.label, str(e), success=False)

        print_information(
            "Note: Only the options presented here can be changed with this transaction"
        )

        # Display menu
        print_header("Available Options")
        for option in SettingOption:
            click.echo(f"{option.id}. {option.label}")

        # Get user choice
        choices = [opt.id for opt in SettingOption] + ["q"]
        choice = click.prompt(
            click.style("\nSelect option", fg=CliColor.WARNING, bold=True),
            type=click.Choice(choices),
        )
        if choice == "q":
            if print_confirmation_message_prompt(
                "Are you sure you want to quit without saving?"
            ):
                raise UpdateCancelled()
            continue

        selected_option = next(opt for opt in SettingOption if opt.id == choice)

        if selected_option == SettingOption.DONE:
            if current_settings == initial_settings:
                print_status("Update Status", "No changes detected", success=True)
                raise UpdateCancelled()
            # Validate all settings
            invalid_settings.clear()
            try:
                for option in SettingOption:
                    if option != SettingOption.DONE:
                        validate_setting(
                            option,
                            current_settings[option],
                            current_settings,
                            deployed_core_settings,
                        )

                if invalid_settings:
                    print_header("Please fix validation errors before proceeding")
                    continue

                if print_confirmation_message_prompt(
                    "Do you want to proceed with these changes?"
                ):
                    print_progress("Building new settings datum")
                    new_datum = OracleSettingsVariant(
                        OracleSettingsDatum(
                            nodes=deployed_core_settings.datum.nodes,
                            required_node_signatures_count=current_settings[
                                SettingOption.THRESHOLD
                            ],
                            fee_info=deployed_core_settings.datum.fee_info,
                            aggregation_liveness_period=current_settings[
                                SettingOption.AGGREGATION_LIVENESS
                            ],
                            time_absolute_uncertainty=current_settings[
                                SettingOption.TIME_UNCERTAINTY
                            ],
                            iqr_fence_multiplier=current_settings[
                                SettingOption.IQR_MULTIPLIER
                            ],
                            utxo_size_safety_buffer=current_settings[
                                SettingOption.UTXO_BUFFER
                            ],
                            closing_period_started_at=deployed_core_settings.datum.closing_period_started_at,
                        )
                    )
                    deployed_core_utxo.output.datum = new_datum
                    deployed_core_utxo.output.datum_hash = None
                    return deployed_core_utxo
                else:
                    continue
            except SettingsValidationError as e:
                print_status("Validation Error", str(e), success=False)
                continue

        try:
            new_value = await get_setting_value(
                selected_option,
                current_settings[selected_option],
                deployed_core_settings,
                current_settings,
            )
            current_settings[selected_option] = new_value
            invalid_settings.discard(
                selected_option
            )  # Clear validation error if value is valid
        except SettingsValidationError as e:
            invalid_settings.add(selected_option)
            print_status("Validation Error", str(e), success=False)


def validate_setting(
    option: SettingOption, value: int, current_settings: dict, deployed_settings: Any
) -> None:
    """Validate a setting value."""
    if value <= 0 and option in [
        SettingOption.TIME_UNCERTAINTY,
        SettingOption.THRESHOLD,
    ]:
        raise SettingsValidationError(
            "Time uncertainty and Node signature count must be positive"
        )

    if option == SettingOption.UTXO_BUFFER and value < 0:
        raise SettingsValidationError("UTxO size safety buffer must not be negative")

    if option == SettingOption.IQR_MULTIPLIER and value <= 100:
        raise SettingsValidationError("IQR fence multiplier must be greater than 100")

    if (
        option == SettingOption.THRESHOLD
        and value > deployed_settings.datum.nodes.length
    ):
        raise SettingsValidationError(
            f"Threshold cannot be greater than number of deployed parties ({deployed_settings.datum.nodes.length})"
        )

    if option == SettingOption.AGGREGATION_LIVENESS:
        time_uncertainty = current_settings[SettingOption.TIME_UNCERTAINTY]
        if value <= time_uncertainty:
            raise SettingsValidationError(
                f"Aggregation liveness ({value}) must be greater than time uncertainty ({time_uncertainty})"
            )
