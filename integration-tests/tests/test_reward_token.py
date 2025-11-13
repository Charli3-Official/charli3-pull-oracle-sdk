"""Test the creation of the TestC3 reward tokens."""

import asyncio
from typing import Any

import pytest
from pycardano import (
    Asset,
    AssetName,
    MultiAsset,
    TransactionBuilder,
    TransactionOutput,
    Value,
    VerificationKeyHash,
)

from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.setup import setup_platform_from_config
from charli3_offchain_core.platform.auth.token_script_builder import (
    PlatformAuthScript,
    ScriptConfig,
)

from .async_utils import async_retry
from .base import TestBase
from .test_utils import (
    logger,
    update_config_file,
)


@pytest.mark.run(order=1)  # Run after platform auth, but before deployment
class TestRewardToken(TestBase):
    """Test the creation of the TestC3 reward tokens."""

    def setup_method(self, method: Any) -> None:
        """Set up the test environment."""
        super().setup_method(method)
        logger.info("Setting up Reward Token test environment")

        # Use the CLI setup function for platform auth
        try:
            # We'll use the same config file but focus on platform auth settings
            platform_setup = setup_platform_from_config(self.config_path, None)

            # Unpack the result tuple
            (
                self.auth_config,
                self.platform_signing_key,
                self.platform_verification_key,
                self.stake_vk,
                self.platform_address,
                self.platform_chain_query,
                self.platform_tx_manager,
                self.platform_orchestrator,
                self.meta_data,
            ) = platform_setup

            # Set the status callback for better logging
            self.platform_orchestrator.status_callback = format_status_update

            # TestC3 token settings
            self.token_name = AssetName(b"TestC3")
            self.token_amount = 1_000_000_000  # 1 billion tokens

            logger.info("Reward Token test environment setup complete")

        except Exception as e:
            logger.error(f"Error setting up Reward Token test environment: {e}")
            raise

    @pytest.mark.asyncio
    @async_retry(tries=1, delay=0)
    async def test_mint_reward_tokens(self) -> None:
        """Test minting TestC3 reward tokens."""
        logger.info("Starting Reward Token minting test")

        # Get multisig config from the deployment config
        multisig_threshold = self.auth_config.multisig.threshold
        multisig_parties = self.auth_config.multisig.parties

        logger.info(f"Using multisig threshold: {multisig_threshold}")
        logger.info(f"Using multisig parties: {multisig_parties}")

        # Create script config and script builder
        script_config = ScriptConfig(
            signers=[
                VerificationKeyHash(bytes.fromhex(pkh)) for pkh in multisig_parties
            ],
            threshold=multisig_threshold,
            network=self.NETWORK,
        )
        script_builder = PlatformAuthScript(
            chain_query=self.platform_chain_query,
            config=script_config,
        )

        # 1. Create token minting policy
        validity_slot, minting_script = script_builder.build_minting_script()
        script_hash = minting_script.hash()
        policy_id = script_hash.payload

        logger.info(f"Created minting policy with ID: {policy_id.hex()}")

        # 2. Create transaction builder
        builder = TransactionBuilder(
            self.platform_chain_query.context,
            fee_buffer=10_000,  # Small buffer for fee calculation
        )

        # 3. Set TTL
        builder.ttl = validity_slot

        # 4. Create multi-asset for minting tokens
        token_value = MultiAsset(
            {script_hash: Asset({self.token_name: self.token_amount})}
        )
        builder.mint = token_value
        builder.add_minting_script(minting_script)

        # 5. Create output with tokens
        output_value = Value(2_000_000) + Value(0, token_value)  # 2 ADA + all tokens
        builder.add_output(
            TransactionOutput(address=self.admin_address, amount=output_value)
        )

        # 6. Add input address for fees
        builder.add_input_address(self.admin_address)

        # 7. Build transaction and sign
        tx = await self.platform_tx_manager.build_tx(
            builder=builder,
            change_address=self.admin_address,
            signing_key=self.admin_signing_key,
        )

        logger.info(f"Submitting token minting transaction: {tx.id}")
        status, _ = await self.platform_tx_manager.sign_and_submit(
            tx, [self.admin_signing_key], wait_confirmation=True
        )

        # 9. Verify transaction status
        assert status == "confirmed", f"Token minting transaction failed: {status}"
        logger.info(f"Token minting transaction confirmed: {tx.id}")

        # 10. Wait for indexing
        await asyncio.sleep(10)

        # 11. Verify tokens were minted
        utxos = await self.chain_query.get_utxos(self.admin_address)
        token_utxo = None
        for utxo in utxos:
            if (
                utxo.output.amount.multi_asset
                and script_hash in utxo.output.amount.multi_asset
                and self.token_name in utxo.output.amount.multi_asset[script_hash]
            ):
                token_utxo = utxo
                break

        assert token_utxo is not None, "TestC3 tokens not found after minting"
        token_amount = token_utxo.output.amount.multi_asset[script_hash][
            self.token_name
        ]
        logger.info(f"Found TestC3 tokens: {token_amount}")
        assert (
            token_amount == self.token_amount
        ), f"Token amount mismatch: {token_amount} vs {self.token_amount}"

        # 12. Update configuration with reward token policy and name
        logger.info(
            f"Updating configuration with reward token policy: {policy_id.hex()}"
        )

        update_config_file(
            self.config_path,
            {
                "tokens.fee_token_policy": policy_id.hex(),
                "tokens.fee_token_name": self.token_name.to_primitive().hex(),
            },
        )

        logger.info("Reward tokens minted and configuration updated successfully")
