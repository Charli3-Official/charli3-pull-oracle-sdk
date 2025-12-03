"""Test ODV aggregate transaction and reward processing."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pycardano import (
    AssetName,
    PaymentExtendedSigningKey,
    PaymentVerificationKey,
    ScriptHash,
    TransactionBuilder,
    TransactionOutput,
    VerificationKeyHash,
)

from charli3_offchain_core.cli.node_keys.generate_node_keys_command import (
    generate_node_keys,
    load_nodes_config,
    save_node_keys,
)
from charli3_offchain_core.models.message import (
    OracleNodeMessage,
    SignedOracleNodeMessage,
)
from charli3_offchain_core.models.oracle_datums import (
    AggState,
    PriceData,
)
from charli3_offchain_core.oracle.aggregate.builder import (
    OracleTransactionBuilder,
)
from charli3_offchain_core.oracle.utils import asset_checks, common, state_checks
from charli3_offchain_core.oracle.utils.calc_methods import median

from .async_utils import async_retry
from .base import TEST_RETRIES, TestBase
from .test_utils import logger, wait_for_indexing


@pytest.mark.run(order=3)
class TestAggregate(TestBase):
    """Test ODV aggregate transaction and reward processing."""

    def setup_method(self, method: Callable) -> None:
        """Set up the ODV aggregate test environment."""
        logger.info("Setting up TestAggregate environment")
        super().setup_method(method)

        # Set up node keys and simulate multiple oracle nodes
        self.node_keys_dir = Path("./node_keys")
        self.base_feed = 1000
        self.feed_variance = 0.02

        # Prepare node keys for testing
        self.prepare_node_keys()

        # Prepare proper reward token configuration
        reward_token_hash = None
        reward_token_name = None

        if (
            self.token_config.reward_token_policy
            and self.token_config.reward_token_name
        ):
            logger.info(
                f"Using reward tokens for testing (policy: {self.token_config.reward_token_policy}, "
                f"name: {self.token_config.reward_token_name})"
            )
            reward_token_hash = ScriptHash(
                bytes.fromhex(self.token_config.reward_token_policy)
            )
            reward_token_name = bytes.fromhex(self.token_config.reward_token_name)
        else:
            logger.info("No reward tokens configured, using ADA for testing")

        # Create oracle transaction builder for ODV
        self.odv_builder = OracleTransactionBuilder(
            tx_manager=self.tx_manager,
            script_address=self.oracle_script_address,
            policy_id=ScriptHash(bytes.fromhex(self.token_config.oracle_policy)),
            reward_token_hash=reward_token_hash,
            reward_token_name=(
                AssetName(reward_token_name) if reward_token_name else None
            ),
        )

        logger.info("TestAggregate setup complete")

    def prepare_node_keys(self) -> None:
        """Prepare node keys for testing."""
        if not self.node_keys_dir.exists():
            logger.info("Node keys directory not found, generating test keys")
            self.node_keys_dir.mkdir(parents=True, exist_ok=True)

            # Use a test mnemonic to generate keys
            test_mnemonic = "test test test test test test test test test test test test test test test test test test test test test test test sauce"

            # Generate node keys
            nodes = generate_node_keys(
                mnemonic=test_mnemonic,
                start_index=0,
                count=9,
            )

            # Save keys to directory
            save_node_keys(nodes, self.node_keys_dir)
            logger.info(f"Generated {len(nodes)} node keys")
        else:
            logger.info(f"Using existing node keys from {self.node_keys_dir}")

        # Load node configuration
        self.nodes_config = load_nodes_config(self.node_keys_dir)
        logger.info(f"Loaded {len(self.nodes_config.nodes)} nodes from config")

        # Load node signing keys
        self.node_keys = []
        for node_dir in sorted(self.node_keys_dir.glob("node_*")):
            try:
                skey = PaymentExtendedSigningKey.load(str(node_dir / "feed.skey"))
                vkey = PaymentVerificationKey.load(str(node_dir / "feed.vkey"))
                feed_vkh = VerificationKeyHash(
                    bytes.fromhex((node_dir / "feed.vkh").read_text().strip())
                )
                self.node_keys.append((skey, vkey, feed_vkh))
                logger.info(f"Loaded node key: {feed_vkh}")
            except Exception as e:
                logger.warning(f"Failed to load key from {node_dir}: {e}")

    async def create_fuel_utxo(self, amount: int = 50_000_000) -> None:
        """Create a large UTxO to ensure sufficient ADA for fees and change."""
        logger.info(f"Creating fuel UTxO of {amount} lovelace")

        builder = TransactionBuilder(self.tx_manager.chain_query.context)
        builder.add_input_address(self.admin_address)

        # Create output to self
        builder.add_output(TransactionOutput(address=self.admin_address, amount=amount))

        try:
            tx = builder.build_and_sign(
                [self.admin_signing_key], change_address=self.admin_address
            )

            logger.info(f"Submitting fuel creation transaction: {tx.id}")
            status, _ = await self.tx_manager.chain_query.submit_tx(
                tx, wait_confirmation=True
            )

            if status != "confirmed":
                logger.warning(f"Fuel creation failed with status: {status}")
            else:
                logger.info("Fuel UTxO created successfully")
                await wait_for_indexing()

        except Exception as e:
            logger.warning(f"Failed to create fuel UTxO: {e}")

    def generate_feed_value(self, base: int, variance: float) -> int:
        """Generate feed value with random variance."""
        import random

        variance_amount = base * random.uniform(0, variance)
        # Randomly choose if variance is positive or negative
        if random.choice([True, False]):
            return base + int(variance_amount)
        return base - int(variance_amount)

    def generate_simulated_feeds(self) -> list[SignedOracleNodeMessage]:
        """Generate simulated node feeds."""
        feeds = []

        # Get current time for all messages
        current_time = self.tx_manager.chain_query.get_current_posix_chain_time_ms()
        policy_id_bytes = bytes.fromhex(self.token_config.oracle_policy)

        for skey, vkey, _ in self.node_keys:
            # Generate feed with random variance
            feed_value = self.generate_feed_value(self.base_feed, self.feed_variance)

            # Create oracle message
            message = OracleNodeMessage(
                feed=feed_value,
                timestamp=current_time,
                oracle_nft_policy_id=policy_id_bytes,
            )

            # Sign message
            signature = message.sign(skey)

            # Create signed message
            signed_message = SignedOracleNodeMessage(
                message=message,
                signature=signature,
                verification_key=vkey,
            )

            # Verify signature
            signed_message.validate_signature()

            feeds.append(signed_message)
            logger.info(f"Generated feed value: {feed_value} for node: {vkey.hash()}")

        return feeds

    @pytest.mark.asyncio
    @pytest.mark.run(order=3.1)
    async def test_odv_transaction(self) -> None:
        """Test the ODV transaction with simulated node feeds."""
        logger.info("Starting ODV transaction test")

        # Ensure we have a good UTxO for fees
        await self.create_fuel_utxo()

        # 1. Load transaction keys
        signing_key, change_address = self.admin_signing_key, self.admin_address

        # 2. Generate simulated node feeds
        node_messages = self.generate_simulated_feeds()

        # 3. Create aggregate message using core module utility
        aggregate_message = common.build_aggregate_message(
            node_messages,
        )

        # 4. Calculate the expected median value
        feeds = list(aggregate_message.node_feeds_sorted_by_feed.values())
        expected_median = median(feeds, len(feeds))
        logger.info(f"Calculated median value: {expected_median}")

        # 5. Build ODV transaction
        odv_result = await self.odv_builder.build_odv_tx(
            message=aggregate_message,
            signing_key=signing_key,
            change_address=change_address,
        )

        # 6. Extract node signing keys
        node_signing_keys = [skey for skey, _, _ in self.node_keys]

        # 7. Submit transaction with all signing keys
        all_signing_keys = [signing_key, *node_signing_keys]

        logger.info(
            f"Submitting ODV transaction with {len(all_signing_keys)} signing keys: {odv_result.transaction.id}"
        )
        logger.info(f"Transaction details: {odv_result.transaction}")

        status, _ = await self.tx_manager.sign_and_submit(
            odv_result.transaction,
            all_signing_keys,
            wait_confirmation=True,
        )

        assert status == "confirmed", f"ODV transaction failed with status: {status}"
        logger.info(f"ODV transaction confirmed: {odv_result.transaction.id}")

        # 8. Wait for indexing before verification
        await wait_for_indexing(10)

        # 9. Verify state changes
        await self.verify_odv_outputs(expected_median)

        logger.info("ODV transaction test completed successfully")

    @async_retry(tries=TEST_RETRIES, delay=5)
    async def verify_odv_outputs(self, expected_median: int) -> None:
        """Verify that ODV outputs are created correctly."""
        logger.info("Verifying ODV transaction outputs")

        # Get UTxOs at script address
        utxos = await self.chain_query.get_utxos(self.oracle_script_address)

        # Check for valid agg state UTxO
        agg_states = asset_checks.filter_utxos_by_token_name(
            utxos,
            ScriptHash(bytes.fromhex(self.token_config.oracle_policy)),
            "C3AS",
        )

        # Convert CBOR to AggState objects
        agg_states = state_checks.convert_cbor_to_agg_states(agg_states)

        # Find non-empty agg states
        non_empty_agg_states = [
            utxo
            for utxo in agg_states
            if utxo.output.datum
            and isinstance(utxo.output.datum, AggState)
            and not utxo.output.datum.price_data.is_empty
        ]

        assert len(non_empty_agg_states) > 0, "No non-empty agg state UTxOs found"

        # Verify the agg state has the correct feed value
        latest_agg_state: PriceData = non_empty_agg_states[0].output.datum.price_data
        agg_state_feed = latest_agg_state.get_price
        assert (
            agg_state_feed == expected_median
        ), f"AggState feed mismatch: {agg_state_feed} vs {expected_median}"

        # Verify the agg state has a valid expiry timestamp
        current_time = self.tx_manager.chain_query.get_current_posix_chain_time_ms()
        expiry = latest_agg_state.get_expiration_time
        assert (
            expiry > current_time
        ), f"Invalid expiry timestamp: {expiry} vs {current_time}"

        logger.info("ODV outputs verified successfully")

    @async_retry(tries=TEST_RETRIES, delay=5)
    async def verify_reward_distribution(self, rewards_result: Any) -> None:
        """Verify that rewards are distributed correctly."""
        logger.info("Verifying reward distribution")

        # Get UTxOs at script address
        utxos = await self.chain_query.get_utxos(self.oracle_script_address)

        # Check reward account exists
        _, reward_account_utxo = state_checks.get_reward_account_by_policy_id(
            utxos,
            ScriptHash(bytes.fromhex(self.token_config.oracle_policy)),
        )

        assert reward_account_utxo is not None, "Reward account UTxO not found"

        # Get reward distribution
        reward_distribution = rewards_result.reward_distribution
        assert len(reward_distribution) > 0, "No rewards were distributed"

        # Verify total reward amount
        total_rewards = sum(reward_distribution.values())
        assert total_rewards > 0, "Total rewards should be greater than zero"

        # Check reward tokens in reward account if configured
        if (
            self.token_config.reward_token_policy
            and self.token_config.reward_token_name
        ):
            script_hash = ScriptHash(
                bytes.fromhex(self.token_config.reward_token_policy)
            )
            token_name = bytes.fromhex(self.token_config.reward_token_name)

            if (
                reward_account_utxo.output.amount.multi_asset
                and script_hash in reward_account_utxo.output.amount.multi_asset
                and token_name
                in reward_account_utxo.output.amount.multi_asset[script_hash]
            ):
                token_amount = reward_account_utxo.output.amount.multi_asset[
                    script_hash
                ][token_name]
                logger.info(f"Reward account token amount: {token_amount}")
                assert token_amount > 0, "Token amount should be greater than zero"
            else:
                logger.info("No tokens found in reward account, may be using ADA")
        else:
            # If no tokens configured, verify ADA amount
            logger.info(
                f"Reward account ADA amount: {reward_account_utxo.output.amount.coin}"
            )

        # Verify the reward account datum nodes_to_rewards mapping is populated
        reward_account_datum = reward_account_utxo.output.datum.datum
        # nodes_to_rewards is a dict mapping FeedVkh to amount
        assert (
            sum(reward_account_datum.nodes_to_rewards.values()) > 0
        ), "No rewards in nodes_to_rewards"

        # Log reward distribution details
        logger.info(f"Total rewards distributed: {total_rewards}")
        logger.info(f"Nodes with rewards: {len(reward_distribution)}")

        logger.info("Reward distribution verified successfully")
