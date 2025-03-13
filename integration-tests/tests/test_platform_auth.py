"""Test the creation of the Platform Auth NFT."""

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.platform.auth.orchestrator import PlatformAuthOrchestrator
from charli3_offchain_core.platform.auth.token_finder import PlatformAuthFinder

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
        self.tx_manager = TransactionManager(self.CHAIN_CONTEXT)

        # Initialize platform auth finder and orchestrator
        self.platform_auth_finder = PlatformAuthFinder(self.CHAIN_CONTEXT)
        self.orchestrator = PlatformAuthOrchestrator(
            chain_query=self.CHAIN_CONTEXT,
            tx_manager=self.tx_manager,
            status_callback=format_status_update,
        )
        logger.info("Platform Auth test environment setup complete")

    @pytest.mark.asyncio
    @async_retry(tries=1, delay=0)
    async def test_mint_platform_auth_nft(self) -> None:
        """Test minting a Platform Auth NFT."""
        logger.info("Starting Platform Auth NFT minting test")

        # Check if Platform Auth NFT already exists
        logger.info(
            f"Checking if Platform Auth NFT already exists at {self.admin_address}"
        )
        platform_utxo = await self.platform_auth_finder.find_auth_utxo(
            policy_id=self.token_config.platform_auth_policy,
            platform_address=str(self.admin_address),
        )

        if platform_utxo:
            logger.info("Platform Auth NFT already exists, skipping test")
            pytest.skip("Platform Auth NFT already exists")

        # Convert verification key hash to hex string for multisig parties
        admin_vkh_hex = self.admin_verification_key.hash().to_primitive().hex()
        multisig_parties = [admin_vkh_hex]
        logger.info(f"Using admin verification key hash: {admin_vkh_hex}")
        logger.info(f"Multisig threshold: 1, parties: {multisig_parties}")

        # Build and submit the auth NFT transaction
        logger.info("Building Platform Auth NFT transaction")
        result = await self.orchestrator.build_tx(
            sender_address=self.admin_address,
            signing_key=self.admin_signing_key,
            multisig_threshold=1,
            multisig_parties=multisig_parties,
            network=self.NETWORK,
        )

        assert result.transaction is not None, "Failed to build transaction"
        assert result.policy_id is not None, "Policy ID not generated"

        logger.info(f"Transaction built successfully with ID: {result.transaction.id}")
        logger.info(f"Generated Policy ID: {result.policy_id}")
        logger.info(f"Platform address: {result.platform_address}")

        logger.info("Signing and submitting transaction")
        status, _ = await self.tx_manager.sign_and_submit(
            result.transaction, [self.admin_signing_key], wait_confirmation=True
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

        # Update token config for subsequent tests
        logger.info(f"Updating token config with new policy ID: {result.policy_id}")
        self.token_config.platform_auth_policy = result.policy_id

        if platform_utxo is not None:
            logger.info("Platform Auth NFT minting test completed successfully")

            # Update configuration.yml file with the new policy ID
            config_path = Path(__file__).parent.parent / "configuration.yml"
            logger.info(f"Updating configuration file at: {config_path}")

            try:
                # Load existing configuration
                with open(config_path) as f:
                    config_data = yaml.safe_load(f)

                # Update the platform_auth_policy value
                if "oracle_owner" not in config_data:
                    config_data["oracle_owner"] = {}

                config_data["oracle_owner"]["platform_auth_policy"] = result.policy_id

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
