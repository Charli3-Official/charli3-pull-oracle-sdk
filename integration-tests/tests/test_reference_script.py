"""Test the creation of reference scripts for the Charli3 ODV Oracle."""

import asyncio
from collections.abc import Callable

import pytest
from retry import retry

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.contracts.aiken_loader import (
    OracleContracts,
    RewardEscrowContract,
)
from charli3_offchain_core.models.oracle_datums import NoDatum
from charli3_offchain_core.oracle.config import OracleScriptConfig
from charli3_offchain_core.oracle.deployment.reference_script_builder import (
    ReferenceScriptBuilder,
)
from charli3_offchain_core.oracle.deployment.reference_script_finder import (
    ReferenceScriptFinder,
)

from .base import TEST_RETRIES, TestBase


@pytest.mark.order(2)
class TestCreateReferenceScript(TestBase):
    """Test the creation of reference scripts for the ODV Oracle."""

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment."""
        super().setup_method(method)
        self.tx_manager = TransactionManager(self.CHAIN_CONTEXT)

        # Load contracts
        self.contracts = OracleContracts.from_blueprint("artifacts/plutus.json")
        self.escrow_contract = RewardEscrowContract.from_blueprint(
            "artifacts/plutus.json"
        )

        # Initialize builders and finders
        self.script_builder = ReferenceScriptBuilder(
            chain_query=self.CHAIN_CONTEXT,
            contracts=self.contracts,
            tx_manager=self.tx_manager,
        )

        self.script_finder = ReferenceScriptFinder(
            chain_query=self.CHAIN_CONTEXT,
            contracts=self.contracts,
        )

        # Script configuration
        self.script_config = OracleScriptConfig(
            create_manager_reference=True,
            reference_ada_amount=69528920,  # 69.52892 ADA for reference scripts
        )

    @retry(tries=TEST_RETRIES, delay=5)
    @pytest.mark.asyncio
    async def test_create_manager_reference_script(self) -> None:
        """Test creating the manager reference script."""
        # Check if reference script already exists
        manager_utxo = await self.script_finder.find_manager_reference()

        if manager_utxo:
            pytest.skip("Manager reference script already exists")

        # Prepare reference script transaction
        result = await self.script_builder.prepare_reference_script(
            script_config=self.script_config,
            script_address=self.oracle_script_address,
            admin_address=self.admin_address,
            signing_key=self.admin_signing_key,
        )

        assert (
            result.manager_tx is not None
        ), "Failed to build manager reference script transaction"

        # Submit the transaction
        await self.script_builder.submit_reference_script(
            result, self.admin_signing_key
        )

        # Verify that the reference script now exists
        await asyncio.sleep(10)  # Wait for UTxOs to be indexed

        manager_utxo = await self.script_finder.find_manager_reference()
        assert (
            manager_utxo is not None
        ), "Manager reference script not found after creation"

    @retry(tries=TEST_RETRIES, delay=5)
    @pytest.mark.asyncio
    async def test_create_escrow_reference_script(self) -> None:
        """Test creating the escrow reference script."""
        # This is for reward token escrow if using non-ADA rewards
        if isinstance(self.reward_token, NoDatum):
            pytest.skip("Escrow not needed for ADA rewards")

        # We'll need to set up the escrow finder and builder
        # This part is simplified and would need a proper implementation
        # based on the actual escrow script requirements

        script_address = self.oracle_script_address  # Or dedicated escrow address

        # Submit escrow reference script
        tx = await self.tx_manager.build_reference_script_tx(
            script=self.escrow_contract.escrow_manager.contract,
            script_address=script_address,
            admin_address=self.admin_address,
            signing_key=self.admin_signing_key,
            reference_ada=self.script_config.reference_ada_amount,
        )

        status, _ = await self.tx_manager.sign_and_submit(
            tx, [self.admin_signing_key], wait_confirmation=True
        )

        assert (
            status == "confirmed"
        ), f"Escrow reference script transaction failed with status: {status}"

        # Verify that the escrow reference script exists
        await asyncio.sleep(10)  # Wait for UTxOs to be indexed

        # Check for a UTxO with the escrow script at the address
        utxos = await self.CHAIN_CONTEXT.get_utxos(script_address)
        found = False
        for utxo in utxos:
            if (
                utxo.output.script
                and utxo.output.script == self.escrow_contract.escrow_manager.contract
            ):
                found = True
                break

        assert found, "Escrow reference script not found after creation"
