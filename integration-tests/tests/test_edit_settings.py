"""Test module for editing Oracle settings.

This module tests the functionality of updating Oracle settings
through the governance system.
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
    """Test class for validating Oracle settings update in the governance system.

    This class inherits from GovernanceBase and implements test methods for
    updating oracle settings. It verifies the transaction building, signing,
    and submission processes.
    """

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment before each test method execution.

        Args:
            method (Callable): The test method being run.
        """
        logger.info("Setting up TestEditSettings environment")
        super().setup_method(method)
        logger.info("TestEditSettings setup completed")

    def load_core_setting_configuration(
        self, current_datum: OracleSettingsDatum
    ) -> OracleSettingsVariant:
        """Create modified settings configuration for testing.

        Args:
            current_datum: The current Oracle settings datum

        Returns:
            Modified Oracle settings for testing
        """
        # Decrease the required signature threshold value by 1
        new_threshold = min(
            current_datum.required_node_signatures_count - 1,
            current_datum.nodes.length,
        )

        # Create a new settings configuration with updated values
        new_settings = OracleSettingsDatum(
            nodes=current_datum.nodes,
            required_node_signatures_count=new_threshold,
            fee_info=current_datum.fee_info,
            aggregation_liveness_period=current_datum.aggregation_liveness_period,
            time_uncertainty_aggregation=current_datum.time_uncertainty_aggregation,
            time_uncertainty_platform=current_datum.time_uncertainty_platform,
            iqr_fence_multiplier=current_datum.iqr_fence_multiplier,
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
        1. Retrieves the current Oracle settings from UTxO
        2. Creates a modified version of the settings
        3. Mocks the manual settings menu to return the modified settings
        4. Builds and submits a transaction to update the settings
        5. Verifies the transaction was confirmed

        Args:
            mock_manual_settings_menu: Mock for the manual settings menu function
        """
        logger.info("Starting Edit Settings transaction")

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

        # Retrieve the current UTxOs
        utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        # Obtain the current Oracle configuration
        in_core_datum, settings_utxo = get_oracle_settings_by_policy_id(
            utxos,
            ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
        )

        logger.info(
            f"Current configuration in UTxO datum hash: {in_core_datum.to_cbor().hex()}"
        )

        # Create a modified configuration for testing
        modified_settings_utxo = deepcopy(settings_utxo)
        modified_settings_utxo.output.datum = self.load_core_setting_configuration(
            in_core_datum
        )
        modified_settings_utxo.output.datum_hash = None

        # Set up the mock to return the modified configuration
        mock_manual_settings_menu.return_value = modified_settings_utxo

        # Find platform auth NFT at the platform address
        platform_utxo = await self.platform_auth_finder.find_auth_utxo(
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

        # Sign and submit the transaction
        result = await self.governance_orchestrator.update_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            oracle_config=self.oracle_configuration,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=self.oracle_addresses.admin_address,
            signing_key=self.loaded_key.payment_sk,
        )

        assert (
            result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Update settings transaction failed: {result.error}"

        logger.info(
            f"Update settings transaction built successfully: {result.transaction.id}"
        )

        # Sign and submit the transaction
        logger.info("Signing and submitting transaction")
        transaction_status, _ = await self.tx_manager.sign_and_submit(
            result.transaction,
            [self.loaded_key.payment_sk],
            wait_confirmation=True,
        )

        logger.info(f"Transaction submission status: {transaction_status}")
        assert (
            transaction_status == "confirmed"
        ), f"Transaction failed with status: {transaction_status}"

        # Wait for UTxOs to be indexed
        await wait_for_indexing(20)

        # Verify that the configuration has been updated correctly
        new_utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        new_core_datum, _ = get_oracle_settings_by_policy_id(
            new_utxos,
            ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
        )

        # Check that the configuration has been updated as expected
        assert (
            new_core_datum.required_node_signatures_count
            == modified_settings_utxo.output.datum.datum.required_node_signatures_count
        ), "Settings were not updated correctly"

        logger.info("Edit Settings test completed successfully")
