"""Test the remove functionality of the Charli3 ODV Oracle."""

from collections.abc import Callable

import pytest
from pycardano import ScriptHash

from charli3_offchain_core.cli.setup import setup_management_from_config
from charli3_offchain_core.models.oracle_datums import NoDatum
from charli3_offchain_core.oracle.lifecycle.orchestrator import LifecycleOrchestrator
from charli3_offchain_core.oracle.utils import asset_checks, common, state_checks

from .async_utils import async_retry
from .base import TEST_RETRIES, TestBase
from .test_utils import logger, wait_for_indexing


@pytest.mark.run(order=10)
class TestOracleRemove(TestBase):
    """Test oracle Remove/resume."""

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment."""
        logger.info("Setting up TestOracleRemove environment")

        super().setup_method(method)

        (
            self.management_config,
            _,
            self.loaded_keys,
            self.oracle_addresses,
            chain_query,
            tx_manager,
            self.platform_auth_finder,
        ) = setup_management_from_config(self.config_path)

        self.lifecycle_orchestrator = LifecycleOrchestrator(
            chain_query=chain_query,
            tx_manager=tx_manager,
            script_address=self.oracle_addresses.script_address,
        )

        # OVERRIDE: Increase TTL offset for this test
        # The remove transaction seems to be particularly sensitive to validity interval
        self.lifecycle_orchestrator.tx_manager.config.ttl_offset = 600
        logger.info(
            f"Overridden ttl_offset to {self.lifecycle_orchestrator.tx_manager.config.ttl_offset} for TestOracleRemove"
        )

    @pytest.mark.asyncio
    @pytest.mark.run(order=10.1)
    @async_retry(tries=TEST_RETRIES, delay=5)
    async def test_oracle_pause(self) -> None:
        """Test oracle pause."""
        # Prepare the transaction
        platform_utxo = await self.platform_auth_finder.find_auth_utxo(
            policy_id=self.management_config.tokens.platform_auth_policy,
            platform_address=self.oracle_addresses.platform_address,
        )

        assert (
            platform_utxo is not None
        ), "No platform auth UTxO found for oracle pause test"

        platform_script = await self.platform_auth_finder.get_platform_script(
            self.oracle_addresses.platform_address
        )

        result = await self.lifecycle_orchestrator.pause_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=self.oracle_addresses.admin_address,
            signing_key=self.loaded_keys.payment_sk,
        )

        assert (
            result.transaction is not None
        ), "Failed to build oracle pause transaction"

        logger.info("Oracle pause transaction built")

        # Submit the transaction
        await self.lifecycle_orchestrator.tx_manager.sign_and_submit(
            result.transaction, [self.loaded_keys.payment_sk], wait_confirmation=False
        )

        logger.info("Oracle pause transaction submitted")

        # Verify that the oracle was paused
        await wait_for_indexing(10)

        utxos = await common.get_script_utxos(
            self.oracle_addresses.script_address, self.lifecycle_orchestrator.tx_manager
        )
        policy_hash = ScriptHash.from_primitive(
            self.management_config.tokens.oracle_policy
        )
        settings_datum, _settings_utxo = state_checks.get_oracle_settings_by_policy_id(
            utxos, policy_hash
        )
        assert (
            settings_datum.pause_period_started_at != NoDatum()
        ), "Oracle pause timestamp not found after creation"

    @pytest.mark.asyncio
    @pytest.mark.run(order=10.2)
    @async_retry(tries=TEST_RETRIES, delay=5)
    async def test_oracle_remove(self) -> None:
        """Test oracle remove."""
        # Create collateral UTxOs first to ensure they're available
        await self.create_collateral_utxos(count=5, amount=14_000_000)

        # Wait for pause period to end
        await wait_for_indexing(352)

        # Prepare the transaction
        platform_utxo = await self.platform_auth_finder.find_auth_utxo(
            policy_id=self.management_config.tokens.platform_auth_policy,
            platform_address=self.oracle_addresses.platform_address,
        )

        assert (
            platform_utxo is not None
        ), "No platform auth UTxO found for oracle remove test"

        platform_script = await self.platform_auth_finder.get_platform_script(
            self.oracle_addresses.platform_address
        )

        result = await self.lifecycle_orchestrator.remove_oracle(
            oracle_policy=self.management_config.tokens.oracle_policy,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=self.oracle_addresses.admin_address,
            signing_key=self.loaded_keys.payment_sk,
            pause_period=self.oracle_config.pause_period_length,
        )

        assert (
            result.transaction is not None
        ), "Failed to build oracle remove transaction"

        logger.info("Oracle remove transaction built")

        # Submit the transaction
        await self.lifecycle_orchestrator.tx_manager.sign_and_submit(
            result.transaction, [self.loaded_keys.payment_sk], wait_confirmation=False
        )

        logger.info("Oracle remove transaction submitted")

        # Verify that the oracle was removed
        await wait_for_indexing(10)

        utxos = await common.get_script_utxos(
            self.oracle_addresses.script_address, self.lifecycle_orchestrator.tx_manager
        )
        policy_hash = ScriptHash.from_primitive(
            self.management_config.tokens.oracle_policy
        )
        core_oracle_utxos = asset_checks.filter_utxos_by_token_name(
            utxos, policy_hash, "C3CS"
        )
        assert core_oracle_utxos == [], "Oracle was not removed"
