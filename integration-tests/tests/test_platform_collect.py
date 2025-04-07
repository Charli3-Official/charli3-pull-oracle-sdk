"""Test platform collection of rewards in the Charli3 ODV Oracle."""

from collections.abc import Callable

import pytest
from pycardano import (
    ScriptHash,
    UTxO,
)

from charli3_offchain_core.cli.base import LoadedKeys
from charli3_offchain_core.models.oracle_datums import (
    RewardAccountDatum,
)
from charli3_offchain_core.oracle.rewards.orchestrator import RewardOrchestrator
from charli3_offchain_core.oracle.utils import state_checks

from .async_utils import async_retry
from .base import TEST_RETRIES, TestBase
from .test_utils import find_platform_auth_nft, logger, wait_for_indexing


@pytest.mark.run(order=5)
class TestPlatformCollect(TestBase):
    """Test platform collection of rewards in the Charli3 ODV Oracle."""

    def setup_method(self, method: Callable) -> None:
        """Set up the test environment."""
        logger.info("Setting up TestPlatformCollect environment")
        super().setup_method(method)

        # Create reward orchestrator for platform collect operations
        self.reward_orchestrator = RewardOrchestrator(
            chain_query=self.chain_query,
            tx_manager=self.tx_manager,
            script_address=self.oracle_script_address,
        )

        logger.info("TestPlatformCollect setup complete")

    @pytest.mark.asyncio
    @async_retry(tries=TEST_RETRIES, delay=5)
    async def test_platform_collect(self) -> None:
        """Test platform collection of rewards."""
        logger.info("Starting platform collect test")

        # 1. First, check if there are rewards to collect
        # Get UTxOs at script address
        utxos = await self.chain_query.get_utxos(self.oracle_script_address)

        # Check reward account
        try:
            reward_datum, reward_utxo = state_checks.get_reward_account_by_policy_id(
                utxos,
                ScriptHash(bytes.fromhex(self.token_config.oracle_policy)),
            )

            # Get initial reward account state for verification
            initial_reward_amount = self._get_reward_account_amount(reward_utxo)
            logger.info(f"Initial reward account amount: {initial_reward_amount}")

            # Check if we have rewards in excess of node allocations that can be collected by platform
            total_node_rewards = sum(reward_datum.nodes_to_rewards)
            logger.info(f"Total allocated node rewards: {total_node_rewards}")

            if initial_reward_amount <= total_node_rewards:
                logger.info(
                    "No excess rewards available for platform collection, skipping test"
                )
                pytest.skip("No excess rewards available for platform collection")

            # Calculate expected platform rewards (excess beyond node allocations)
            expected_platform_rewards = initial_reward_amount - total_node_rewards
            logger.info(f"Expected platform rewards: {expected_platform_rewards}")

            # 2. Find platform auth NFT at the platform address
            platform_utxo = await find_platform_auth_nft(
                self.platform_auth_finder,
                self.token_config.platform_auth_policy,
                [self.platform_address, self.admin_address],
            )

            if not platform_utxo:
                logger.error("Platform auth NFT not found - please create one first")
                pytest.skip("Platform auth NFT not found")

            logger.info(
                f"Found platform auth NFT at UTxO: {platform_utxo.input.transaction_id}#{platform_utxo.input.index}"
            )

            # 3. Get platform script
            platform_script = await self.platform_auth_finder.get_platform_script(
                str(self.platform_address)
            )

            # Create LoadedKeys with admin keys for testing
            loaded_keys = LoadedKeys(
                payment_sk=self.admin_signing_key,
                payment_vk=self.admin_verification_key,
                stake_vk=None,  # Not needed for testing
                address=self.admin_address,
            )

            # Get initial platform address balance
            initial_platform_utxos = await self.chain_query.get_utxos(
                self.platform_address
            )
            initial_platform_balance = self._calculate_balance(initial_platform_utxos)
            logger.info(f"Initial platform address balance: {initial_platform_balance}")

            # 4. Use the reward orchestrator to test platform collection
            result = await self.reward_orchestrator.collect_platform_oracle(
                oracle_policy=self.token_config.oracle_policy,
                platform_utxo=platform_utxo,
                platform_script=platform_script,
                tokens=self.token_config,
                loaded_key=loaded_keys,
                network=self.NETWORK,
            )

            # 5. Check the result
            if result is not None:
                # If we have a transaction, we can test submission
                assert (
                    result.transaction is not None
                ), "Should have transaction for platform collect"

                # 6. Submit the transaction
                logger.info(
                    f"Submitting platform collect transaction: {result.transaction.id}"
                )
                status, _ = await self.tx_manager.sign_and_submit(
                    result.transaction,
                    [loaded_keys.payment_sk],
                    wait_confirmation=True,
                )

                assert (
                    status == "confirmed"
                ), f"Platform collect transaction failed with status: {status}"
                logger.info(
                    f"Platform collect transaction confirmed: {result.transaction.id}"
                )

                # 7. Wait for indexing
                await wait_for_indexing(10)

                # 8. Verify platform rewards were collected
                await self.verify_platform_reward_collection(
                    original_reward_datum=reward_datum,
                    original_reward_amount=initial_reward_amount,
                    expected_platform_rewards=expected_platform_rewards,
                    initial_platform_balance=initial_platform_balance,
                )

                logger.info("Platform collect test completed successfully")

        except Exception as e:
            logger.error(f"Error in platform collect test: {e}")
            raise

    def _get_reward_account_amount(self, reward_utxo: UTxO) -> int:
        """Get the amount of rewards in the reward account (tokens or ADA)."""
        if (
            self.token_config.reward_token_policy
            and self.token_config.reward_token_name
        ):
            # Get token amount
            script_hash = ScriptHash(
                bytes.fromhex(self.token_config.reward_token_policy)
            )
            token_name = bytes.fromhex(self.token_config.reward_token_name)

            if (
                reward_utxo.output.amount.multi_asset
                and script_hash in reward_utxo.output.amount.multi_asset
                and token_name in reward_utxo.output.amount.multi_asset[script_hash]
            ):
                return reward_utxo.output.amount.multi_asset[script_hash][token_name]
            return 0
        else:
            # Return ADA amount
            return reward_utxo.output.amount.coin

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
            token_name = bytes.fromhex(self.token_config.reward_token_name)

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
    async def verify_platform_reward_collection(
        self,
        original_reward_datum: RewardAccountDatum,
        original_reward_amount: int,
        expected_platform_rewards: int,
        initial_platform_balance: int,
    ) -> None:
        """Verify that platform rewards were correctly collected."""
        logger.info("Verifying platform reward collection")

        # Get UTxOs at script address
        utxos = await self.chain_query.get_utxos(self.oracle_script_address)

        # Check reward account
        new_reward_datum, reward_utxo = state_checks.get_reward_account_by_policy_id(
            utxos,
            ScriptHash(bytes.fromhex(self.token_config.oracle_policy)),
        )

        assert new_reward_datum is not None, "Reward account datum not found"

        # 1. Verify reward account balance decreased by the expected amount
        new_reward_amount = self._get_reward_account_amount(reward_utxo)
        logger.info(f"New reward account amount: {new_reward_amount}")

        expected_reward_after = original_reward_amount - expected_platform_rewards

        # We need some tolerance for ADA rewards due to transaction fees
        if not (
            self.token_config.reward_token_policy
            and self.token_config.reward_token_name
        ):
            assert (
                new_reward_amount < original_reward_amount
            ), f"Reward account amount should decrease, but got {original_reward_amount} -> {new_reward_amount}"
        else:
            # For tokens, we expect the exact amount decrease
            assert (
                new_reward_amount == expected_reward_after
            ), f"Reward account amount should be {expected_reward_after}, but got {new_reward_amount}"

        # 2. Verify the nodes_to_rewards list didn't change
        new_rewards = new_reward_datum.nodes_to_rewards
        orig_rewards = original_reward_datum.nodes_to_rewards

        assert len(new_rewards) == len(
            orig_rewards
        ), "Reward lists should have same length"
        for i, (new, orig) in enumerate(zip(new_rewards, orig_rewards)):
            assert (
                new == orig
            ), f"Node rewards should not change during platform collect: node {i}: {orig} -> {new}"

        # 3. Verify the platform address received the rewards
        new_platform_utxos = await self.chain_query.get_utxos(self.platform_address)
        new_platform_balance = self._calculate_balance(new_platform_utxos)
        logger.info(f"New platform balance: {new_platform_balance}")

        # The platform balance should increase
        # For tokens, we expect exact increase; for ADA, we account for transaction fees
        if not (
            self.token_config.reward_token_policy
            and self.token_config.reward_token_name
        ):
            # For ADA, just check that balance increased
            assert (
                new_platform_balance > initial_platform_balance
            ), f"Platform balance should increase, but got {initial_platform_balance} -> {new_platform_balance}"
        else:
            # For tokens, check for the exact expected amount
            expected_minimum = initial_platform_balance + expected_platform_rewards
            assert new_platform_balance >= expected_minimum, (
                f"Platform should receive at least {expected_platform_rewards} tokens, "
                f"but balance only increased from {initial_platform_balance} to {new_platform_balance}"
            )

        logger.info("Verified platform reward collection successful")
