"""Oracle simulation orchestrator."""

import asyncio
import logging
import secrets
import time

from pycardano import Address

from charli3_offchain_core.cli.txs.base import TransactionContext, TxConfig
from charli3_offchain_core.models.oracle_datums import AggregateMessage
from charli3_offchain_core.oracle.transactions.builder import (
    OdvResult,
    OracleTransactionBuilder,
    RewardsResult,
)

from .models import SimulatedNode, SimulationConfig, SimulationResult
from .utils import create_aggregate_message

logger = logging.getLogger(__name__)


class OracleSimulator:
    """Manages oracle simulation state and operations."""

    def __init__(
        self,
        tx_config: TxConfig,
        sim_config: SimulationConfig,
    ) -> None:
        """Initialize simulator with configuration.

        Args:
            tx_config: Transaction configuration
            sim_config: Simulation parameters
        """
        self.tx_config = tx_config
        self.sim_config = sim_config
        self.nodes = [SimulatedNode() for _ in range(sim_config.node_count)]

        # Initialize transaction components
        self.ctx = TransactionContext(tx_config)
        self.tx_builder = OracleTransactionBuilder(
            tx_manager=self.ctx.tx_manager,
            script_address=self.ctx.script_address,
            policy_id=self.ctx.policy_id,
            oracle_config=None,  # Not needed for simulation
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
            variance_amount = self.sim_config.base_feed * (
                (secrets.randbelow(10000) / 10000.0) * self.sim_config.variance
            )
            feed_value = self.sim_config.base_feed + int(variance_amount)

            # Sign feed value
            msg_timestamp, signature = node.sign_feed(feed_value, timestamp)
            node_feeds[idx] = {
                "feed": feed_value,
                "signature": signature.hex(),
                "verification_key": node.verification_key.to_primitive().hex(),
                "timestamp": msg_timestamp,
            }

        # Create aggregate message
        message = create_aggregate_message(node_feeds, timestamp)
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
        """
        # Load keys
        signing_key, default_change = self.ctx.load_keys()
        change_address = change_address or default_change

        # Build and submit transaction
        result = await self.tx_builder.build_odv_tx(
            message=message,
            settings=None,  # Will be loaded from chain
            signing_key=signing_key,
            change_address=change_address,
        )

        status, _ = await self.ctx.tx_manager.sign_and_submit(
            result.transaction,
            [signing_key],
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
        """
        # Load keys
        signing_key, default_change = self.ctx.load_keys()
        change_address = change_address or default_change

        # Build and submit transaction
        result = await self.tx_builder.build_rewards_tx(
            settings=None,  # Will be loaded from chain
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
        """
        # Generate and submit ODV
        message, feeds = await self.generate_feeds()
        odv_result = await self.submit_odv(message)

        # Wait configured time
        await asyncio.sleep(self.sim_config.wait_time)

        # Process rewards
        rewards = await self.process_rewards()

        return SimulationResult(
            nodes=self.nodes,
            feeds=feeds,
            odv_tx=str(odv_result.transaction.id),
            rewards=rewards,
        )
