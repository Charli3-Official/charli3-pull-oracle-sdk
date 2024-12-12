"""Update Settings."""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import click
from pycardano import (
    Redeemer,
    UTxO,
)

from charli3_offchain_core.cli.config.formatting import (
    CliColor,
    print_confirmation_message_prompt,
    print_information,
    print_status,
    print_title,
    print_validation_results,
)
from charli3_offchain_core.cli.config.update_settings import PlatformTxConfig
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.models.oracle_datums import (
    OracleSettingsDatum,
    OracleSettingsVariant,
)
from charli3_offchain_core.models.oracle_redeemers import UpdateSettings
from charli3_offchain_core.oracle.transactions.base import (
    BaseTransaction,
    MultisigResult,
    TransactionResult,
)

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


class SettingField(Enum):
    AGGREGATION_LIVENESS = (
        "Aggregation Liveness Period",
        "must be greater than time uncertainty",
    )
    TIME_UNCERTAINTY = ("Time Absolute Uncertainty", "must be positive")
    IQR_MULTIPLIER = ("IQR Fence Multiplier", "must be greater than 100")
    THRESHOLD = (
        "Required Node Signatures Count",
        "must be positive and not greater than number of deployed parties",
    )
    SAFETY_BUFFER = ("UTxO Size Safety Buffer", "must not be negative")

    def __init__(self, display_name: str, validation_message: str) -> None:
        self.display_name = display_name
        self.validation_message = validation_message


@dataclass
class ValidationResult:
    is_valid: bool
    message: str | None = None
    previous_value: Any | None = None
    new_value: Any | None = None
    has_changed: bool = False


@dataclass
class SettingsValidator:
    def __init__(self) -> None:
        self._validation_results = {}
        self._has_changes = False

    def validate_setting(
        self, field: SettingField, current_value: Any, new_value: Any, condition: bool
    ) -> None:
        has_changed = current_value != new_value
        if has_changed:
            self._has_changes = True

        self._validation_results[field] = ValidationResult(
            is_valid=condition,
            message=(
                f"{field.display_name} {field.validation_message}"
                if not condition
                else None
            ),
            previous_value=current_value,
            new_value=new_value,
            has_changed=has_changed,
        )

    @property
    def is_valid(self) -> bool:
        return all(result.is_valid for result in self._validation_results.values())

    @property
    def has_changes(self) -> bool:
        return self._has_changes

    @property
    def results(self) -> dict[SettingField, ValidationResult]:
        return self._validation_results


