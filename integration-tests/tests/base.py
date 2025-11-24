"""Base functionality for ODV integration tests."""

import asyncio
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from pycardano import (
    Network,
    TransactionBuilder,
    TransactionOutput,
)

from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.setup import setup_oracle_from_config

from .async_utils import async_retry
from .test_utils import logger, wait_for_indexing

# Increase recursion limit to avoid RecursionError
sys.setrecursionlimit(2000)  # Default is usually 1000

# Configure logging

TEST_RETRIES = 3


class TestBase:
    """Base class for ODV system integration tests."""

    NETWORK = Network.TESTNET
    DIR_PATH: ClassVar[str] = os.path.dirname(os.path.realpath(__file__))

    def setup_method(self, method: Any) -> None:
        """Set up test configuration."""
        logger.info("Setting up test base environment")
        self.config_path = Path(self.DIR_PATH).parent / "configuration.yml"

        if not self.config_path.exists():
            logger.error(f"Configuration file not found at {self.config_path}")
            raise FileNotFoundError(
                f"Configuration file not found at {self.config_path}"
            )

        try:
            # Use the CLI setup function to load configuration
            logger.info(f"Loading configuration from {self.config_path}")
            setup_result = setup_oracle_from_config(self.config_path)

            # Unpack the result tuple
            (
                self.deployment_config,
                self.oracle_config,
                self.payment_sk,
                self.payment_vk,
                self.addresses,
                self.chain_query,
                self.tx_manager,
                self.orchestrator,
                self.platform_auth_finder,
                self.configs,
            ) = setup_result

            # Set status callback once in base class
            self.orchestrator.status_callback = format_status_update

            # OVERRIDE: Increase TTL offset for integration tests
            # This helps avoid "outside of validity interval" errors in slower CI environments
            # Default is 180s (3 mins), increasing to 600s (10 mins)
            self.tx_manager.config.ttl_offset = 300
            logger.info(
                f"Overridden ttl_offset to {self.tx_manager.config.ttl_offset} for testing"
            )

            # Store important configuration details as instance attributes
            self.admin_signing_key = self.payment_sk
            self.admin_verification_key = self.payment_vk
            self.admin_address = self.addresses.admin_address
            self.oracle_script_address = self.addresses.script_address
            self.platform_address = self.addresses.platform_address

            # For easier access, store some specific configurations
            self.nodes_config = self.deployment_config.nodes
            self.token_config = self.deployment_config.tokens
            self.timing_config = self.deployment_config.timing
            self.fee_config = self.configs["rate_token"]

            logger.info(f"admin_address: {self.admin_address}")
            logger.info(f"oracle_script_address: {self.oracle_script_address}")
            logger.info(f"platform_address: {self.platform_address}")
            logger.info(
                f"admin_address pub_key_hash: {self.admin_address.payment_part}"
            )
            logger.info(
                f"oracle_script_address script_hash: {self.oracle_script_address.payment_part}"
            )

            logger.info("Test base environment setup complete")

        except Exception as e:
            logger.error(f"Error setting up test environment: {e}")
            raise

    @async_retry(tries=TEST_RETRIES, delay=3)
    async def assert_output(
        self, target_address: str, predicate_function: Callable
    ) -> None:
        """Check that at least one UTxO at the address satisfies the predicate function."""
        utxos = await self.chain_query.get_utxos(target_address)
        found = False

        for utxo in utxos:
            if predicate_function(utxo):
                found = True
                break

        assert found, f"No UTxO matching the predicate at address: {target_address}"

    @async_retry(tries=TEST_RETRIES, delay=3)
    async def wait_for_transaction(self, tx_id: str, timeout: int = 60) -> Any | None:
        """Wait for a transaction to be confirmed on the blockchain."""
        start_time = asyncio.get_event_loop().time()

        while True:
            try:
                # Use transaction query from the chain query
                tx = await self.chain_query.context.get_transaction(tx_id)
                if tx:
                    return tx
            except Exception as e:
                logger.debug(f"Exception while waiting for transaction {tx_id}: {e}")

            if asyncio.get_event_loop().time() - start_time > timeout:
                return None

            await asyncio.sleep(3)

    async def create_collateral_utxos(
        self, count: int = 10, amount: int = 20_000_000
    ) -> bool:
        """
        Create dedicated collateral UTxOs to ensure availability for deployment.

        Args:
            count: Number of collateral UTxOs to create (default increased to 10)
            amount: Amount per UTxO in lovelace (default increased to 20 ADA)

        Returns:
            True if creation succeeded, False otherwise
        """
        logger.info(f"Creating {count} collateral UTxOs of {amount} lovelace each")

        # Build transaction with multiple outputs
        builder = TransactionBuilder(self.tx_manager.chain_query.context)
        builder.add_input_address(self.admin_address)

        # Create separate outputs for each collateral UTxO
        for _ in range(count):
            builder.add_output(
                TransactionOutput(address=self.admin_address, amount=amount)
            )

        try:
            # Build and sign transaction
            tx = builder.build_and_sign(
                [self.admin_signing_key], change_address=self.admin_address
            )

            # Submit transaction
            logger.info(f"Submitting collateral creation transaction: {tx.id}")
            status, _ = await self.tx_manager.chain_query.submit_tx(
                tx, wait_confirmation=True
            )

            if status != "confirmed":
                logger.error(f"Collateral creation failed with status: {status}")
                return False

            # Wait for indexing
            await wait_for_indexing()

            # Verify UTxOs were created
            new_utxos = await self.tx_manager.chain_query.get_utxos(self.admin_address)
            new_collateral = [
                utxo
                for utxo in new_utxos
                if not utxo.output.amount.multi_asset
                and utxo.output.amount.coin >= 5_000_000
                and utxo.output.amount.coin <= 20_000_000
            ]

            logger.info(f"Found {len(new_collateral)} collateral UTxOs after creation")
            return len(new_collateral) >= count

        except Exception as e:
            logger.error(f"Error creating collateral UTxOs: {e}")
            return False


class MultisigTestBase(TestBase):
    """Base class for multisig tests."""

    def setup_method(self, method: "Callable") -> None:
        """Setup for multisig tests."""
        super().setup_method(method)

        # For multisig tests, we might need to use a different platform address
        # This can be customized based on the multisig configuration
        self.multisig_threshold = self.deployment_config.multi_sig.threshold
        self.multisig_parties = self.deployment_config.multi_sig.parties
