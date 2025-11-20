"""Test module for editing Oracle settings.

This module tests the functionality of updating Oracle settings through the
governance system. It verifies that settings can be properly modified and
that these modifications are correctly persisted on the blockchain.
"""

from collections.abc import Callable
from copy import deepcopy
from typing import Any
from unittest.mock import patch

import pytest
from pycardano import Address, ScriptHash

from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.models.oracle_datums import (
    OracleSettingsDatum,
    OracleSettingsVariant,
)
from charli3_offchain_core.oracle.utils.common import get_script_utxos
from charli3_offchain_core.oracle.utils.state_checks import (
    get_oracle_settings_by_policy_id,
)

from .governance import GovernanceBase
from .test_utils import (
    logger,
    wait_for_indexing,
)


class TestEditSettings(GovernanceBase):
    """Test class for validating Oracle settings updates in the governance system.

    This class inherits from GovernanceBase and implements test methods for
    updating oracle settings. It verifies the transaction building, signing,
    and submission processes, ensuring that modified settings are correctly
    applied to the blockchain state.
    """

    def setup_method(self, method: Callable) -> None:
        """Set up the test environment before each test method execution.

        Initializes the test environment by calling the parent class setup
        and performing any additional test-specific configuration.

        Args:
            method (Callable): The test method being run.
        """
        logger.info("Setting up TestEditSettings environment")
        super().setup_method(method)
        logger.info("TestEditSettings setup completed")

    def create_modified_settings(
        self, current_datum: OracleSettingsDatum
    ) -> OracleSettingsVariant:
        """Create modified settings configuration for testing.

        This method creates a modified version of the Oracle settings by
        reducing the required signature threshold by 1, while ensuring
        it does not exceed the total number of nodes.

        Args:
            current_datum (OracleSettingsDatum): The current Oracle settings datum

        Returns:
            OracleSettingsVariant: Modified Oracle settings for testing
        """
        # Decrease the required signature threshold value by 1
        # Ensure it doesn't exceed the total number of nodes
        new_threshold = min(
            current_datum.required_node_signatures_count - 1,
            len(current_datum.nodes),
        )

        logger.info(
            f"Modifying required signatures from {current_datum.required_node_signatures_count} to {new_threshold}"
        )

        # Create a new settings configuration with updated values
        # Only the required_node_signatures_count is being changed
        new_settings = OracleSettingsDatum(
            nodes=current_datum.nodes,
            required_node_signatures_count=new_threshold,
            fee_info=current_datum.fee_info,
            aggregation_liveness_period=current_datum.aggregation_liveness_period,
            time_uncertainty_aggregation=current_datum.time_uncertainty_aggregation,
            time_uncertainty_platform=current_datum.time_uncertainty_platform,
            iqr_fence_multiplier=current_datum.iqr_fence_multiplier,
            median_divergency_factor=current_datum.median_divergency_factor,
            utxo_size_safety_buffer=current_datum.utxo_size_safety_buffer,
            pause_period_started_at=current_datum.pause_period_started_at,
        )

        return OracleSettingsVariant(new_settings)

    @pytest.mark.asyncio
    @patch(
        "charli3_offchain_core.oracle.governance.update_builder.manual_settings_menu"
    )
    async def test_edit_settings(self, mock_manual_settings_menu: Any) -> None:
        """Test the process of updating Oracle settings.

        This test method:
        1. Retrieves the current Oracle settings from blockchain UTxOs
        2. Creates a modified version of the settings (reducing signature threshold)
        3. Mocks the manual settings menu to return the modified settings
        4. Builds and submits a transaction to update the settings
        5. Verifies the transaction was confirmed and settings were updated correctly

        Args:
            mock_manual_settings_menu: Mock for the manual settings menu function
                that returns our modified settings instead of showing an interactive menu

        Raises:
            AssertionError: If the transaction fails to build or confirm,
                           or if the settings were not updated correctly
        """
        logger.info("Starting Edit Settings transaction test")

        # Log current configuration
        logger.info(f"Using admin address: {self.oracle_addresses.admin_address}")
        logger.info(f"Using platform address: {self.oracle_addresses.platform_address}")
        logger.info(
            f"Using oracle script address: {self.oracle_addresses.script_address}"
        )
        logger.info(
            f"Using platform auth policy ID: {self.management_config.tokens.platform_auth_policy}"
        )
        logger.info(
            f"Oracle Token ScriptHash: {self.management_config.tokens.oracle_policy}"
        )

        # Retrieve the current UTxOs (BEFORE changes)
        initial_utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        # Obtain the current Oracle configuration
        initial_oracle_datum, initial_settings_utxo = get_oracle_settings_by_policy_id(
            initial_utxos,
            ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
        )

        initial_sig_threshold = initial_oracle_datum.required_node_signatures_count
        logger.info(f"Initial required signature threshold: {initial_sig_threshold}")
        logger.info(
            f"Current configuration in UTxO datum hash: {initial_oracle_datum.to_cbor().hex()}"
        )

        # Create a modified configuration for testing
        modified_settings_utxo = deepcopy(initial_settings_utxo)
        modified_settings_variant = self.create_modified_settings(initial_oracle_datum)
        modified_settings_utxo.output.datum = modified_settings_variant
        modified_settings_utxo.output.datum_hash = None

        # Extract the target threshold for later verification
        target_signature_threshold = (
            modified_settings_variant.datum.required_node_signatures_count
        )
        logger.info(
            f"Target signature threshold after modification: {target_signature_threshold}"
        )

        # Set up the mock to return the modified configuration
        mock_manual_settings_menu.return_value = modified_settings_utxo

        # Find platform auth NFT at the platform address
        platform_auth_utxo = await self.platform_auth_finder.find_auth_utxo(
            policy_id=self.management_config.tokens.platform_auth_policy,
            platform_address=self.oracle_addresses.platform_address,
        )

        # Get platform script
        logger.info(
            f"Getting platform script for address: {self.oracle_addresses.platform_address}"
        )

        platform_script = await self.platform_auth_finder.get_platform_script(
            str(self.oracle_addresses.platform_address)
        )

        # Build the transaction to update settings
        update_result = await self.governance_orchestrator.update_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            oracle_config=self.oracle_configuration,
            platform_utxo=platform_auth_utxo,
            platform_script=platform_script,
            change_address=self.oracle_addresses.admin_address,
            signing_key=self.loaded_key.payment_sk,
        )

        # Verify transaction was built successfully
        assert (
            update_result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Update settings transaction failed: {update_result.error}"

        logger.info(
            f"Update settings transaction built successfully: {update_result.transaction.id}"
        )

        # Sign and submit the transaction
        logger.info("Signing and submitting transaction")
        transaction_status, _ = await self.tx_manager.sign_and_submit(
            update_result.transaction,
            [self.loaded_key.payment_sk],
            wait_confirmation=True,
        )

        logger.info(f"Transaction submission status: {transaction_status}")
        assert (
            transaction_status == "confirmed"
        ), f"Transaction failed with status: {transaction_status}"

        # Wait for UTxOs to be indexed with additional time for settings updates
        await wait_for_indexing(5)

        # Verify that the configuration has been updated correctly (AFTER changes)
        updated_utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        updated_oracle_datum, _ = get_oracle_settings_by_policy_id(
            updated_utxos,
            ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
        )

        # Get the actual updated signature threshold
        actual_updated_threshold = updated_oracle_datum.required_node_signatures_count
        logger.info(f"Actual updated signature threshold: {actual_updated_threshold}")

        # Check that the signature threshold has been updated as expected
        assert actual_updated_threshold == target_signature_threshold, (
            f"Settings were not updated correctly. Expected threshold: {target_signature_threshold}, "
            f"but got: {actual_updated_threshold}"
        )

        # Additionally, verify the change from initial value
        assert actual_updated_threshold < initial_sig_threshold, (
            f"Signature threshold was not reduced. Initial: {initial_sig_threshold}, "
            f"Current: {actual_updated_threshold}"
        )

        logger.info("Edit Settings test completed successfully")
