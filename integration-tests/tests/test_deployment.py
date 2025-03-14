"""Test the deployment of the Charli3 ODV Oracle."""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.config.nodes import NodeConfig, NodesConfig
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import FeeConfig, NoDatum, RewardPrices
from charli3_offchain_core.oracle.config import OracleDeploymentConfig
from charli3_offchain_core.oracle.deployment.orchestrator import (
    OracleDeploymentOrchestrator,
)
from charli3_offchain_core.platform.auth.token_finder import PlatformAuthFinder

from .async_utils import async_retry
from .base import TestBase

# Set up logger
logger = logging.getLogger(__name__)


@pytest.mark.run(order=1)
class TestDeployment(TestBase):
    """Test the deployment of the Charli3 ODV Oracle."""

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment."""
        logger.info("Setting up TestDeployment environment")
        super().setup_method(method)
        self.tx_manager = TransactionManager(self.CHAIN_CONTEXT)

        # Reload the platform auth policy from the configuration file
        config_path = Path(__file__).parent.parent / "configuration.yml"
        logger.info(f"Loading configuration from: {config_path}")
        try:
            with open(config_path) as f:
                config_data = yaml.safe_load(f)

            if (
                "oracle_owner" in config_data
                and "platform_auth_policy" in config_data["oracle_owner"]
            ):
                old_policy = self.token_config.platform_auth_policy
                new_policy = config_data["oracle_owner"]["platform_auth_policy"]
                logger.info(
                    f"Updating platform_auth_policy from {old_policy} to {new_policy}"
                )
                self.token_config.platform_auth_policy = new_policy
            else:
                logger.warning("platform_auth_policy not found in configuration file")
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")

        # Load contracts
        logger.info("Loading OracleContracts from blueprint")
        self.contracts = OracleContracts.from_blueprint(
            "../artifacts/testnet_plutus.json"
        )

        # Initialize orchestrator
        logger.info("Initializing OracleDeploymentOrchestrator")
        self.orchestrator = OracleDeploymentOrchestrator(
            chain_query=self.CHAIN_CONTEXT,
            contracts=self.contracts,
            tx_manager=self.tx_manager,
            status_callback=format_status_update,
        )

        # Initialize platform auth finder
        logger.info("Initializing PlatformAuthFinder")
        self.platform_auth_finder = PlatformAuthFinder(self.CHAIN_CONTEXT)

        # Configure node list for deployment
        logger.info("Configuring nodes for deployment")
        self.node_configs = []
        for _i, vkh in enumerate(self.node_vkhs[:4]):
            self.node_configs.append(
                NodeConfig(
                    feed_vkh=vkh,
                    payment_vkh=vkh,
                )
            )

        # Set required signatures to match the number of nodes
        num_nodes = len(self.node_configs)
        self.nodes_config = NodesConfig(
            required_signatures=num_nodes,
            nodes=self.node_configs,
        )

        self.rate_config = FeeConfig(
            rate_nft=NoDatum(),
            reward_prices=RewardPrices(
                node_fee=self.node_fee, platform_fee=self.platform_fee
            ),
        )

        # Set up deployment config
        logger.info("Setting up deployment configuration")
        self.deployment_config = OracleDeploymentConfig(
            network=self.NETWORK,
            reward_transport_count=self.transport_count,
        )
        logger.info("TestDeployment setup complete")

    @pytest.mark.asyncio
    @async_retry(tries=1, delay=0)
    async def test_deployment(self) -> None:
        """Test oracle deployment with platform auth NFT."""
        logger.info("Starting oracle deployment test")

        # Log current configuration
        logger.info(f"Using admin address: {self.admin_address}")
        logger.info(
            f"Using platform auth policy ID: {self.token_config.platform_auth_policy}"
        )

        # Find platform auth NFT at admin address
        logger.info(
            f"Looking for platform auth NFT at admin address: {self.admin_address}"
        )
        platform_utxo = await self.platform_auth_finder.find_auth_utxo(
            policy_id=self.token_config.platform_auth_policy,
            platform_address=str(self.admin_address),
        )

        # If not found at admin address, try the platform-specific address
        if not platform_utxo:
            platform_address = (
                "addr_test1wqzlxelqsy5t5n2ftpzu3n6p9n0xg8n83mn9wp9zxrvag0g6ljsgr"
                # "addr_test1wrtqtdlqc66rzl2hcjhq5p0dfmalw944pwcne6p5kafthhqtzp03x"
            )
            logger.info(
                f"Platform auth NFT not found at admin address, trying platform address: {platform_address}"
            )
            platform_utxo = await self.platform_auth_finder.find_auth_utxo(
                policy_id=self.token_config.platform_auth_policy,
                platform_address=platform_address,
            )

        # If still not found, skip the test
        if not platform_utxo:
            pytest.skip("Platform auth NFT not found - please create one first")

        logger.info(
            f"Found platform auth NFT in UTxO: {platform_utxo.input.transaction_id}#{platform_utxo.input.index}"
        )

        # Get platform script
        logger.info("Getting platform script")
        if platform_utxo.output.address:
            platform_address_str = str(platform_utxo.output.address)
            logger.info(f"Using platform address: {platform_address_str}")
            platform_script = await self.platform_auth_finder.get_platform_script(
                platform_address_str
            )
        else:
            logger.info(
                f"Using admin address for platform script: {self.admin_address}"
            )
            platform_script = await self.platform_auth_finder.get_platform_script(
                self.admin_address
            )

        # Build the deployment transaction
        logger.info("Building deployment transaction")
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
            rate_config=self.rate_config,
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

        # Verify deployment by checking for oracle UTxOs
        logger.info("Waiting for UTxOs to be indexed after deployment")
        await asyncio.sleep(10)  # Wait for UTxOs to be indexed

        # Check that UTxOs exist at the oracle script address
        logger.info(
            f"Checking for UTxOs at oracle script address: {self.oracle_script_address}"
        )
        utxos = await self.CHAIN_CONTEXT.get_utxos(self.oracle_script_address)
        logger.info(f"Found {len(utxos)} UTxOs at oracle script address")
        assert (
            len(utxos) > 0
        ), "No UTxOs found at oracle script address after deployment"

        # Store the deployment result for other tests
        logger.info("Storing deployment result for other tests")
        with open("deployment_result.txt", "w") as f:
            f.write(f"Oracle Policy ID: {result.start_result.transaction.id}\n")
            f.write(f"Oracle Script Address: {self.oracle_script_address}\n")

        logger.info("Oracle deployment test completed successfully")
