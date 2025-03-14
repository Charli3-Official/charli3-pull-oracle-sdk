"""Test the creation of the Platform Auth NFT."""

import asyncio
import logging
from typing import Any

import pytest
import yaml

from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.setup import setup_platform_from_config

from .async_utils import async_retry
from .base import TestBase

# Set up logger
logger = logging.getLogger(__name__)


@pytest.mark.run(order=0)  # Run before deployment tests
class TestPlatformAuth(TestBase):
    """Test the creation of the Platform Auth NFT."""

    def setup_method(self, method: Any) -> None:
        """Set up the test environment."""
        super().setup_method(method)
        logger.info("Setting up Platform Auth test environment")

        # Use the CLI setup function for platform auth
        try:
            # We'll use the same config file but focus on platform auth settings
            platform_setup = setup_platform_from_config(self.config_path, None)

            # Unpack the result tuple
            (
                self.auth_config,
                self.platform_signing_key,
                self.platform_verification_key,
                self.stake_vk,
                self.platform_address,
                self.platform_chain_query,
                self.platform_tx_manager,
                self.platform_orchestrator,
                self.meta_data,
            ) = platform_setup

            # Set the status callback for better logging
            self.platform_orchestrator.status_callback = format_status_update

            logger.info("Platform Auth test environment setup complete")

        except Exception as e:
            logger.error(f"Error setting up Platform Auth test environment: {e}")
            raise

    @pytest.mark.asyncio
    @async_retry(tries=1, delay=0)
    async def test_mint_platform_auth_nft(self) -> None:
        """Test minting a Platform Auth NFT."""
        logger.info("Starting Platform Auth NFT minting test")

        # Check if Platform Auth NFT already exists
        logger.info(
            f"Checking if Platform Auth NFT already exists at {self.platform_address}"
        )

        platform_utxo = await self.platform_auth_finder.find_auth_utxo(
            policy_id=self.token_config.platform_auth_policy,
            platform_address=str(self.platform_address),
        )

        if platform_utxo:
            logger.info("Platform Auth NFT already exists, skipping test")
            pytest.skip("Platform Auth NFT already exists")

        # Get multisig config from the deployment config
        multisig_threshold = self.auth_config.multisig.threshold
        multisig_parties = self.auth_config.multisig.parties

        logger.info(f"Using multisig threshold: {multisig_threshold}")
        logger.info(f"Using multisig parties: {multisig_parties}")

        # Build the auth NFT transaction
        logger.info("Building Platform Auth NFT transaction")
        result = await self.platform_orchestrator.build_tx(
            sender_address=self.platform_address,
            signing_key=self.platform_signing_key,
            multisig_threshold=multisig_threshold,
            multisig_parties=multisig_parties,
            network=self.NETWORK,
        )

        assert result.transaction is not None, "Failed to build transaction"
        assert result.policy_id is not None, "Policy ID not generated"

        logger.info(f"Transaction built successfully with ID: {result.transaction.id}")
        logger.info(f"Generated Policy ID: {result.policy_id}")
        logger.info(f"Platform address: {result.platform_address}")

        # Sign and submit the transaction
        logger.info("Signing and submitting transaction")
        status, _ = await self.platform_tx_manager.sign_and_submit(
            result.transaction, [self.platform_signing_key], wait_confirmation=True
        )

        logger.info(f"Transaction submission status: {status}")
        assert status == "confirmed", f"Platform Auth NFT transaction failed: {status}"

        # Verify that NFT was created
        logger.info("Waiting for UTxOs to be indexed...")
        await asyncio.sleep(10)  # Wait for UTxOs to be indexed

        logger.info(f"Verifying NFT creation at address: {result.platform_address}")
        platform_utxo = await self.platform_auth_finder.find_auth_utxo(
            policy_id=result.policy_id,
            platform_address=str(result.platform_address),
        )

        if platform_utxo:
            logger.info(
                f"Platform Auth NFT found in UTxO: {platform_utxo.input.transaction_id}#{platform_utxo.input.index}"
            )
        else:
            logger.error("Platform Auth NFT not found after minting")

        assert platform_utxo is not None, "Platform Auth NFT not found after minting"

        # Update the configuration file with the new policy ID
        logger.info(
            f"Updating configuration file with new policy ID: {result.policy_id}"
        )
        config_path = self.config_path

        try:
            # Load existing configuration
            with open(config_path) as f:
                config_data = yaml.safe_load(f)

            # Update the platform auth policy ID
            if "tokens" not in config_data:
                config_data["tokens"] = {}

            config_data["tokens"]["platform_auth_policy"] = result.policy_id

            # Write updated configuration back to file
            with open(config_path, "w") as f:
                yaml.dump(config_data, f, default_flow_style=False)

            logger.info(
                f"Configuration file updated with policy ID: {result.policy_id}"
            )

        except Exception as e:
            logger.error(f"Failed to update configuration file: {e}")
            # Don't fail the test if config update fails

            logger.info(
                "Platform Auth NFT minting and configuration update completed successfully"
            )
