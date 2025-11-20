# """Test module for adding Oracle Data Verification nodes to ODV settings.

# This module tests the functionality of adding node configurations to Oracle
# settings in a blockchain environment. It validates that nodes can be properly
# added through governance transactions and ensures the configuration is
# correctly updated with the expected number of nodes.
# """

# from collections.abc import Callable

# import pytest
# from pycardano import Address, ScriptHash

# from charli3_offchain_core.constants.status import ProcessStatus
# from charli3_offchain_core.oracle.utils.common import get_script_utxos
# from charli3_offchain_core.oracle.utils.state_checks import (
#     get_oracle_settings_by_policy_id,
# )

# from .governance import GovernanceBase
# from .test_utils import (
#     logger,
#     wait_for_indexing,
# )


# class TestAddNodes(GovernanceBase):
#     """Test class for validating node addition transactions in the governance system.

#     This class inherits from GovernanceBase and implements test methods for
#     adding oracle nodes to the system configuration. It verifies the
#     transaction building, signing, and submission processes, ensuring that
#     the correct number of nodes are added while maintaining appropriate
#     signature requirements.

#     Attributes:
#         NODES_TO_ADD_COUNT (int): Number of nodes to add during the test.
#     """

#     NODES_TO_ADD_COUNT = 1

#     def setup_method(self, method: Callable) -> None:
#         """Set up the test environment before each test method execution.

#         Initializes the test environment by calling the parent class setup
#         and performing any additional test-specific configuration.

#         Args:
#             method (Callable): The test method being run.
#         """
#         logger.info("Setting up TestAddNodes environment")
#         super().setup_method(method)
#         logger.info("TestAddNodes setup completed")

#     @pytest.mark.asyncio
#     async def test_add_nodes(self) -> None:
#         """Test the process of adding nodes to oracle settings.

#         This test method:
#         1. Verifies the initial node configuration matches blockchain state
#         2. Retrieves the platform authentication NFT
#         3. Gets the platform script and multisig configuration
#         4. Prepares new nodes to be added
#         5. Builds a transaction to add nodes
#         6. Signs and submits the transaction
#         7. Verifies the transaction was confirmed and nodes were added correctly

#         Raises:
#             AssertionError: If the transaction fails to build or confirm,
#                            or if the wrong number of nodes are added
#         """
#         logger.info("Starting Add nodes transaction")

#         # Log current configuration
#         logger.info(f"Using admin address: {self.oracle_addresses.admin_address}")
#         logger.info(f"Using platform address: {self.oracle_addresses.platform_address}")
#         logger.info(
#             f"Using oracle script address: {self.oracle_addresses.script_address}"
#         )
#         logger.info(
#             f"Using platform auth policy ID: {self.management_config.tokens.platform_auth_policy}"
#         )
#         logger.info(
#             f"Oracle Token ScriptHash: {self.management_config.tokens.oracle_policy}"
#         )

#         # Check the current allowed Nodes inside the configuration (BEFORE transaction)
#         initial_utxos = await get_script_utxos(
#             Address.from_primitive(self.oracle_addresses.script_address),
#             self.tx_manager,
#         )

#         initial_oracle_datum, _ = get_oracle_settings_by_policy_id(
#             initial_utxos,
#             ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
#         )

#         # Log current node count in the UTxO's datum
#         initial_node_count = len(initial_oracle_datum.nodes)
#         logger.info(f"Initial nodes in UTxO datum: {initial_node_count}")

#         # Find platform auth NFT at the platform address
#         platform_auth_utxo = await self.platform_auth_finder.find_auth_utxo(
#             policy_id=self.management_config.tokens.platform_auth_policy,
#             platform_address=self.oracle_addresses.platform_address,
#         )

#         # Get platform script
#         logger.info(
#             f"Getting platform script for address: {self.oracle_addresses.platform_address}"
#         )

#         platform_script = await self.platform_auth_finder.get_platform_script(
#             str(self.oracle_addresses.platform_address)
#         )

#         # Prepare nodes to add while maintaining the same signature threshold
#         nodes_to_add = self.prepare_nodes_for_addition(
#             self.management_config.nodes,
#             required_signatures=initial_node_count,
#             count_to_add=self.NODES_TO_ADD_COUNT,
#         )

#         # Verify correct number of nodes are being added
#         assert len(nodes_to_add.nodes) == self.NODES_TO_ADD_COUNT, (
#             f"Expected to add {self.NODES_TO_ADD_COUNT} nodes, "
#             f"but found {len(nodes_to_add.nodes)} nodes prepared for addition"
#         )

#         logger.info(f"Nodes to add: {nodes_to_add.nodes}")
#         logger.info(
#             f"Required signatures will remain: {nodes_to_add.required_signatures}"
#         )

#         # Build transaction to add nodes
#         addition_result = await self.governance_orchestrator.add_nodes_oracle(
#             oracle_policy=self.management_config.tokens.oracle_policy,
#             new_nodes_config=nodes_to_add,
#             platform_utxo=platform_auth_utxo,
#             platform_script=platform_script,
#             change_address=self.oracle_addresses.admin_address,
#             signing_key=self.loaded_key.payment_sk,
#             test_mode=True,
#         )

#         # Verify transaction was built successfully
#         assert (
#             addition_result.status == ProcessStatus.TRANSACTION_BUILT
#         ), f"Add Nodes transaction failed: {addition_result.error}"

#         logger.info(
#             f"Add Nodes transaction built successfully: {addition_result.transaction.id}"
#         )

#         # Sign and submit the transaction
#         logger.info("Signing and submitting transaction")
#         transaction_status, _ = await self.tx_manager.sign_and_submit(
#             addition_result.transaction,
#             [self.loaded_key.payment_sk],
#             wait_confirmation=True,
#         )

#         logger.info(f"Transaction submission status: {transaction_status}")
#         assert (
#             transaction_status == "confirmed"
#         ), f"Transaction failed with status: {transaction_status}"

#         # Wait for UTxOs to be indexed
#         await wait_for_indexing(5)

#         # Check the current allowed Nodes inside the configuration (AFTER transaction)
#         updated_utxos = await get_script_utxos(
#             Address.from_primitive(self.oracle_addresses.script_address),
#             self.tx_manager,
#         )

#         updated_oracle_datum, _ = get_oracle_settings_by_policy_id(
#             updated_utxos,
#             ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
#         )

#         # Log current node count in the UTxO's datum
#         final_node_count = len(updated_oracle_datum.nodes)
#         logger.info(f"Final nodes in UTxO datum after addition: {final_node_count}")

#         # Calculate expected node count after addition
#         expected_node_count = initial_node_count + self.NODES_TO_ADD_COUNT

#         # Assert that the node counts match after addition
#         assert expected_node_count == final_node_count, (
#             f"Node count mismatch after addition: Expected {expected_node_count} nodes "
#             f"(initial {initial_node_count} + {self.NODES_TO_ADD_COUNT} added), "
#             f"but the Settings UTxO contains {final_node_count} nodes"
#         )
