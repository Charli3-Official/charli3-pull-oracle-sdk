"""Test module for scaling down Oracle Data Verification UTxO pairs.

This module tests the functionality of decreasing the number of UTxO pairs
in the Oracle. It validates that the scaling down operation correctly
removes the specified number of pairs (each consisting of an AggregationState UTxO and a
RewardTransport UTxO) from the blockchain environment.
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
    decreasing the number of UTxO pairs in the Oracle system. Each pair consists of an
    AggregationState UTxO and a RewardTransport UTxO. It verifies the transaction building,
    signing, and submission processes, and ensures that the expected number of pairs
    are removed from the blockchain.

    Attributes:
        PAIRS_TO_REMOVE_COUNT (int): Number of UTxO pairs to remove during the test.
    """

    PAIRS_TO_REMOVE_COUNT = 1

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
        """Test the process of scaling down Oracle UTxO pairs.

        Each pair consists of an AggregationState UTxO and a RewardTransport UTxO.
        These pairs are used by the Oracle system to track aggregation states and
        manage reward distribution. When scaling down, pairs are removed from the
        blockchain to reduce resource usage.

        This test method:
        1. Counts the current AggregationState and RewardTransport UTxOs
        2. Retrieves the platform authentication NFT
        3. Gets the platform script configuration
        4. Builds a transaction to remove UTxO pairs
        5. Signs and submits the transaction
        6. Verifies the transaction was confirmed
        7. Confirms the UTxO pairs are removed correctly from the blockchain

        Raises:
            AssertionError: If the transaction fails to build or confirm,
                           or if the expected number of pairs is not removed
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
            f"Scale-down amount: {self.PAIRS_TO_REMOVE_COUNT} UTxO pair(s) to remove"
        )

        # BEFORE: Get current UTxOs and count initial AggregationState and RewardTransport UTxOs
        initial_utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        initial_agg_state_utxos = self.extract_aggregation_state_utxos(
            initial_utxos, self.management_config.tokens.oracle_policy
        )

        initial_reward_transport_utxos = self.extract_reward_transport_utxos(
            initial_utxos, self.management_config.tokens.oracle_policy
        )

        initial_agg_state_count = len(initial_agg_state_utxos)
        initial_reward_transport_count = len(initial_reward_transport_utxos)

        logger.info(f"Initial AggregationState UTxOs: {initial_agg_state_count}")
        logger.info(f"Initial RewardTransport UTxOs: {initial_reward_transport_count}")

        # Verify that we have enough UTxO pairs to remove
        assert initial_agg_state_count >= self.PAIRS_TO_REMOVE_COUNT, (
            f"Insufficient AggregationState UTxOs for scale-down: Found {initial_agg_state_count}, "
            f"but need at least {self.PAIRS_TO_REMOVE_COUNT} to remove"
        )

        assert initial_reward_transport_count >= self.PAIRS_TO_REMOVE_COUNT, (
            f"Insufficient RewardTransport UTxOs for scale-down: Found {initial_reward_transport_count}, "
            f"but need at least {self.PAIRS_TO_REMOVE_COUNT} to remove"
        )

        # Verify that the initial counts match (should be in pairs)
        assert initial_agg_state_count == initial_reward_transport_count, (
            f"Initial UTxO pair mismatch: Found {initial_agg_state_count} AggregationState UTxOs "
            f"but {initial_reward_transport_count} RewardTransport UTxOs"
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
            f"Building scale-down transaction to remove {self.PAIRS_TO_REMOVE_COUNT} UTxO pair(s)"
        )
        scale_down_result = await self.governance_orchestrator.scale_down_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            scale_amount=self.PAIRS_TO_REMOVE_COUNT,
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
        logger.info("Waiting 20 seconds for UTxOs to be indexed")
        await wait_for_indexing(20)

        # AFTER: Check the updated UTxOs to verify pairs were removed
        logger.info("Verifying UTxO pairs were removed correctly")
        updated_utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        final_agg_state_utxos = self.extract_aggregation_state_utxos(
            updated_utxos, self.management_config.tokens.oracle_policy
        )

        final_reward_transport_utxos = self.extract_reward_transport_utxos(
            updated_utxos, self.management_config.tokens.oracle_policy
        )

        final_agg_state_count = len(final_agg_state_utxos)
        final_reward_transport_count = len(final_reward_transport_utxos)

        logger.info(f"Final AggregationState UTxOs: {final_agg_state_count}")
        logger.info(f"Final RewardTransport UTxOs: {final_reward_transport_count}")

        # Calculate expected counts after removing pairs
        expected_utxo_count = initial_agg_state_count - self.PAIRS_TO_REMOVE_COUNT
        logger.info(f"Expected UTxOs of each type after removal: {expected_utxo_count}")

        # Assert that both types of UTxOs were removed correctly
        assert expected_utxo_count == final_agg_state_count, (
            f"AggregationState UTxO count mismatch: Expected {expected_utxo_count} UTxOs "
            f"(initial {initial_agg_state_count} - {self.PAIRS_TO_REMOVE_COUNT} removed), "
            f"but found {final_agg_state_count} UTxOs in the blockchain"
        )

        assert expected_utxo_count == final_reward_transport_count, (
            f"RewardTransport UTxO count mismatch: Expected {expected_utxo_count} UTxOs "
            f"(initial {initial_reward_transport_count} - {self.PAIRS_TO_REMOVE_COUNT} removed), "
            f"but found {final_reward_transport_count} UTxOs in the blockchain"
        )

        # Assert that we have the same number of each type of UTxO (should be in pairs)
        assert final_agg_state_count == final_reward_transport_count, (
            f"Final UTxO pair mismatch: Found {final_agg_state_count} AggregationState UTxOs "
            f"but {final_reward_transport_count} RewardTransport UTxOs"
        )

        logger.info("Scale-down operation completed successfully")
