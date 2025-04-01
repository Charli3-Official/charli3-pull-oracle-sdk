"""Test module for adding Oracle Data Verification nodes to ODV settings.

This module tests the functionality of adding node configurations to an Oracle
settings in a blockchain environment. It validates that nodes can be properly
added through governance transactions.
"""

from collections.abc import Callable

import pytest
from pycardano import Address, ScriptHash

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


class TestAddNodes(GovernanceBase):
    """Test class for validating node addition transactions in the governance system.

    This class inherits from GovernanceBase and implements test methods for
    adding oracle nodes to the system configuration. It verifies the
    transaction building, signing, and submission processes.
    """

    NEW_NODES = 1

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment before each test method execution.

        Args:
            method (Callable): The test method being run.
        """
        logger.info("Setting up TestAddNodes environment")
        super().setup_method(method)
        logger.info("TestAddNodes setup completed")

    @pytest.mark.asyncio
    async def test_add_nodes(self) -> None:
        """Test the process of adding nodes to oracle settings.

        This test method:
        1. Retrieves the platform authentication NFT
        2. Gets the platform script and multisig configuration
        3. Builds a transaction to add nodes
        4. Signs and submits the transaction
        5. Verifies the transaction was confirmed

        Raises:
            AssertionError: If the transaction fails to build or confirm
        """
        logger.info("Starting Add nodes transaction")
        # Log current configuratio
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

        # Check the current allowed Nodes inside the configuration
        utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        in_core_datum, _ = get_oracle_settings_by_policy_id(
            utxos,
            ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
        )

        # Log current node count in the UTxO's datum
        logger.info(f"Current nodes in UTxO datum: {in_core_datum.nodes.length}")

        # Compare node count between configuration file and UTxO datum
        config_node_count = len(self.management_config.nodes.nodes)
        utxo_node_count = in_core_datum.nodes.length

        # Assert that the node counts match
        assert config_node_count == utxo_node_count, (
            f"Node count mismatch: Configuration file has {config_node_count} nodes, "
            f"but the Settings UTxO contains {utxo_node_count} nodes"
        )

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

        # Since the intended purpose is to add 1 node,
        # and keep the same number of required signatures
        nodes_to_add = self.load_nodes_to_add(
            self.management_config.nodes,
            required_signatures=self.management_config.nodes.required_signatures,
            attach_count=self.NEW_NODES,
        )

        logger.info(f"Nodes to add: {nodes_to_add}")

        result = await self.governance_orchestrator.add_nodes_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            new_nodes_config=nodes_to_add,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=self.oracle_addresses.admin_address,
            signing_key=self.loaded_key.payment_sk,
            test_mode=True,
        )
        assert (
            result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Add Nodes transaction failed: {result.error}"

        logger.info(
            f"Add Nodes transaction built successfully: {result.transaction.id}"
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

        # Check the current allowed Nodes inside the configuration
        utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        in_core_datum, _ = get_oracle_settings_by_policy_id(
            utxos,
            ScriptHash(bytes.fromhex(self.management_config.tokens.oracle_policy)),
        )

        # Log current node count in the UTxO's datum
        logger.info(f"Current nodes in UTxO datum: {in_core_datum.nodes.length}")

        # Compare node count between UTxO datum and new nodes
        expected_node_count = len(self.management_config.nodes.nodes) + self.NEW_NODES
        utxo_node_count = in_core_datum.nodes.length

        # Assert that the node counts match
        assert expected_node_count == utxo_node_count, (
            f"Node count mismatch: Configuration file has {config_node_count} nodes, "
            f"but the Settings UTxO contains {utxo_node_count} nodes"
        )