class UpdateCoreSettings(BaseTransaction):
    """Update Core Setting Transaction Logic"""

    REDEEMER = Redeemer(UpdateSettings())

    async def process_update(
        self, modified_core_utxo: UTxO, output: Path | None
    ) -> TransactionResult | MultisigResult:
        """Process the settings update transaction."""
        # Fetch required UTxOs and scripts
        platform_utxo, platform_script = await self.fetch_auth_utxo_and_script()
        contract_reference_utxo = await self.fetch_reference_script_utxo()

        # Build transaction
        self._update_status(
            ProcessStatus.BUILDING_TRANSACTION, "Building transaction..."
        )
        tx_manager = await self._build_update_transaction(
            modified_core_utxo, platform_utxo, platform_script, contract_reference_utxo
        )

        # Handle signing based on requirements
        if await self.required_single_signature(platform_script):
            return await self._process_single_signature(tx_manager)
        else:
            return await self._process_multisig(tx_manager, output)

    async def manual_settings_menu(self, deployed_core_utxo: UTxO) -> UTxO:  # noqa
        """Interactive menu for manual settings updates."""
        deployed_core_settings = deployed_core_utxo.output.datum
        current_settings = {
            SettingOption.AGGREGATION_LIVENESS: deployed_core_settings.datum.aggregation_liveness_period,
            SettingOption.TIME_UNCERTAINTY: deployed_core_settings.datum.time_absolute_uncertainty,
            SettingOption.IQR_MULTIPLIER: deployed_core_settings.datum.iqr_fence_multiplier,
            SettingOption.THRESHOLD: deployed_core_settings.datum.required_node_signatures_count,
            SettingOption.UTXO_BUFFER: deployed_core_settings.datum.utxo_size_safety_buffer,
        }

        while True:
            # Print current settings
            print_title("Current Settings")
            for option in SettingOption:
                if option != SettingOption.DONE:
                    print_status(
                        option.label, str(current_settings[option]), success=True
                    )
            print_information(
                "Note: Only the options presented here can be changed with this transaction"
            )

            # Display menu with numbers
            click.echo(
                click.style("\nAvailable options:", fg=CliColor.WARNING, bold=True)
            )
            for option in SettingOption:
                click.echo(f"{option.id}. {option.label}")

            choice = click.prompt(
                click.style("\nSelect option", fg=CliColor.WARNING, bold=True),
                type=click.Choice([opt.id for opt in SettingOption]),
            )

            # Convert numeric choice back to enum
            selected_option = next(opt for opt in SettingOption if opt.id == choice)

            if selected_option == SettingOption.DONE:
                try:
                    # Validate timing parameters
                    if not current_settings[SettingOption.TIME_UNCERTAINTY] > 0:
                        raise ValueError("Time uncertainty must be positive")

                    if (
                        not current_settings[SettingOption.AGGREGATION_LIVENESS]
                        > current_settings[SettingOption.TIME_UNCERTAINTY]
                    ):
                        raise ValueError(
                            "Aggregation liveness must be greater than time uncertainty"
                        )

                    if not current_settings[SettingOption.IQR_MULTIPLIER] > 100:
                        raise ValueError("IQR multiplier must be greater than 100")

                    # Validate threshold
                    if not current_settings[SettingOption.THRESHOLD] > 0:
                        raise ValueError("Threshold must be positive")

                    if (
                        not current_settings[SettingOption.THRESHOLD]
                        <= deployed_core_settings.datum.nodes.length
                    ):
                        raise ValueError(
                            "Threshold cannot be greater than number of deployed parties"
                        )

                    if print_confirmation_message_prompt(
                        "Do you want to proceed with these changes?"
                    ):
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
                        return deployed_core_utxo
                except ValueError as e:
                    logger.error(str(e))
                    continue

            # Get and validate new value
            new_value = await self.get_setting_value(
                selected_option,
                current_settings[selected_option],
                deployed_core_settings,
            )

            # Update settings
            current_settings[selected_option] = new_value

    async def get_setting_value(  # noqa
        self, option: SettingOption, current_value: int, deployed_settings: Any
    ) -> int:
        """Prompt user for new setting value with validation."""
        while True:
            try:
                prompt_text = (
                    f"Enter new value for {option.label} (current: {current_value})"
                )
                if option == SettingOption.THRESHOLD:
                    prompt_text += f" (max: {deployed_settings.datum.nodes.length})"
                elif option == SettingOption.TIME_UNCERTAINTY:
                    prompt_text += " (must be positive)"
                elif option == SettingOption.UTXO_BUFFER:
                    prompt_text += " (must not be negative)"
                elif option == SettingOption.AGGREGATION_LIVENESS:
                    prompt_text += f" (must be greater than time uncertainty: {deployed_settings.datum.time_absolute_uncertainty})"
                elif option == SettingOption.IQR_MULTIPLIER:
                    prompt_text += " (must be greater than 100)"

                new_value = click.prompt(
                    click.style(prompt_text, fg=CliColor.WARNING, bold=True), type=int
                )

                # Immediate validation for individual fields
                if option == SettingOption.TIME_UNCERTAINTY and new_value <= 0:
                    raise ValueError("Time uncertainty must be positive")
                elif option == SettingOption.UTXO_BUFFER and new_value < 0:
                    raise ValueError("UTxO safety buffer must not be negative")
                elif option == SettingOption.IQR_MULTIPLIER and new_value <= 100:
                    raise ValueError("IQR multiplier must be greater than 100")
                elif option == SettingOption.THRESHOLD:
                    if new_value <= 0:
                        raise ValueError("Threshold must be positive")
                    if new_value > deployed_settings.datum.nodes.length:
                        raise ValueError(
                            "Threshold cannot be greater than number of deployed parties"
                        )

                return new_value
            except ValueError as e:
                logger.error(str(e))

    async def allowed_datum_changes_from_file(self, utxo_to_change: UTxO) -> UTxO:
        """
        Validates and creates a new OracleSettingsVariant with updated settings.
        """

        validator = await self._validate_new_settings(
            utxo_to_change.output.datum.datum, self.tx_config
        )

        if not validator.has_changes:
            print_information("No changes detected in configuration file")
            return utxo_to_change

        # Show changes and get confirmation
        if not await self._show_and_confirm_changes(validator):
            return utxo_to_change

        if not validator.is_valid:
            raise ValueError(
                "Validation failed. Please check the error messages above."
            )

        return self._modified_core_utxo(utxo_to_change)

    async def _validate_new_settings(
        self, current_settings: OracleSettingsDatum, tx_config: PlatformTxConfig
    ) -> SettingsValidator:
        validator = SettingsValidator()

        # Validate time uncertainty
        validator.validate_setting(
            SettingField.TIME_UNCERTAINTY,
            current_settings.time_absolute_uncertainty,
            tx_config.timing.time_uncertainty,
            tx_config.timing.time_uncertainty > 0,
        )

        # Validate aggregation liveness
        validator.validate_setting(
            SettingField.AGGREGATION_LIVENESS,
            current_settings.aggregation_liveness_period,
            tx_config.timing.aggregation_liveness,
            tx_config.timing.aggregation_liveness > tx_config.timing.time_uncertainty,
        )

        # Validate IQR multiplier
        validator.validate_setting(
            SettingField.IQR_MULTIPLIER,
            current_settings.iqr_fence_multiplier,
            tx_config.timing.iqr_multiplier,
            tx_config.timing.iqr_multiplier > 100,
        )

        # Validate threshold
        validator.validate_setting(
            SettingField.THRESHOLD,
            current_settings.required_node_signatures_count,
            tx_config.multi_sig.threshold,
            tx_config.multi_sig.threshold > 0
            and tx_config.multi_sig.threshold <= current_settings.nodes.length,
        )

        # Validate safety buffer
        validator.validate_setting(
            SettingField.SAFETY_BUFFER,
            current_settings.utxo_size_safety_buffer,
            tx_config.timing.utxo_size_safety_buffer,
            tx_config.timing.utxo_size_safety_buffer >= 0,
        )

        return validator

    def _modified_core_utxo(self, utxo_to_change: UTxO) -> UTxO:
        """Create modified UTxO with new settings."""
        modified_datum = OracleSettingsVariant(
            OracleSettingsDatum(
                nodes=utxo_to_change.output.datum.datum.nodes,
                required_node_signatures_count=self.tx_config.multi_sig.threshold,
                fee_info=utxo_to_change.output.datum.datum.fee_info,
                aggregation_liveness_period=self.tx_config.timing.aggregation_liveness,
                time_absolute_uncertainty=self.tx_config.timing.time_uncertainty,
                iqr_fence_multiplier=self.tx_config.timing.iqr_multiplier,
                utxo_size_safety_buffer=self.tx_config.timing.utxo_size_safety_buffer,
                closing_period_started_at=utxo_to_change.output.datum.datum.closing_period_started_at,
            )
        )
        utxo_to_change.output.datum = modified_datum
        return utxo_to_change

    async def _show_and_confirm_changes(self, validator: SettingsValidator) -> bool:
        if not validator.has_changes:
            return False

        # Print validation results only if we have changes
        print_validation_results(validator)

        # Ask for confirmation
        return print_confirmation_message_prompt(
            "Do you want to proceed with the changes above?"
        )
