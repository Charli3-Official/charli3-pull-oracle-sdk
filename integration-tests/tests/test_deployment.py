"""Test the deployment of the Charli3 ODV Oracle."""

import asyncio
from collections.abc import Callable

import pytest
from retry import retry

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.config.nodes import NodeConfig, NodesConfig
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.oracle.config import OracleDeploymentConfig
from charli3_offchain_core.oracle.deployment.orchestrator import (
    OracleDeploymentOrchestrator,
)
from charli3_offchain_core.platform.auth.token_finder import PlatformAuthFinder

from .base import TEST_RETRIES, TestBase


@pytest.mark.order(1)
class TestDeployment(TestBase):
    """Test the deployment of the Charli3 ODV Oracle."""

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment."""
        super().setup_method(method)
        self.tx_manager = TransactionManager(self.CHAIN_CONTEXT)

        # Load contracts
        self.contracts = OracleContracts.from_blueprint("artifacts/plutus.json")

        # Initialize orchestrator
        self.orchestrator = OracleDeploymentOrchestrator(
            chain_query=self.CHAIN_CONTEXT,
            contracts=self.contracts,
            tx_manager=self.tx_manager,
            status_callback=format_status_update,
        )

        # Initialize platform auth finder
        self.platform_auth_finder = PlatformAuthFinder(self.CHAIN_CONTEXT)

        # Configure node list for deployment
        self.node_configs = []
        for _i, vkh in enumerate(self.node_vkhs[:2]):  # Start with 2 nodes
            self.node_configs.append(
                NodeConfig(
                    feed_vkh=vkh,
                    payment_vkh=vkh,  # Initially same as feed_vkh
                )
            )

        self.nodes_config = NodesConfig(
            required_signatures=1,
            nodes=self.node_configs,
        )

        # Set up deployment config
        self.deployment_config = OracleDeploymentConfig(
            network=self.NETWORK,
            reward_transport_count=self.transport_count,
        )

    @retry(tries=TEST_RETRIES, delay=5)
    @pytest.mark.asyncio
    async def test_deployment(self) -> None:
        """Test oracle deployment with platform auth NFT."""
        # Find platform auth NFT
        platform_utxo = await self.platform_auth_finder.find_auth_utxo(
            policy_id=self.token_config.platform_auth_policy,
            platform_address=str(self.admin_address),
        )

        # If no platform auth NFT is found, we'll need to mint one for testing
        if not platform_utxo:
            pytest.skip("Platform auth NFT not found - please create one first")

        platform_script = await self.platform_auth_finder.get_platform_script(
            self.admin_address
        )

        # Build the deployment transaction
        result = await self.orchestrator.build_tx(
            oracle_config=self.oracle_config,
            platform_script=platform_script,
            admin_address=self.admin_address,
            script_address=self.oracle_script_address,
            aggregation_liveness_period=self.aggregation_liveness_period,
            time_uncertainty_aggregation=self.time_uncertainty_aggregation,
            time_uncertainty_platform=self.time_uncertainty_platform,
            iqr_fence_multiplier=self.iqr_fence_multiplier,
            deployment_config=self.deployment_config,
            nodes_config=self.nodes_config,
            signing_key=self.admin_signing_key,
            platform_utxo=platform_utxo,
        )

        assert (
            result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Deployment transaction build failed: {result.error}"

        # Sign and submit the transaction
        status, _ = await self.tx_manager.sign_and_submit(
            result.start_result.transaction,
            [self.admin_signing_key],
            wait_confirmation=True,
        )

        assert (
            status == "confirmed"
        ), f"Deployment transaction failed with status: {status}"

        # Verify deployment by checking for oracle UTxOs
        await asyncio.sleep(10)  # Wait for UTxOs to be indexed

        # Check that UTxOs exist at the oracle script address
        utxos = await self.CHAIN_CONTEXT.get_utxos(self.oracle_script_address)
        assert (
            len(utxos) > 0
        ), "No UTxOs found at oracle script address after deployment"

        # Store the deployment result for other tests
        with open("deployment_result.txt", "w") as f:
            f.write(f"Oracle Policy ID: {result.start_result.transaction.id}\n")
            f.write(f"Oracle Script Address: {self.oracle_script_address}\n")
