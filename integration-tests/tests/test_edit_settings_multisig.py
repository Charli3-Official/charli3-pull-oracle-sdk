# """Test module for Oracle governance using multisig."""

# from collections.abc import Callable
# from copy import deepcopy
# from pathlib import Path
# from typing import Any
# from unittest.mock import patch

# import pytest
# from pycardano import (
#     Address,
#     PaymentExtendedSigningKey,
#     PaymentVerificationKey,
#     ScriptHash,
#     VerificationKeyHash,
# )

# from charli3_offchain_core.constants.status import ProcessStatus
# from charli3_offchain_core.models.oracle_datums import (
#     OracleSettingsDatum,
#     OracleSettingsVariant,
# )
# from charli3_offchain_core.oracle.utils.common import get_script_utxos
# from charli3_offchain_core.oracle.utils.state_checks import (
#     get_oracle_settings_by_policy_id,
# )

# from .governance import GovernanceBase
# from .test_utils import (
#     logger,
#     wait_for_indexing,
# )


# class TestMultisigGovernance(GovernanceBase):
#     """Test class for validating Oracle settings updates in the governance system.
#     The test uses multisig transactions.

#     This class inherits from GovernanceBase and implements test methods for
#     updating oracle settings. It verifies the transaction building, signing,
#     and submission processes, ensuring that modified settings are correctly
#     applied to the blockchain state.
#     """

#     def setup_method(self, method: Callable) -> None:
#         """Set up the test environment before each test method execution.

#         Initializes the test environment by calling the parent class setup
#         and performing any additional test-specific configuration.

#         Args:
#             method (Callable): The test method being run.
#         """
#         logger.info("Setting up TestMultisigGovernance environment")
#         super().setup_method(method)

#         # Set up platform keys directory - same as in TestMultisigPlatformAuth
#         self.platform_keys_dir = Path("./platform_keys")

#         # Load platform configuration and keys
#         self.load_platform_multisig_keys()

#         logger.info("TestMultisigGovernance setup completed")

#     def create_modified_settings(
#         self, current_datum: OracleSettingsDatum
#     ) -> OracleSettingsVariant:
#         """Create modified settings configuration for testing.

#         This method creates a modified version of the Oracle settings by
#         reducing the required signature threshold by 1, while ensuring
#         it does not exceed the total number of nodes.

#         Args:
#             current_datum (OracleSettingsDatum): The current Oracle settings datum

#         Returns:
#             OracleSettingsVariant: Modified Oracle settings for testing
#         """
#         # Decrease the required signature threshold value by 1
#         # Ensure it doesn't exceed the total number of nodes
#         new_threshold = min(
#             current_datum.required_node_signatures_count - 1,
#             len(current_datum.nodes),
#         )

#         logger.info(
#             f"Modifying required signatures from {current_datum.required_node_signatures_count} to {new_threshold}"
#         )

#         # Create a new settings configuration with updated values
#         # Only the required_node_signatures_count is being changed
#         new_settings = OracleSettingsDatum(
#             nodes=current_datum.nodes,
#             required_node_signatures_count=new_threshold,
#             fee_info=current_datum.fee_info,
#             aggregation_liveness_period=current_datum.aggregation_liveness_period,
#             time_uncertainty_aggregation=current_datum.time_uncertainty_aggregation,
#             time_uncertainty_platform=current_datum.time_uncertainty_platform,
#             iqr_fence_multiplier=current_datum.iqr_fence_multiplier,
#             median_divergency_factor=current_datum.median_divergency_factor,
#             utxo_size_safety_buffer=current_datum.utxo_size_safety_buffer,
#             pause_period_started_at=current_datum.pause_period_started_at,
#         )

#         return OracleSettingsVariant(new_settings)

#     def load_platform_multisig_keys(self) -> None:
#         """Load multisig keys from platform_keys dir if present."""
#         self.platform_keys_dir = Path("./platform_keys")

#         if not self.platform_keys_dir.exists():
#             logger.warning("Platform keys directory not found")
#             self.required_signers = 0
#             self.platform_keys = []
#             return

#         # Read threshold
#         try:
#             self.required_signers = int(
#                 (self.platform_keys_dir / "required_signatures").read_text()
#             )
#         except Exception:
#             logger.warning("Failed to read required_signatures, defaulting to 1")
#             self.required_signers = 1

