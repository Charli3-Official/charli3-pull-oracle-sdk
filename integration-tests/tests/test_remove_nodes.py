"""Test module for removing Oracle Data Verification nodes from ODV settings.

This module tests the functionality of removing node configurations from Oracle
settings in a blockchain environment. It validates that nodes can be properly
removed through governance transactions and ensures the configuration is
correctly updated with the expected number of nodes and signature requirements.
"""

from collections.abc import Callable

import pytest
from pycardano import Address, ScriptHash

from charli3_offchain_core.cli.config.nodes import NodesConfig
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.oracle.utils.common import get_script_utxos
from charli3_offchain_core.oracle.utils.state_checks import (
    get_oracle_settings_by_policy_id,
)

from .governance import GovernanceBase
from .test_utils import (
    logger,
    wait_for_indexing,
)


class TestRemoveNodes(GovernanceBase):
    """Test class for validating node removal transactions in the governance system.

    This class inherits from GovernanceBase and implements test methods for
    removing oracle nodes from the system configuration. It verifies the
    transaction building, signing, and submission processes, ensuring that
    the correct number of nodes are removed and signature thresholds are
    properly adjusted.

    Attributes:
        NODES_TO_REMOVE_COUNT (int): Number of nodes to remove during the test.
    """

    NODES_TO_REMOVE_COUNT = 2

    def setup_method(self, method: Callable) -> None:
        """Set up the test environment before each test method execution.

        Initializes the test environment by calling the parent class setup
        and performing any additional test-specific configuration.

        Args:
            method (Callable): The test method being run.
        """
        logger.info("Setting up TestRemoveNodes environment")
        super().setup_method(method)
        logger.info("TestRemoveNodes setup completed")

    @pytest.mark.asyncio
    async def test_remove_nodes(self) -> None:
        """Test the process of removing nodes from oracle settings.

        This test method:
        1. Retrieves the platform authentication NFT
        2. Gets the platform script and multisig configuration
        3. Identifies the nodes to remove and calculates new signature requirements
        4. Builds a transaction to remove nodes
        5. Signs and submits the transaction
        6. Verifies the transaction was confirmed and the correct nodes were removed

        Raises:
            AssertionError: If the transaction fails to build or confirm,
                           or if the wrong number of nodes are removed
        """
        logger.info("Starting Remove nodes transaction")

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

        # Before transaction: Get current node count from blockchain
        old_utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        old_in_core_datum, _ = get_oracle_settings_by_policy_id(
            old_utxos,
            ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
        )

        logger.info(f"Initial node count: {old_in_core_datum.nodes.length}")

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

        # Prepare nodes for removal
        (adjusted_signature_threshold, nodes_to_remove) = (
            self.prepare_nodes_for_removal(
                nodes_config=self.management_config.nodes,
                count_to_remove=self.NODES_TO_REMOVE_COUNT,
            )
        )

        logger.info(f"Nodes to remove: {nodes_to_remove}")
        logger.info(f"New required signatures: {adjusted_signature_threshold}")

        # Build transaction to remove nodes
        removal_result = await self.governance_orchestrator.del_nodes_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            new_nodes_config=NodesConfig(adjusted_signature_threshold, nodes_to_remove),
            platform_utxo=platform_auth_utxo,
            platform_script=platform_script,
            change_address=self.oracle_addresses.admin_address,
            tokens=self.management_config.tokens,
            reward_dismissing_period_length=self.oracle_configuration.reward_dismissing_period_length,
            network=self.management_config.network.network,
            reward_issuer_addr=self.escrow_config.reward_issuer_addr,
            escrow_address=self.escrow_config.reference_script_addr,
            signing_key=self.loaded_key.payment_sk,
            test_mode=True,
        )

        # Verify transaction was built successfully
        assert (
            removal_result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Remove Nodes transaction failed: {removal_result.error}"

        logger.info(
            f"Remove Nodes transaction built successfully: {removal_result.transaction.id}"
        )

        # Sign and submit the transaction
        logger.info("Signing and submitting transaction")
        transaction_status, _ = await self.tx_manager.sign_and_submit(
            removal_result.transaction,
            [self.loaded_key.payment_sk],
            wait_confirmation=True,
        )

        logger.info(f"Transaction submission status: {transaction_status}")
        assert (
            transaction_status == "confirmed"
        ), f"Transaction failed with status: {transaction_status}"

        # Wait for UTxOs to be indexed
        await wait_for_indexing(5)

        # After transaction: Verify changes took effect
        utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        new_in_core_datum, _ = get_oracle_settings_by_policy_id(
            utxos,
            ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
        )

        # Log current node count in the UTxO's datum
        logger.info(f"Current nodes in UTxO datum: {new_in_core_datum.nodes.length}")

        # Compare node count between UTxO datum and new nodes
        expected_node_count = (
            len(self.management_config.nodes.nodes) - self.NODES_TO_REMOVE_COUNT
        )
        new_node_count = new_in_core_datum.nodes.length

        # Assert that the node counts match
        assert expected_node_count == new_node_count, (
            f"Node count mismatch: Previous transaction {old_in_core_datum.nodes.length} nodes, "
            f"but the Settings UTxO contains {new_node_count} nodes"
        )
