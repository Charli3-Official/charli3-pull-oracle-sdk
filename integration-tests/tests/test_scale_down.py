"""Test module for scaling down Oracle Data Verification UTxO pairs.

This module tests the functionality of decreasing the number of UTxO pairs
in the Oracle. It validates that the scaling down operation correctly
removes the specified number of pairs (each consisting of an AggState UTxO and a
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
    AggState UTxO and a RewardTransport UTxO. It verifies the transaction building,
    signing, and submission processes, and ensures that the expected number of pairs
    are removed.
    """

    REMOVE_PAIR_UTXOS = 1

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment before each test method execution.

        Args:
            method (Callable): The test method being run.
        """
        logger.info("Setting up TestScaleDown environment")
        super().setup_method(method)
        logger.info("TestScaleDown setup completed")

    @pytest.mark.asyncio
    async def test_scale_down(self) -> None:
        """Test the process of scaling down Oracle UTxO pairs.

        Each pair consists of an AggState UTxO and a RewardTransport UTxO.

        This test method:
        1. Counts the current AggState and RewardTransport UTxOs
        2. Retrieves the platform authentication NFT
        3. Gets the platform script configuration
        4. Builds a transaction to remove UTxO pairs
        5. Signs and submits the transaction
        6. Verifies the transaction was confirmed
        7. Confirms the UTxO pairs are removed correctly

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
            f"Scale-down amount: {self.REMOVE_PAIR_UTXOS} UTxO pair(s) to remove"
        )

        # Get current UTxOs and count both AggState and RewardTransport UTxOs
        utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        agg_state_utxos = self.filter_all_agg_states(
            utxos, self.management_config.tokens.oracle_policy
        )

        reward_transport_utxos = self.filter_all_reward_transports(
            utxos, self.management_config.tokens.oracle_policy
        )

        total_agg_state_utxos = len(agg_state_utxos)
        total_reward_transport_utxos = len(reward_transport_utxos)

        logger.info(f"Current AggState UTxOs: {total_agg_state_utxos}")
        logger.info(f"Current RewardTransport UTxOs: {total_reward_transport_utxos}")

        # Find platform auth NFT at the platform address
        logger.info("Retrieving platform authentication NFT")
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

        # Build the scale-down transaction
        logger.info(
            f"Building scale-down transaction to remove {self.REMOVE_PAIR_UTXOS} aggregation state pair(s)"
        )
        result = await self.governance_orchestrator.scale_down_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            scale_amount=self.REMOVE_PAIR_UTXOS,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=self.oracle_addresses.admin_address,
            signing_key=self.loaded_key.payment_sk,
        )

        assert (
            result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Scale-down transaction failed to build: {result.error}"

        logger.info(
            f"Scale-down transaction built successfully: {result.transaction.id}"
        )

        # Sign and submit the transaction
        logger.info("Signing and submitting scale-down transaction")
        transaction_status, _ = await self.tx_manager.sign_and_submit(
            result.transaction,
            [self.loaded_key.payment_sk],
            wait_confirmation=True,
        )

        logger.info(f"Scale-down transaction submission status: {transaction_status}")
        assert (
            transaction_status == "confirmed"
        ), f"Scale-down transaction failed with status: {transaction_status}"

        # Wait for UTxOs to be indexed
        await wait_for_indexing(20)

        # Check the updated UTxOs
        logger.info("Verifying UTxO pairs were removed correctly")
        utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        new_agg_state_utxos = self.filter_all_agg_states(
            utxos, self.management_config.tokens.oracle_policy
        )

        new_reward_transport_utxos = self.filter_all_reward_transports(
            utxos, self.management_config.tokens.oracle_policy
        )

        new_agg_state_count = len(new_agg_state_utxos)
        new_reward_transport_count = len(new_reward_transport_utxos)

        logger.info(f"Updated AggState UTxOs: {new_agg_state_count}")
        logger.info(f"Updated RewardTransport UTxOs: {new_reward_transport_count}")

        # Compare counts before and after
        expected_count = total_agg_state_utxos - self.REMOVE_PAIR_UTXOS
        logger.info(f"Expected UTxOs of each type: {expected_count}")

        # Assert that both types of UTxOs were removed correctly
        assert expected_count == new_agg_state_count, (
            f"AggState UTxO mismatch: Expected {expected_count} UTxOs, "
            f"but found {new_agg_state_count} UTxOs in the blockchain"
        )

        assert expected_count == new_reward_transport_count, (
            f"RewardTransport UTxO mismatch: Expected {expected_count} UTxOs, "
            f"but found {new_reward_transport_count} UTxOs in the blockchain"
        )

        # Assert that we have the same number of each type of UTxO
        assert new_agg_state_count == new_reward_transport_count, (
            f"UTxO pair mismatch: Found {new_agg_state_count} AggState UTxOs "
            f"but {new_reward_transport_count} RewardTransport UTxOs"
        )

        logger.info("Scale-down operation completed successfully")
