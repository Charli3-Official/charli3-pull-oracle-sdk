"""Test the deployment of the Charli3 ODV Oracle."""

from collections.abc import Callable

import pytest

from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.oracle.utils.common import get_script_utxos

from .base import TestBase
from .test_utils import (
    find_platform_auth_nft,
    logger,
    update_config_file,
    wait_for_indexing,
)


@pytest.mark.run(order=1)
class TestDeployment(TestBase):
    """Test the deployment of the Charli3 ODV Oracle."""

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment."""
        logger.info("Setting up TestDeployment environment")
        super().setup_method(method)
        logger.info("TestDeployment setup complete")

    @pytest.mark.asyncio
    async def test_deployment(self) -> None:
        """Test oracle deployment with platform auth NFT."""
        logger.info("Starting oracle deployment test")

        # Log current configuration
        logger.info(f"Using admin address: {self.admin_address}")
        logger.info(f"Using platform address: {self.platform_address}")
        logger.info(f"Using oracle script address: {self.oracle_script_address}")
        logger.info(
            f"Using platform auth policy ID: {self.token_config.platform_auth_policy}"
        )

        # Create collateral UTxOs first to ensure they're available
        await self.create_collateral_utxos(count=5, amount=9_000_000)

        # Find platform auth NFT at the platform address
        platform_utxo = await find_platform_auth_nft(
            self.platform_auth_finder,
            self.token_config.platform_auth_policy,
            [self.platform_address, self.admin_address],
        )

        # If still not found, skip the test
        if not platform_utxo:
            pytest.skip("Platform auth NFT not found - please create one first")

        # Get platform script
        logger.info(f"Getting platform script for address: {self.platform_address}")
        platform_script = await self.platform_auth_finder.get_platform_script(
            str(self.platform_address)
        )
        platform_multisig_config = self.platform_auth_finder.get_script_config(
            platform_script
        )

        logger.info(
            f"Platform multisig threshold: {platform_multisig_config.threshold}"
        )

        # Build the deployment transaction
        logger.info("Building deployment transaction")
        result = await self.orchestrator.build_tx(
            oracle_config=self.oracle_config,
            platform_script=platform_script,
            admin_address=self.admin_address,
            script_address=self.oracle_script_address,
            aggregation_liveness_period=self.timing_config.aggregation_liveness,
            time_uncertainty_aggregation=self.timing_config.time_uncertainty_aggregation,
            time_uncertainty_platform=self.timing_config.time_uncertainty_platform,
            iqr_fence_multiplier=self.timing_config.iqr_multiplier,
            deployment_config=self.configs["deployment"],
            nodes_config=self.nodes_config,
            rate_config=self.fee_config,
            signing_key=self.admin_signing_key,
            platform_utxo=platform_utxo,
        )

        assert (
            result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Deployment transaction build failed: {result.error}"
        logger.info(
            f"Deployment transaction built successfully: {result.start_result.transaction.id}"
        )

        # Sign and submit the transaction
        logger.info("Signing and submitting deployment transaction")
        status, _ = await self.tx_manager.sign_and_submit(
            result.start_result.transaction,
            [self.admin_signing_key],
            wait_confirmation=True,
        )

        logger.info(f"Deployment transaction submission status: {status}")
        assert (
            status == "confirmed"
        ), f"Deployment transaction failed with status: {status}"

        # Wait for UTxOs to be indexed
        await wait_for_indexing(5)

        # Check that UTxOs exist at the oracle script address
        logger.info(
            f"Checking for UTxOs at oracle script address: {self.oracle_script_address}"
        )
        utxos = await get_script_utxos(self.oracle_script_address, self.tx_manager)
        logger.info(f"Found {len(utxos)} UTxOs at oracle script address")
        assert (
            len(utxos) > 0
        ), "No UTxOs found at oracle script address after deployment"

        # Update the configuration file with the new params
        logger.info(
            f"Updating configuration file with new oracle script address: {self.oracle_script_address}"
        )
        logger.info(
            f"Updating configuration file with new oracle policy id: {result.start_result.oracle_policy_id}"
        )
        update_config_file(
            self.config_path,
            {
                "oracle_address": str(self.oracle_script_address),
                "tokens.oracle_policy": result.start_result.oracle_policy_id,
            },
        )

        logger.info("Oracle deployment test completed successfully")