#         self.platform_keys = []
#         for key_dir in sorted(self.platform_keys_dir.glob("platform_*")):
#             try:
#                 skey = PaymentExtendedSigningKey.load(key_dir / "administrator.skey")
#                 vkey = PaymentVerificationKey.load(key_dir / "administrator.vkey")
#                 vkh = VerificationKeyHash(
#                     bytes.fromhex((key_dir / "administrator.vkh").read_text().strip())
#                 )
#                 self.platform_keys.append((skey, vkey, vkh))
#                 logger.info(f"Loaded platform key: {vkh}")
#             except Exception as e:
#                 logger.warning(f"Could not load key from {key_dir}: {e}")

#     @pytest.mark.asyncio
#     @patch(
#         "charli3_offchain_core.oracle.governance.update_builder.manual_settings_menu"
#     )
#     async def test_edit_settings(self, mock_manual_settings_menu: Any) -> None:
#         logger.info("Starting Edit Settings transaction test")

#         # Load multisig keys if present
#         self.load_platform_multisig_keys()
#         use_multisig = len(self.platform_keys) >= self.required_signers

#         # Retrieve current settings
#         initial_utxos = await get_script_utxos(
#             Address.from_primitive(self.oracle_addresses.script_address),
#             self.tx_manager,
#         )
#         initial_oracle_datum, initial_settings_utxo = get_oracle_settings_by_policy_id(
#             initial_utxos,
#             ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
#         )
#         initial_sig_threshold = initial_oracle_datum.required_node_signatures_count

#         modified_settings_utxo = deepcopy(initial_settings_utxo)
#         modified_settings_variant = self.create_modified_settings(initial_oracle_datum)
#         modified_settings_utxo.output.datum = modified_settings_variant
#         modified_settings_utxo.output.datum_hash = None
#         target_signature_threshold = (
#             modified_settings_variant.datum.required_node_signatures_count
#         )

#         mock_manual_settings_menu.return_value = modified_settings_utxo

#         # Get platform UTxO and script
#         platform_auth_utxo = await self.platform_auth_finder.find_auth_utxo(
#             policy_id=self.management_config.tokens.platform_auth_policy,
#             platform_address=self.oracle_addresses.platform_address,
#         )
#         platform_script = await self.platform_auth_finder.get_platform_script(
#             str(self.oracle_addresses.platform_address)
#         )

#         update_result = await self.governance_orchestrator.update_oracle(
#             oracle_policy=self.management_config.tokens.oracle_policy,
#             oracle_config=self.oracle_configuration,
#             platform_utxo=platform_auth_utxo,
#             platform_script=platform_script,
#             change_address=self.oracle_addresses.admin_address,
#             signing_key=self.loaded_key.payment_sk,
#         )

#         assert (
#             update_result.status == ProcessStatus.TRANSACTION_BUILT
#         ), f"Update failed: {update_result.error}"
#         tx = update_result.transaction

#         logger.info("Signing transaction")
#         # Sign with admin
#         self.tx_manager.sign_tx(tx, self.loaded_key.payment_sk)

#         if use_multisig:
#             logger.info(f"Signing with multisig - threshold {self.required_signers}")
#             sig_count = 0
#             for skey, _, vkh in self.platform_keys:
#                 if sig_count >= self.required_signers:
#                     break
#                 self.tx_manager.sign_tx(tx, skey)
#                 logger.info(f"Added platform signature {sig_count + 1}: {vkh}")
#                 sig_count += 1
#         else:
#             logger.info("Multisig not configured, using single sig")

#         status, _ = await self.tx_manager.sign_and_submit(
#             tx, [], wait_confirmation=True
#         )
#         assert status == "confirmed", f"Transaction failed with status: {status}"

#         await wait_for_indexing(5)

#         # Verify settings were updated
#         updated_utxos = await get_script_utxos(
#             Address.from_primitive(self.oracle_addresses.script_address),
#             self.tx_manager,
#         )
#         updated_oracle_datum, _ = get_oracle_settings_by_policy_id(
#             updated_utxos,
#             ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
#         )

#         actual_updated_threshold = updated_oracle_datum.required_node_signatures_count
#         assert (
#             actual_updated_threshold == target_signature_threshold
#         ), f"Expected threshold {target_signature_threshold}, got {actual_updated_threshold}"
#         assert (
#             actual_updated_threshold < initial_sig_threshold
#         ), f"Threshold not reduced: {initial_sig_threshold} → {actual_updated_threshold}"

#         logger.info("Edit Settings test completed successfully with multisig support")
