"""Test the creation of reference scripts for the Charli3 ODV Oracle."""

from collections.abc import Callable

import pytest

from charli3_offchain_core.oracle.config import OracleScriptConfig

from .async_utils import async_retry
from .base import TEST_RETRIES, TestBase
from .test_utils import logger, wait_for_indexing


@pytest.mark.run(order=2)
class TestCreateReferenceScript(TestBase):
    """Test the creation of reference scripts for the ODV Oracle."""

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment."""
        logger.info("Setting up TestCreateReferenceScript environment")

        super().setup_method(method)

        # Script configuration
        self.script_config = OracleScriptConfig(
            create_manager_reference=True,
            reference_ada_amount=69528920,  # 69.52892 ADA for reference scripts
        )

    @pytest.mark.asyncio
    @async_retry(tries=TEST_RETRIES, delay=5)
    async def test_create_manager_reference_script(self) -> None:
        """Test creating the manager reference script."""
        # Check if reference script already exists

        # Prepare reference script transaction
        reference_result, needs_reference = (
            await self.orchestrator.handle_reference_scripts(
                script_config=self.script_config,
                script_address=self.oracle_script_address,
                admin_address=self.admin_address,
                signing_key=self.admin_signing_key,
            )
        )

        if not needs_reference:
            pytest.skip("Manager reference script already exists")

        assert (
            reference_result.manager_tx is not None
        ), "Failed to build manager reference script transaction"

        logger.info("Manager reference script transaction built")

        # Submit the transaction
        await self.orchestrator.submit_reference_script_tx(
            reference_result, self.admin_signing_key
        )

        logger.info("Manager reference script transaction submitted")

        # Verify that the reference script now exists
        await wait_for_indexing(10)

        manager_utxo = (
            await self.orchestrator.reference_builder.script_finder.find_manager_reference()
        )
        assert (
            manager_utxo is not None
        ), "Manager reference script not found after creation"
