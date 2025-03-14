"""Base functionality for ODV integration tests."""

import asyncio
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from pycardano import (
    Network,
    OgmiosV6ChainContext,
)
from pycardano.backend.kupo import KupoChainContextExtension
from retry import retry

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.cli.setup import setup_oracle_from_config

# Increase recursion limit to avoid RecursionError
sys.setrecursionlimit(2000)  # Default is usually 1000

# Configure logging
logger = logging.getLogger(__name__)
TEST_RETRIES = 6


class TestBase:
    """Base class for ODV system integration tests."""

    NETWORK = Network.TESTNET
    OGMIOS_WS = "ws://localhost:1337"
    KUPO_URL = "http://localhost:1442"
    _, ws_host = OGMIOS_WS.split("ws://")
    ws_url, port = ws_host.split(":")
    ogmios_context = OgmiosV6ChainContext(
        host=ws_url,
        port=port,
        secure=False,
        refetch_chain_tip_interval=None,
        network=NETWORK,
    )
    kupo_context = KupoChainContextExtension(
        ogmios_context,
        kupo_url=KUPO_URL,
    )

    CHAIN_CONTEXT: ClassVar[ChainQuery] = ChainQuery(kupo_ogmios_context=kupo_context)
    DIR_PATH: ClassVar[str] = os.path.dirname(os.path.realpath(__file__))
    wallet_keys: ClassVar[list] = []

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

    @retry(tries=TEST_RETRIES, delay=3)
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

    @retry(tries=TEST_RETRIES, delay=3)
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


class MultisigTestBase(TestBase):
    """Base class for multisig tests."""

    def setup_method(self, method: "Callable") -> None:
        """Setup for multisig tests."""
        super().setup_method(method)

        # For multisig tests, we might need to use a different platform address
        # This can be customized based on the multisig configuration
        self.multisig_threshold = self.deployment_config.multi_sig.threshold
        self.multisig_parties = self.deployment_config.multi_sig.parties
