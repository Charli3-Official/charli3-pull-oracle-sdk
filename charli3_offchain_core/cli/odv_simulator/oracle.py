"""Oracle simulation orchestrator."""

import asyncio
import logging

from pycardano import (
    Address,
    Transaction,
    TransactionWitnessSet,
    VerificationKeyWitness,
)

from charli3_offchain_core.cli.aggregate_txs.base import TransactionContext
from charli3_offchain_core.cli.config.formatting import (
    print_header,
    print_progress,
    print_status,
)
from charli3_offchain_core.models.base import TxValidityInterval
from charli3_offchain_core.models.client import OdvFeedRequest, OdvTxSignatureRequest
from charli3_offchain_core.models.message import SignedOracleNodeMessage
from charli3_offchain_core.oracle.aggregate.builder import (
    OdvResult,
    OracleTransactionBuilder,
    RewardsResult,
)
from charli3_offchain_core.oracle.utils.common import build_aggregate_message

from .models import SimulatedNode, SimulationConfig, SimulationResult
from .node import NodeSimulator

logger = logging.getLogger(__name__)


class OracleSimulator:
    """Orchestrates oracle simulation operations."""

    def __init__(self, config: SimulationConfig) -> None:
        """Initialize simulator with configuration."""
        self.config = config

        print_progress("Initializing nodes from configuration")

        self.nodes = [
            SimulatedNode.from_key_directory(node_dir)
            for node_dir in config.simulation.get_node_dirs()
        ]

        self.node_simulators = {
            node.hex_feed_vkh: NodeSimulator(
                node=node,
                base_feed=config.simulation.base_feed,
                variance=config.simulation.variance,
            )
            for node in self.nodes
        }

        print_progress(f"Successfully initialized {len(self.nodes)} node simulators")
        print_progress("Setting up transaction context and builder")

        self.ctx = TransactionContext(config)
        self.tx_builder = OracleTransactionBuilder(
            tx_manager=self.ctx.tx_manager,
            script_address=self.ctx.script_address,
            policy_id=self.ctx.policy_id,
            reward_token_hash=self.ctx.reward_token_hash,
            reward_token_name=self.ctx.reward_token_name,
        )
        print_status("Success", "Transaction setup complete", success=True)

    async def collect_feed_updates(self) -> dict[str, SignedOracleNodeMessage]:
        """Collect feed updates from all nodes."""
        print_progress("Calculating validity window for feed updates")
        validity_window = self.ctx.tx_manager.calculate_validity_window(
            self.config.odv_validity_length
        )

        feed_request = OdvFeedRequest(
            oracle_nft_policy_id=self.config.policy_id,
            tx_validity_interval=TxValidityInterval(
                start=validity_window.validity_start, end=validity_window.validity_end
            ),
        )

        print_progress("Requesting feed values from all nodes")
        tasks = [
            node.handle_feed_request(feed_request)
            for node in self.node_simulators.values()
        ]

        responses = await asyncio.gather(*tasks)
        feed_responses = {pkh: msg for pkh, msg in responses if msg is not None}

        print_status(
            "Feed Updates",
            f"Received {len(feed_responses)} node responses",
            success=True,
        )
        return feed_responses

    async def collect_signatures(
        self, node_messages: dict[str, SignedOracleNodeMessage], tx: Transaction
    ) -> dict[str, str]:
        """Collect transaction signatures from all nodes."""
        print_progress("Preparing transaction signature request")
        tx_request = OdvTxSignatureRequest(
            node_messages=node_messages,
            tx_cbor=tx.to_cbor_hex(),
        )

        print_progress("Requesting transaction signatures from nodes")
        tasks = [
            node.handle_sign_request(tx_request)
            for node in self.node_simulators.values()
        ]

        responses = await asyncio.gather(*tasks)

        signed_txs = {}
        for node_pkh, response in zip(self.node_simulators.keys(), responses):
            if response is not None:
                signed_txs[node_pkh] = response

        print_status(
            "Signed Tx Responses",
            f"Received {len(signed_txs)} node signatures",
            success=True,
        )
        return signed_txs

    def attach_tx_signatures(
        self,
        tx_cbor: str,
        signed_txs: dict[str, Transaction],
    ) -> Transaction:
        """Attach collected signatures to transaction."""
        transaction = Transaction.from_cbor(tx_cbor)
        if transaction.transaction_witness_set is None:
            transaction.transaction_witness_set = TransactionWitnessSet()

        try:
            transaction.transaction_witness_set.vkey_witnesses = []

            for vkh, signed_tx in signed_txs.items():
                if (
                    isinstance(signed_tx.transaction_witness_set, TransactionWitnessSet)
                    and signed_tx.transaction_witness_set.vkey_witnesses
                    and isinstance(
                        signed_tx.transaction_witness_set.vkey_witnesses[0],
                        VerificationKeyWitness,
                    )
                ):

                    witness = signed_tx.transaction_witness_set.vkey_witnesses[0]

                    if vkh in self.node_simulators:
                        transaction.transaction_witness_set.vkey_witnesses.append(
                            witness
                        )

            print_status(
                "Witnesses Attachment",
                f"{len(transaction.transaction_witness_set.vkey_witnesses)} successfully attached",
                success=True,
            )
            return transaction

        except Exception as e:
            logger.error(f"Error attaching signatures: {e}")
            raise

    async def submit_odv(
        self,
        node_messages: dict[str, SignedOracleNodeMessage],
        change_address: Address | None = None,
    ) -> OdvResult:
        """Submit ODV transaction."""
        print_progress("Loading transaction keys")
        signing_key, default_change = self.ctx.load_keys()
        change_address = change_address or default_change

        print_progress("Building aggregate message from node responses")
        validity_window = self.ctx.tx_manager.calculate_validity_window(
            self.config.odv_validity_length
        )
        aggregate_message = build_aggregate_message(
            list(node_messages.values()), validity_window.current_time
        )
        print_status(
            "Aggregate Message",
            f"Created with {aggregate_message.node_feeds_count} feeds and {aggregate_message.timestamp} timestamp",
            success=True,
        )

        print_progress("Building ODV transaction")
        result = await self.tx_builder.build_odv_tx(
            message=aggregate_message,
            signing_key=signing_key,
            change_address=change_address,
            validity_window=validity_window,
        )

        print_progress("Collecting node signatures for transaction")
        signed_txs = await self.collect_signatures(node_messages, result.transaction)

        print_progress("Adding node signatures to transaction")
        transaction = self.attach_tx_signatures(
            result.transaction.to_cbor_hex(), signed_txs
        )

        print_progress("Submitting final ODV transaction")
        status, _ = await self.ctx.tx_manager.sign_and_submit(
            transaction,
            [signing_key],
            wait_confirmation=True,
        )

        if status != "confirmed":
            raise RuntimeError(f"ODV transaction failed: {status}")

        print_status("ODV Submission", "Completed successfully", success=True)
        return result

    async def process_rewards(
        self,
        change_address: Address | None = None,
    ) -> RewardsResult:
        """Process rewards for pending ODV."""
        print_progress("Loading keys for rewards processing")
        signing_key, default_change = self.ctx.load_keys()
        change_address = change_address or default_change

        print_progress("Building rewards transaction")
        result = await self.tx_builder.build_rewards_tx(
            signing_key=signing_key,
            change_address=change_address,
        )

        print_progress("Submitting rewards transaction")
        status, _ = await self.ctx.tx_manager.sign_and_submit(
            result.transaction,
            [signing_key],
            wait_confirmation=True,
        )

        if status != "confirmed":
            raise RuntimeError(f"Rewards transaction failed: {status}")
        print_status("Rewards Processing", "Completed successfully", success=True)
        return result

    async def run_simulation(self) -> SimulationResult:
        """Run complete oracle simulation."""
        try:
            print_header("Phase 1: Feed Collection")
            node_messages = await self.collect_feed_updates()

            if not node_messages:
                raise RuntimeError("No valid node responses received")

            print_header("Phase 2: ODV Transaction")
            odv_result = await self.submit_odv(node_messages)

            print_progress(
                f"\nWaiting {self.config.simulation.wait_time} milliseconds before processing rewards"
            )
            await asyncio.sleep(self.config.simulation.wait_time / 1000)

            print_progress("Phase 3: Rewards Processing")
            rewards = await self.process_rewards()
            print_status("Simulation", "Completed successfully", success=True)
            return SimulationResult(
                nodes=self.nodes,
                feeds={
                    i: {
                        "feed": msg.message.feed,
                        "verification_key": msg.verification_key.to_cbor().hex(),
                        "timestamp": msg.message.timestamp,
                    }
                    for i, msg in enumerate(node_messages.values())
                },
                odv_tx=str(odv_result.transaction.id),
                rewards=rewards,
            )

        except Exception as e:
            logger.error("Simulation failed: %s", e)
            raise
