"""Test module for scaling down Oracle Data Verification UTxOs.

This module tests the functionality of decreasing the number of RewardAccount
and AggState UTxOs in the Oracle. It validates that the scaling down operation
correctly removes the specified number of UTxOs independently from the blockchain
environment.
"""

from collections.abc import Callable

import pytest
from pycardano import Address

from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.oracle.utils.common import get_script_utxos

from .governance import GovernanceBase
from .test_utils import (
    logger,
    wait_for_indexing,
)


class TestScaleDown(GovernanceBase):
    """Test class for validating Oracle scale-down operations in the governance system.

    This class inherits from GovernanceBase and implements test methods for
    decreasing the number of RewardAccount and AggState UTxOs in the Oracle system.
    It verifies the transaction building, signing, and submission processes, and
    ensures that the expected number of UTxOs are removed from the blockchain.

    Attributes:
        REWARD_ACCOUNTS_TO_REMOVE (int): Number of RewardAccount UTxOs to remove during the test.
        AGGSTATES_TO_REMOVE (int): Number of AggState UTxOs to remove during the test.
    """

    REWARD_ACCOUNTS_TO_REMOVE = 1
    AGGSTATES_TO_REMOVE = 1

    def setup_method(self, method: Callable) -> None:
        """Set up the test environment before each test method execution.

        Initializes the test environment by calling the parent class setup
        and performing any additional test-specific configuration.

        Args:
            method (Callable): The test method being run.
        """
        logger.info("Setting up TestScaleDown environment")
        super().setup_method(method)
        logger.info("TestScaleDown setup completed")

    @pytest.mark.asyncio
    async def test_scale_down(self) -> None:
        """Test the process of scaling down Oracle RewardAccount and AggState UTxOs.

        RewardAccount UTxOs manage reward distribution, while AggState UTxOs track
        aggregation states. When scaling down, empty/expired UTxOs are removed from
        the blockchain to reduce resource usage. These can be scaled independently.

        This test method:
        1. Counts the current AggState and RewardAccount UTxOs
        2. Retrieves the platform authentication NFT
        3. Gets the platform script configuration
        4. Builds a transaction to remove empty RewardAccount and AggState UTxOs independently
        5. Signs and submits the transaction
        6. Verifies the transaction was confirmed
        7. Confirms the UTxOs are removed correctly from the blockchain

        Raises:
            AssertionError: If the transaction fails to build or confirm,
                           or if the expected number of UTxOs is not removed
        """
        logger.info("Starting Oracle scale-down operation")

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
        logger.info(
            f"Scale-down: {self.REWARD_ACCOUNTS_TO_REMOVE} RewardAccount(s) + "
            f"{self.AGGSTATES_TO_REMOVE} AggState(s) to remove"
        )

        # BEFORE: Get current UTxOs and count initial AggState and RewardAccount UTxOs
        initial_utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        initial_agg_state_utxos = self.extract_aggregation_state_utxos(
            initial_utxos, self.management_config.tokens.oracle_policy
        )

        initial_reward_account_utxos = self.extract_reward_account_utxos(
            initial_utxos, self.management_config.tokens.oracle_policy
        )

        initial_agg_state_count = len(initial_agg_state_utxos)
        initial_reward_account_count = len(initial_reward_account_utxos)

        logger.info(f"Initial AggState UTxOs: {initial_agg_state_count}")
        logger.info(f"Initial RewardAccount UTxOs: {initial_reward_account_count}")

        # Verify that we have enough UTxOs to remove
        assert initial_agg_state_count >= self.AGGSTATES_TO_REMOVE, (
            f"Insufficient AggState UTxOs for scale-down: Found {initial_agg_state_count}, "
            f"but need at least {self.AGGSTATES_TO_REMOVE} to remove"
        )

        assert initial_reward_account_count >= self.REWARD_ACCOUNTS_TO_REMOVE, (
            f"Insufficient RewardAccount UTxOs for scale-down: Found {initial_reward_account_count}, "
            f"but need at least {self.REWARD_ACCOUNTS_TO_REMOVE} to remove"
        )

        # Find platform auth NFT at the platform address
        logger.info("Retrieving platform authentication NFT")
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

        # Build the scale-down transaction
        logger.info(
            f"Building scale-down transaction: {self.REWARD_ACCOUNTS_TO_REMOVE} RewardAccount(s) + "
            f"{self.AGGSTATES_TO_REMOVE} AggState(s)"
        )
        scale_down_result = await self.governance_orchestrator.scale_down_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            reward_account_count=self.REWARD_ACCOUNTS_TO_REMOVE,
            aggstate_count=self.AGGSTATES_TO_REMOVE,
            platform_utxo=platform_auth_utxo,
            platform_script=platform_script,
            change_address=self.oracle_addresses.admin_address,
            signing_key=self.loaded_key.payment_sk,
        )

        assert (
            scale_down_result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Scale-down transaction failed to build: {scale_down_result.error}"

        logger.info(
            f"Scale-down transaction built successfully: {scale_down_result.transaction.id}"
        )

        # Sign and submit the transaction
        logger.info("Signing and submitting scale-down transaction")
        transaction_status, _ = await self.tx_manager.sign_and_submit(
            scale_down_result.transaction,
            [self.loaded_key.payment_sk],
            wait_confirmation=True,
        )

        logger.info(f"Scale-down transaction submission status: {transaction_status}")
        assert (
            transaction_status == "confirmed"
        ), f"Scale-down transaction failed with status: {transaction_status}"

        # Wait for UTxOs to be indexed
        await wait_for_indexing(5)

        # AFTER: Check the updated UTxOs to verify they were removed
        logger.info("Verifying UTxOs were removed correctly")
        updated_utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        final_agg_state_utxos = self.extract_aggregation_state_utxos(
            updated_utxos, self.management_config.tokens.oracle_policy
        )

        final_reward_account_utxos = self.extract_reward_account_utxos(
            updated_utxos, self.management_config.tokens.oracle_policy
        )

        final_agg_state_count = len(final_agg_state_utxos)
        final_reward_account_count = len(final_reward_account_utxos)

        logger.info(f"Final AggState UTxOs: {final_agg_state_count}")
        logger.info(f"Final RewardAccount UTxOs: {final_reward_account_count}")

        # Calculate expected counts after removing UTxOs
        expected_agg_state_count = initial_agg_state_count - self.AGGSTATES_TO_REMOVE
        expected_reward_account_count = (
            initial_reward_account_count - self.REWARD_ACCOUNTS_TO_REMOVE
        )
        logger.info(
            f"Expected AggState UTxOs after removal: {expected_agg_state_count}, "
            f"Expected RewardAccount UTxOs: {expected_reward_account_count}"
        )

        # Assert that AggState UTxOs were removed correctly
        assert expected_agg_state_count == final_agg_state_count, (
            f"AggState UTxO count mismatch: Expected {expected_agg_state_count} UTxOs "
            f"(initial {initial_agg_state_count} - {self.AGGSTATES_TO_REMOVE} removed), "
            f"but found {final_agg_state_count} UTxOs in the blockchain"
        )

        # Assert that RewardAccount UTxOs were removed correctly
        assert expected_reward_account_count == final_reward_account_count, (
            f"RewardAccount UTxO count mismatch: Expected {expected_reward_account_count} UTxOs "
            f"(initial {initial_reward_account_count} - {self.REWARD_ACCOUNTS_TO_REMOVE} removed), "
            f"but found {final_reward_account_count} UTxOs in the blockchain"
        )

        logger.info("Scale-down operation completed successfully")
