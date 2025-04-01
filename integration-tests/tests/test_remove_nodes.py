"""Test module for removing Oracle Data Verification nodes from ODV settings.

This module tests the functionality of removing node configurations from an Oracle
settings in a blockchain environment. It validates that nodes can be properly
removed through governance transactions.
"""

from collections.abc import Callable

import pytest

from charli3_offchain_core.constants.status import ProcessStatus

from .governance import GovernanceBase
from .test_utils import (
    logger,
    wait_for_indexing,
)


class TestRemoveNodes(GovernanceBase):
    """Test class for validating node removal transactions in the governance system.

    This class inherits from GovernanceBase and implements test methods for
    removing oracle nodes from the system configuration. It verifies the
    transaction building, signing, and submission processes.
    """

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment before each test method execution.

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
        3. Builds a transaction to remove nodes
        4. Signs and submits the transaction
        5. Verifies the transaction was confirmed

        Raises:
            AssertionError: If the transaction fails to build or confirm
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

        # Since the intended purpose is to remove 1 node
        nodes_to_remove = self.load_nodes_to_remove(
            self.management_config.nodes, required_signatures=1, slice_count=8
        )

        logger.info(f"Nodes to remove: {nodes_to_remove}")

        result = await self.governance_orchestrator.del_nodes_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            new_nodes_config=nodes_to_remove,
            platform_utxo=platform_utxo,
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
        assert (
            result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Remove Nodes transaction failed: {result.error}"

        logger.info(
            f"Remove Nodes transaction built successfully: {result.transaction.id}"
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
        await wait_for_indexing(5)
