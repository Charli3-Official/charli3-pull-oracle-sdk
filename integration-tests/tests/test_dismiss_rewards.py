"""Test dismiss rewards in the Charli3 ODV Oracle."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest
from pycardano import (
    AssetName,
    ScriptHash,
    UTxO,
)

from charli3_offchain_core.cli.base import LoadedKeys
from charli3_offchain_core.oracle.rewards.orchestrator import RewardOrchestrator

from .async_utils import async_retry
from .base import TEST_RETRIES, TestBase
from .test_utils import find_platform_auth_nft, logger, wait_for_indexing


@pytest.mark.run(order=6)
class TestDismissRewards(TestBase):
    """Test dismiss rewards in the Charli3 ODV Oracle."""

    def setup_method(self, method: Callable) -> None:
        """Set up the test environment."""
        logger.info("Setting up TestDismissRewards environment")
        super().setup_method(method)

        # Create reward orchestrator for dismiss operations
        self.reward_orchestrator = RewardOrchestrator(
            chain_query=self.chain_query,
            tx_manager=self.tx_manager,
            script_address=self.oracle_script_address,
            ref_script_config=self.ref_script_config,
        )

        logger.info("TestDismissRewards setup complete")

    @pytest.mark.asyncio
    @async_retry(tries=TEST_RETRIES, delay=5)
    async def test_dismiss_rewards(self) -> None:
        """Test dismissing rewards."""
        logger.info("Starting dismiss rewards test")

        # Wait for reward dismissing period to pass
        # Configured period is 25000ms (25s). We wait 30s to be safe.
        logger.info("Waiting 30s for reward dismissing period to pass...")
        await asyncio.sleep(30)

        # Mock the confirm_withdrawal_amount_and_address function
        with patch(
            "charli3_offchain_core.oracle.rewards.dismiss_rewards_builder.confirm_withdrawal_amount_and_address",
            new=AsyncMock(return_value=self.platform_address),
        ):
            # 1. Check if there are rewards to dismiss (any reward account with > 0 rewards)
            # We rely on previous tests (TestAggregate) to have populated rewards.

            # Let's verify we can find the platform auth NFT first, as it's required
            platform_utxo = await find_platform_auth_nft(
                self.platform_auth_finder,
                self.token_config.platform_auth_policy,
                [self.platform_address, self.admin_address],
            )

            if not platform_utxo:
                logger.error("Platform auth NFT not found - please create one first")
                pytest.skip("Platform auth NFT not found")

            # Get platform script
            platform_script = await self.platform_auth_finder.get_platform_script(
                str(self.platform_address)
            )

            # Create LoadedKeys with admin keys for testing
            loaded_keys = LoadedKeys(
                payment_sk=self.admin_signing_key,
                payment_vk=self.admin_verification_key,
                stake_vk=None,
                address=self.admin_address,
            )

            # Get initial platform balance
            initial_platform_utxos = await self.chain_query.get_utxos(
                self.platform_address
            )
            initial_platform_balance = self._calculate_balance(initial_platform_utxos)

            # 2. Use the reward orchestrator to dismiss rewards
            # We pass the configured period (8000) or let it read from config?
            # The orchestrator method requires `reward_dismission_period_length` as argument.
            # We should read it from our loaded config.

            reward_dismission_period_length = (
                self.timing_config.reward_dismissing_period
            )
            logger.info(
                f"Using reward dismissing period: {reward_dismission_period_length}"
            )

            result = await self.reward_orchestrator.dismiss_rewards(
                oracle_policy=self.token_config.oracle_policy,
                platform_utxo=platform_utxo,
                platform_script=platform_script,
                tokens=self.token_config,
                loaded_key=loaded_keys,
                network=self.NETWORK,
                reward_dismission_period_length=reward_dismission_period_length,
            )

            if result.error:
                logger.warning(f"Dismiss rewards returned error: {result.error}")
                if (
                    "No rewards available" in str(result.error)
                    or "No expired transports" in str(result.error)
                    or "No pending transports" in str(result.error)
                ):
                    # If tests ran out of order or no rewards were generated, we skip.
                    pytest.skip(
                        f"Cannot test dismiss rewards (preconditions not met): {result.error}"
                    )
                else:
                    pytest.fail(f"Dismiss rewards failed: {result.error}")

            # 3. Check the result
            assert (
                result.transaction is not None
            ), "Should have transaction for dismiss rewards"

            # 4. Submit the transaction
            logger.info(
                f"Submitting dismiss rewards transaction: {result.transaction.id}"
            )
            status, _ = await self.tx_manager.sign_and_submit(
                result.transaction,
                [loaded_keys.payment_sk],
                wait_confirmation=True,
            )

            assert (
                status == "confirmed"
            ), f"Dismiss rewards transaction failed with status: {status}"
            logger.info(
                f"Dismiss rewards transaction confirmed: {result.transaction.id}"
            )

            # 5. Wait for indexing
            await wait_for_indexing(10)

            # 6. Verify rewards were dismissed (accounts emptied)
            await self.verify_dismiss_rewards(initial_platform_balance)

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
    async def verify_dismiss_rewards(self, initial_platform_balance: int) -> None:
        """Verify that rewards were correctly dismissed."""
        logger.info("Verifying dismiss rewards")

        # Get UTxOs at script address
        await self.chain_query.get_utxos(self.oracle_script_address)

        # Check platform balance increase
        new_platform_utxos = await self.chain_query.get_utxos(self.platform_address)
        new_platform_balance = self._calculate_balance(new_platform_utxos)

        logger.info(
            f"Platform balance: {initial_platform_balance} -> {new_platform_balance}"
        )

        if not (
            self.token_config.reward_token_policy
            and self.token_config.reward_token_name
        ):
            # ADA
            assert (
                new_platform_balance > initial_platform_balance
            ), "Platform balance should increase (ADA)"
        else:
            # Token
            assert (
                new_platform_balance > initial_platform_balance
            ), "Platform balance should increase (Token)"

        logger.info("Verified dismiss rewards successful")
