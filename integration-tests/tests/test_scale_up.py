"""Test module for scaling up Oracle Data Verification aggregation state UTxOs.

This module tests the functionality of increasing the number of aggregation state UTxOs
in the Oracle settings. It validates that the scaling up operation correctly
adds the specified number of aggregation state pairs to the blockchain environment.
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


class TestScaleUp(GovernanceBase):
    """Test class for validating Oracle scale-up operations in the governance system.

    This class inherits from GovernanceBase and implements test methods for
    increasing the number of aggregation state UTxOs in the Oracle system. It verifies
    the transaction building, signing, and submission processes, and ensures that
    the expected number of new aggregation state pairs are created.
    """

    NEW_PAIR_UTXOS = 2

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment before each test method execution.

        Args:
            method (Callable): The test method being run.
        """
        logger.info("Setting up TestScaleUp environment")
        super().setup_method(method)
        logger.info("TestScaleUp setup completed")

    @pytest.mark.asyncio
    async def test_scale_up(self) -> None:
        """Test the process of scaling up Oracle aggregation state UTxOs.

        This test method:
        1. Counts the current aggregation state UTxOs
        2. Retrieves the platform authentication NFT
        3. Gets the platform script configuration
        4. Builds a transaction to add new aggregation state pairs
        5. Signs and submits the transaction
        6. Verifies the transaction was confirmed
        7. Confirms the new aggregation state UTxOs are created correctly

        Raises:
            AssertionError: If the transaction fails to build or confirm,
                           or if the expected number of aggregation states is not created
        """
        logger.info("Starting Oracle scale-up operation")

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
            f"Scale-up amount: {self.NEW_PAIR_UTXOS} new aggregation state pair(s)"
        )

        # Get current UTxOs and count aggregation states
        utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        total_agg_state_utxos = len(self.filter_all_agg_states(utxos))
        logger.info(f"Current aggregation state UTxOs: {total_agg_state_utxos}")

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

        # Build the scale-up transaction
        logger.info(
            f"Building scale-up transaction to add {self.NEW_PAIR_UTXOS} aggregation state pair(s)"
        )
        result = await self.governance_orchestrator.scale_up_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            scale_amount=self.NEW_PAIR_UTXOS,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=self.oracle_addresses.admin_address,
            signing_key=self.loaded_key.payment_sk,
        )

        assert (
            result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Scale-up transaction failed to build: {result.error}"

        logger.info(f"Scale-up transaction built successfully: {result.transaction.id}")

        # Sign and submit the transaction
        logger.info("Signing and submitting scale-up transaction")
        transaction_status, _ = await self.tx_manager.sign_and_submit(
            result.transaction,
            [self.loaded_key.payment_sk],
            wait_confirmation=True,
        )

        logger.info(f"Scale-up transaction submission status: {transaction_status}")
        assert (
            transaction_status == "confirmed"
        ), f"Scale-up transaction failed with status: {transaction_status}"

        # Wait for UTxOs to be indexed
        logger.info(f"Waiting {20} seconds for UTxOs to be indexed")
        await wait_for_indexing(20)

        # Check the updated aggregation state UTxOs
        logger.info("Verifying new aggregation state UTxOs were created correctly")
        utxos = await get_script_utxos(
            Address.from_primitive(self.oracle_addresses.script_address),
            self.tx_manager,
        )

        new_agg_state_utxos = len(self.filter_all_agg_states(utxos))
        logger.info(f"Updated aggregation state UTxOs: {new_agg_state_utxos}")

        # Compare aggregation state count before and after
        expected_agg_state_utxos = total_agg_state_utxos + self.NEW_PAIR_UTXOS
        logger.info(f"Expected aggregation state UTxOs: {expected_agg_state_utxos}")

        # Assert that the aggregation state counts match
        assert expected_agg_state_utxos == new_agg_state_utxos, (
            f"Aggregation state mismatch: Expected {expected_agg_state_utxos} UTxOs, "
            f"but found {new_agg_state_utxos} UTxOs in the blockchain"
        )

        logger.info("Scale-up operation completed successfully")
