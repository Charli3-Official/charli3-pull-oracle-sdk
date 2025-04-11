"""Test node collection of rewards in the Charli3 ODV Oracle."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pycardano import (
    Address,
    AssetName,
    PaymentExtendedSigningKey,
    PaymentVerificationKey,
    ScriptHash,
    UTxO,
    VerificationKeyHash,
)

from charli3_offchain_core.cli.base import LoadedKeys
from charli3_offchain_core.oracle.rewards.orchestrator import RewardOrchestrator
from charli3_offchain_core.oracle.utils import state_checks

from .async_utils import async_retry
from .base import TEST_RETRIES, TestBase
from .test_utils import logger, wait_for_indexing


@pytest.mark.run(order=4)
class TestNodeCollect(TestBase):
    """Test node collection of rewards in the Charli3 ODV Oracle."""

    def setup_method(self, method: Callable) -> None:
        """Set up the test environment."""
        logger.info("Setting up TestNodeCollect environment")
        super().setup_method(method)

        # Create reward orchestrator for node collect operations
        self.reward_orchestrator = RewardOrchestrator(
            chain_query=self.chain_query,
            tx_manager=self.tx_manager,
            script_address=self.oracle_script_address,
        )

        # Node keys directory for loading test node keys
        self.node_keys_dir = Path("./node_keys")
        if not self.node_keys_dir.exists():
            logger.warning("Node keys directory not found. Some tests may be skipped.")

        # Load a test node key to use for rewards collection
        self.node_keys = self._load_node_key()

        logger.info("TestNodeCollect setup complete")

    def _load_node_key(
        self,
    ) -> (
        tuple[
            PaymentExtendedSigningKey,
            PaymentVerificationKey,
            PaymentExtendedSigningKey,
            PaymentVerificationKey,
            Address,
        ]
        | None
    ):
        """Load a node key for testing."""
        try:
            # Get the first node directory
            node_dirs = sorted(self.node_keys_dir.glob("node_*"))
            if not node_dirs:
                logger.warning("No node keys found in node_keys directory")
                return None

            node_dir = node_dirs[0]

            # Load the signing key
            feed_skey = PaymentExtendedSigningKey.load(node_dir / "feed.skey")

            # Load the verification key
            feed_vkey = PaymentVerificationKey.load(node_dir / "feed.vkey")

            # Load the verification key hash
            feed_vkh = VerificationKeyHash(
                bytes.fromhex((node_dir / "feed.vkh").read_text().strip())
            )

            # Load the payment signing key
            payment_skey = PaymentExtendedSigningKey.load(node_dir / "payment.skey")
            payment_vkey = PaymentVerificationKey.load(node_dir / "payment.vkey")

            # Load the payment verification key hash
            payment_vkh = VerificationKeyHash(
                bytes.fromhex((node_dir / "payment.vkh").read_text().strip())
            )

            # Derive the node's payment address
            node_address = Address(
                payment_part=payment_vkh,
                network=self.NETWORK,
            )

            logger.info(
                f"Loaded node key: feed_vkh={feed_vkh}, payment_vkh={payment_vkh}"
            )
            logger.info(f"Node payment address: {node_address}")

            return (
                feed_skey,
                feed_vkey,
                payment_skey,
                payment_vkey,
                node_address,
            )

        except Exception as e:
            logger.error(f"Failed to load node key: {e}")
            return None

    @pytest.mark.asyncio
    @async_retry(tries=TEST_RETRIES, delay=5)
    async def test_node_collect(self) -> None:
        """Test node collection of rewards."""
        logger.info("Starting node collect test")

        # Skip test if we couldn't load a node key
        if not self.node_keys:
            pytest.skip("No node keys available for testing")

        # Mock the confirm_withdrawal_amount_and_address function
        with patch(
            "charli3_offchain_core.oracle.rewards.node_collect_builder.confirm_withdrawal_amount_and_address",
            new=AsyncMock(return_value=self.node_keys[-1]),
        ):
            # Unpack the node keys
            (
                _,
                node_feed_vkey,
                node_payment_skey,
                node_payment_vkey,
                node_address,
            ) = self.node_keys

            # 1. First, check if there are rewards to collect
            # Get UTxOs at script address
            utxos = await self.chain_query.get_utxos(self.oracle_script_address)

            # Check reward account
            try:
                reward_datum, _ = state_checks.get_reward_account_by_policy_id(
                    utxos,
                    ScriptHash(bytes.fromhex(self.token_config.oracle_policy)),
                )

                # Get settings to find registered nodes
                settings_datum, _ = state_checks.get_oracle_settings_by_policy_id(
                    utxos,
                    ScriptHash(bytes.fromhex(self.token_config.oracle_policy)),
                )

                # Check if our node is registered
                registered_nodes = list(settings_datum.nodes.node_map.keys())
                node_feed_vkh = node_feed_vkey.hash()
                logger.info(f"Node feed VKH: {node_feed_vkh}")

                if node_feed_vkh not in registered_nodes:
                    logger.warning(
                        f"Test node with VKH {node_feed_vkh} is not registered in the oracle"
                    )

                    # Try to find the index of a node that has rewards
                    node_index = -1
                    for i, _ in enumerate(registered_nodes):
                        if (
                            i < len(reward_datum.nodes_to_rewards)
                            and reward_datum.nodes_to_rewards[i] > 0
                        ):
                            node_index = i
                            break

                    if node_index == -1:
                        logger.info(
                            "No registered nodes with rewards found, skipping test"
                        )
                        pytest.skip("No registered nodes with rewards found")

                    # We can't actually run the test since we don't have the keys for a registered node
                    logger.info(
                        "Cannot run test with available node keys, skipping test"
                    )
                    pytest.skip("Cannot run test with available node keys")

                # Get initial balance of the node's address for verification
                initial_utxos = await self.chain_query.get_utxos(node_address)

                # Calculate initial balance (tokens or ADA)
                initial_balance = self._calculate_balance(initial_utxos)
                logger.info(f"Node initial balance: {initial_balance}")

                # Find the index of our node in the nodes list
                node_index = registered_nodes.index(node_feed_vkh)

                # Check if this node has rewards to collect
                if (
                    node_index >= len(reward_datum.nodes_to_rewards)
                    or reward_datum.nodes_to_rewards[node_index] == 0
                ):
                    logger.info(
                        f"No rewards available for test node {node_feed_vkh}, skipping test"
                    )
                    pytest.skip("No rewards available for test node")

                # Record initial reward amount for verification
                initial_reward = reward_datum.nodes_to_rewards[node_index]
                logger.info(
                    f"Test node has {initial_reward} rewards available for collection"
                )

                # Create LoadedKeys with node keys for testing
                payment_vkh = settings_datum.nodes.node_map[node_feed_vkh]
                payment_address = Address(
                    payment_part=payment_vkh,
                    network=self.NETWORK,
                )

                loaded_keys = LoadedKeys(
                    payment_sk=node_payment_skey,
                    payment_vk=node_payment_vkey,
                    stake_vk=None,
                    address=payment_address,
                )

                # 2. Use the reward orchestrator to collect rewards
                result = await self.reward_orchestrator.collect_node_oracle(
                    oracle_policy=self.token_config.oracle_policy,
                    tokens=self.token_config,
                    loaded_key=loaded_keys,
                    network=self.NETWORK,
                )

                # 3. Check the result
                if result is not None:
                    # If we have a transaction, we can test submission
                    assert (
                        result.transaction is not None
                    ), "Should have transaction for node collect"

                    # 4. Submit the transaction
                    logger.info(
                        f"Submitting node collect transaction: {result.transaction.id}"
                    )
                    status, _ = await self.tx_manager.sign_and_submit(
                        result.transaction,
                        [node_payment_skey],
                        wait_confirmation=True,
                    )

                    assert (
                        status == "confirmed"
                    ), f"Node collect transaction failed with status: {status}"
                    logger.info(
                        f"Node collect transaction confirmed: {result.transaction.id}"
                    )

                    # 5. Wait for indexing
                    await wait_for_indexing(10)

                    # 6. Verify the reward was collected
                    await self.verify_reward_collection(
                        node_feed_vkh=node_feed_vkh,
                        node_address=payment_address,
                        initial_balance=initial_balance,
                        initial_reward=initial_reward,
                    )

                    logger.info("Node collect test completed successfully")

            except Exception as e:
                logger.error(f"Error in node collect test: {e}")
                raise

    def _calculate_balance(self, utxos: list[UTxO]) -> int:
        """Calculate the balance of an address (either tokens or ADA)."""
        if (
            self.token_config.reward_token_policy
            and self.token_config.reward_token_name
        ):
            # Calculate token balance
            script_hash = ScriptHash(
                bytes.fromhex(self.token_config.reward_token_policy)
            )
            token_name = AssetName(bytes.fromhex(self.token_config.reward_token_name))

            total = 0
            for utxo in utxos:
                if (
                    utxo.output.amount.multi_asset
                    and script_hash in utxo.output.amount.multi_asset
                    and token_name in utxo.output.amount.multi_asset[script_hash]
                ):
                    total += utxo.output.amount.multi_asset[script_hash][token_name]

            return total
        else:
            # Calculate ADA balance
            return sum(utxo.output.amount.coin for utxo in utxos)

    @async_retry(tries=TEST_RETRIES, delay=5)
    async def verify_reward_collection(
        self,
        node_feed_vkh: VerificationKeyHash,
        node_address: Address,
        initial_balance: int,
        initial_reward: int,
    ) -> None:
        """Verify that rewards were correctly collected."""
        logger.info("Verifying reward collection")

        # Get UTxOs at script address
        utxos = await self.chain_query.get_utxos(self.oracle_script_address)

        # Check reward account
        new_reward_datum, _ = state_checks.get_reward_account_by_policy_id(
            utxos,
            ScriptHash(bytes.fromhex(self.token_config.oracle_policy)),
        )

        # Get settings to find registered nodes
        settings_datum, _ = state_checks.get_oracle_settings_by_policy_id(
            utxos,
            ScriptHash(bytes.fromhex(self.token_config.oracle_policy)),
        )

        # Find the index of our node in the nodes list
        registered_nodes = list(settings_datum.nodes.node_map.keys())
        node_index = registered_nodes.index(node_feed_vkh)

        # 1. Verify rewards were zeroed out in the reward account
        assert new_reward_datum is not None, "Reward account datum not found"
        assert node_index < len(
            new_reward_datum.nodes_to_rewards
        ), "Node index out of range"

        new_reward = new_reward_datum.nodes_to_rewards[node_index]
        logger.info(f"Node reward after collection: {new_reward}")
        assert (
            new_reward == 0
        ), f"Node reward should be zeroed out, but got {new_reward}"

        # 2. Verify the node's address received the rewards
        new_utxos = await self.chain_query.get_utxos(node_address)
        new_balance = self._calculate_balance(new_utxos)

        logger.info(f"Node new balance: {new_balance}")

        # The new balance should be greater than or equal to initial balance + reward
        # We can't do exact matching because of transaction fees
        expected_minimum = initial_balance + initial_reward

        # For ADA rewards, we need to account for transaction fees
        if not (
            self.token_config.reward_token_policy
            and self.token_config.reward_token_name
        ):
            # For ADA, we'll just check that the balance increased
            assert (
                new_balance > initial_balance
            ), f"Node balance should increase, but got {initial_balance} -> {new_balance}"
        else:
            # For tokens, we should get the exact amount
            assert new_balance >= expected_minimum, (
                f"Node should receive at least {expected_minimum} tokens, "
                f"but balance is only {new_balance} (from {initial_balance})"
            )

        logger.info(f"Verified reward collection: {initial_balance} -> {new_balance}")
