"""Oracle simulation orchestrator."""

import asyncio
import logging
import secrets
import time

from pycardano import Address

from charli3_offchain_core.cli.aggregate_txs.base import TransactionContext
from charli3_offchain_core.models.oracle_datums import AggregateMessage
from charli3_offchain_core.oracle.aggregate.builder import (
    OdvResult,
    OracleTransactionBuilder,
    RewardsResult,
)

from .models import SimulatedNode, SimulationConfig, SimulationResult
from .utils import create_aggregate_message

logger = logging.getLogger(__name__)


class OracleSimulator:
    """Manages oracle simulation state and operations."""

    def __init__(self, config: SimulationConfig) -> None:
        """Initialize simulator with configuration.

        Args:
            config: Complete simulation configuration
        """
        # Store config
        self.config = config

        # Initialize nodes from key directories
        self.nodes = [
            SimulatedNode.from_key_directory(node_dir)
            for node_dir in config.simulation.get_node_dirs()
        ]

        logger.info("Initialized %d nodes from keys", len(self.nodes))

        # Initialize transaction components
        self.ctx = TransactionContext(config)
        self.tx_builder = OracleTransactionBuilder(
            tx_manager=self.ctx.tx_manager,
            script_address=self.ctx.script_address,
            policy_id=self.ctx.policy_id,
            reward_token_hash=self.ctx.reward_token_hash,
            reward_token_name=self.ctx.reward_token_name,
        )

    async def generate_feeds(self) -> tuple[AggregateMessage, dict]:
        """Generate varied feeds for all nodes.

        Returns:
            Tuple of (aggregate message, node feed data)
        """
        timestamp = int(time.time() * 1000)
        node_feeds = {}

        for idx, node in enumerate(self.nodes):
            # Add random variance to base feed
            variance_amount = self.config.simulation.base_feed * (
                (secrets.randbelow(10000) / 10000.0) * self.config.simulation.variance
            )
            feed_value = self.config.simulation.base_feed + int(variance_amount)

            node_feeds[idx] = {
                "feed": feed_value,
                "verification_key": node.verify_key_bytes.hex(),
                "timestamp": timestamp,
            }

        # Create aggregate message
        message = create_aggregate_message(node_feeds)
        return message, node_feeds

    async def submit_odv(
        self,
        message: AggregateMessage,
        change_address: Address | None = None,
    ) -> OdvResult:
        """Submit ODV transaction.

        Args:
            message: Aggregate message to submit
            change_address: Optional change address

        Returns:
            ODV transaction result

        Raises:
            RuntimeError: If transaction fails
        """
        # Load keys
        signing_key, default_change = self.ctx.load_keys()
        change_address = change_address or default_change

        # Build and submit transaction
        result = await self.tx_builder.build_odv_tx(
            message=message,
            signing_key=signing_key,
            change_address=change_address,
        )

        all_signing_keys = [signing_key] + [node.signing_key for node in self.nodes]

        status, _ = await self.ctx.tx_manager.sign_and_submit(
            result.transaction,
            all_signing_keys,
            wait_confirmation=True,
        )

        if status != "confirmed":
            raise RuntimeError(f"ODV transaction failed: {status}")

        return result

    async def process_rewards(
        self,
        change_address: Address | None = None,
    ) -> RewardsResult:
        """Process rewards for pending ODV.

        Args:
            change_address: Optional change address

        Returns:
            Rewards calculation result

        Raises:
            RuntimeError: If transaction fails
        """
        # Load keys
        signing_key, default_change = self.ctx.load_keys()
        change_address = change_address or default_change

        # Build and submit transaction
        result = await self.tx_builder.build_rewards_tx(
            signing_key=signing_key,
            change_address=change_address,
        )

        status, _ = await self.ctx.tx_manager.sign_and_submit(
            result.transaction,
            [signing_key],
            wait_confirmation=True,
        )

        if status != "confirmed":
            raise RuntimeError(f"Rewards transaction failed: {status}")

        return result

    async def run_simulation(self) -> SimulationResult:
        """Run complete oracle simulation.

        Returns:
            SimulationResult containing transaction results

        Raises:
            Exception: If simulation fails
        """
        try:
            # Generate and submit ODV
            logger.info("Generating feeds and submitting ODV...")
            message, feeds = await self.generate_feeds()
            odv_result = await self.submit_odv(message)

            # Wait configured time
            await asyncio.sleep(self.config.simulation.wait_time)

            # Process rewards
            rewards = await self.process_rewards()

            return SimulationResult(
                nodes=self.nodes,
                feeds=feeds,
                odv_tx=str(odv_result.transaction.id),
                rewards=rewards,
            )
        except Exception as e:
            logger.error("Simulation failed: %s", e)
            raise
