"""
Test module for Platform Authentication NFT creation and validation.

This module verifies the creation of a Platform Auth NFT using a multisignature setup.
It includes functionality to generate platform keys, configure multisig settings,
and validate the creation of the authentication NFT.
"""

from pathlib import Path
from typing import Any

import pytest
from pycardano import (
    ExtendedSigningKey,
    HDWallet,
    PaymentExtendedSigningKey,
    PaymentVerificationKey,
    VerificationKeyHash,
)

from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.setup import setup_platform_from_config

from .async_utils import async_retry
from .base import TestBase
from .test_utils import (
    find_platform_auth_nft,
    logger,
    update_config_file,
    wait_for_indexing,
)

TOTAL_SIGNERS = 2
REQUIRED_SIGNERS = 2


@pytest.mark.run(order=0)
class TestMultisigPlatformAuth(TestBase):
    """
    Test suite for Platform Authentication NFT creation using multisig setup.

    This class tests the entire workflow of:
    1. Setting up platform keys with multisignature configuration
    2. Creating a Platform Auth NFT
    3. Verifying the minted NFT
    4. Updating configuration with the generated policy ID
    """

    def setup_method(self, method: Any) -> None:
        """
        Set up the test environment for each test method.

        This method prepares the platform keys and initializes the platform
        configuration for authentication testing.

        Args:
            method: The test method being set up
        """
        super().setup_method(method)
        logger.info("Setting up Platform Auth test environment")

        # Set up platform keys directory
        self.platform_keys_dir = Path("./platform_keys")

        # Clean up existing platform keys directory to ensure a fresh start
        if self.platform_keys_dir.exists():
            import shutil

            shutil.rmtree(self.platform_keys_dir)
            logger.info(
                f"Removed existing platform keys directory: {self.platform_keys_dir}"
            )

        # Configure multisig environment (2 total signers, requiring 1 signatures)
        self.prepare_platform_keys(
            total_signers=TOTAL_SIGNERS, required_signers=REQUIRED_SIGNERS
        )

        try:
            # Initialize platform using the configuration file
            platform_setup = setup_platform_from_config(self.config_path, None)

            # Unpack the result tuple to individual components
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

            # Set status callback for better logging of transaction status
            self.platform_orchestrator.status_callback = format_status_update

            logger.info("Platform Auth test environment setup complete")

        except Exception as e:
            logger.error(f"Error setting up Platform Auth test environment: {e}")
            raise

    def prepare_platform_keys(self, total_signers: int, required_signers: int) -> None:
        """
        Prepare platform keys for multisignature testing.

        This method either generates new platform keys or uses existing ones,
        then loads the platform configuration for testing.

        Args:
            total_signers: Total number of signers in the multisig setup
            required_signers: Minimum number of required signatures
        """
        if not self.platform_keys_dir.exists():
            logger.info("Platform keys directory not found, creating")
            self.platform_keys_dir.mkdir(parents=True, exist_ok=True)

        # Use a test mnemonic for reproducible key generation
        test_mnemonic = "test test test test test test test test test test test test test test test test test test test test test test test sauce"
        platform_keys = self.generate_platform_keys(test_mnemonic, total_signers)

        # Save generated keys with required signers configuration
        self.save_platform_keys(platform_keys, required_signers, self.platform_keys_dir)
        logger.info(f"Generated {len(platform_keys)} platform keys")

        # Load platform configuration from the saved files
        (self.required_signers, self.parties) = self.load_platform_config(
            self.platform_keys_dir
        )
        logger.info(f"Loaded {len(self.parties)} platform administrators from config")
        logger.info(f"Configured with {self.required_signers} required signers")

        # Load platform signing keys
        self.platform_keys = []
        for platform_dir in sorted(self.platform_keys_dir.glob("platform_*")):
            try:
                # Corregido: "adminsitrator.skey" a "administrator.skey"
                skey = PaymentExtendedSigningKey.load(
                    str(platform_dir / "administrator.skey")
                )
                vkey = PaymentVerificationKey.load(
                    str(platform_dir / "administrator.vkey")
                )
                vkh = VerificationKeyHash(
                    bytes.fromhex(
                        (platform_dir / "administrator.vkh").read_text().strip()
                    )
                )
                self.platform_keys.append((skey, vkey, vkh))
                logger.info(f"Loaded node key: {vkh}")
            except Exception as e:
                logger.warning(f"Failed to load key from {platform_dir}: {e}")

    def load_platform_config(self, platform_dir: Path) -> tuple[int, list[str]]:
        """
        Load platform multisig configuration from the specified directory.

        Args:
            platform_dir: Directory containing platform configuration files

        Returns:
            Tuple containing:
                - Number of required signatures
                - List of verification key hashes for all parties

        Raises:
            ValueError: If required files are missing or invalid
        """
        if not platform_dir.is_dir():
            raise ValueError(f"Keys directory not found: {platform_dir}")

        # Read required signatures count
        try:
            required_sigs = int((platform_dir / "required_signatures").read_text())
        except (ValueError, FileNotFoundError) as e:
            raise ValueError("Invalid or missing required_signatures file") from e

        # Load all node configurations
        parties = []
        # Buscamos directorios platform_* (no node_*)
        for admin_dir in sorted(platform_dir.glob("platform_*")):
            try:
                vkh = (admin_dir / "administrator.vkh").read_text()
                parties.append(vkh)
            except FileNotFoundError as e:
                raise ValueError(f"Missing key files in {admin_dir}") from e

        return (required_sigs, parties)

    def save_platform_keys(
        self, parties: list[dict[str, Any]], threshold: int, output_dir: Path
    ) -> None:
        """
        Save generated platform keys to the specified directory.

        Args:
            parties: List of dictionaries containing key information for each party
            threshold: Minimum number of required signatures
            output_dir: Directory to store the key files
        """
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save threshold configuration
        with (output_dir / "required_signatures").open("w") as f:
            f.write(str(threshold))

        # Save keys for each administrator
        for administrator in parties:
            index = administrator["index"]
            platform_dir = output_dir / f"platform_{index}"
            platform_dir.mkdir(exist_ok=True)

            # Save verification and signing keys
            administrator["vkey"].save(str(platform_dir / "administrator.vkey"))
            administrator["skey"].save(str(platform_dir / "administrator.skey"))

            # Save verification key hash
            with (platform_dir / "administrator.vkh").open("w") as f:
                f.write(administrator["vkh"].to_primitive().hex())

    def generate_platform_keys(
        self, mnemonic: str, total_signers: int = 1
    ) -> list[dict[str, Any]]:
        """
        Generate platform keys from a mnemonic phrase.

        Args:
            mnemonic: The mnemonic phrase to derive keys from
            total_signers: Number of signing keys to generate

        Returns:
            List of dictionaries containing key information for each party
        """
        start_index = 0
        hdwallet = HDWallet.from_mnemonic(mnemonic)
        parties = []

        for i in range(start_index, start_index + total_signers):
            # Derive keys at the specified HD path
            derived_wallet = hdwallet.derive_from_path(f"m/1852'/1815'/0'/0/{i}")
            signing_key = ExtendedSigningKey.from_hdwallet(derived_wallet)
            verification_key = PaymentVerificationKey.from_primitive(
                derived_wallet.public_key
            )
            vkh = verification_key.hash()

            # Store key information
            parties.append(
                {
                    "index": i,
                    "vkey": verification_key,
                    "skey": signing_key,
                    "vkh": vkh,
                }
            )

        return parties

    @pytest.mark.asyncio
    @async_retry(tries=1, delay=0)
    async def test_mint_platform_auth_nft(self) -> None:
        """Test minting a Platform Auth NFT with proper multisig."""
        logger.info("Starting Platform Auth NFT minting test")

        # Check if a Platform Auth NFT already exists
        platform_utxo = await find_platform_auth_nft(
            self.platform_auth_finder,
            self.token_config.platform_auth_policy,
            [self.platform_address, self.admin_address],
        )

        if platform_utxo:
            logger.info("Platform Auth NFT already exists, skipping test")
            pytest.skip("Platform Auth NFT already exists")

        # Multisig configuration
        multisig_threshold = self.required_signers
        multisig_parties = self.parties

        logger.info(f"Using multisig threshold: {multisig_threshold}")
        logger.info(f"Using multisig parties: {multisig_parties}")

        # Build the transaction
        logger.info("Building Platform Auth NFT transaction")

        result = await self.platform_orchestrator.build_tx(
            sender_address=self.platform_address,
            signing_key=self.platform_signing_key,
            multisig_threshold=multisig_threshold,
            multisig_parties=multisig_parties,
            network=self.NETWORK,
        )

        assert result.transaction is not None, "Failed to build transaction"
        assert result.policy_id is not None, "Policy ID not generated"

        logger.info(f"Transaction built successfully with ID: {result.transaction.id}")
        logger.info(f"Generated Policy ID: {result.policy_id}")
        logger.info(f"Platform address: {result.platform_address}")

        # Extract platform signing keys
        platform_signing_keys = [skey for skey, _, _ in self.platform_keys]

        # IMPORTANT: For multisig, we need to ensure that ALL required signatures
        # are present and correct

        # 1. First sign with the main key
        self.platform_tx_manager.sign_tx(result.transaction, self.platform_signing_key)
        logger.info("Transaction signed with platform_signing_key")

        # 2. Get additional signatures to reach the threshold
        signatures_needed = multisig_threshold - 1

        # Filter to ensure we don't use the same key twice
        filtered_platform_keys = [
            key
            for key in platform_signing_keys
            if not key.to_cbor() == self.platform_signing_key.to_cbor()
        ]

        # Verify we have enough keys available
        if len(filtered_platform_keys) < signatures_needed:
            logger.error(
                f"Not enough unique signing keys available. Need {signatures_needed} more, have {len(filtered_platform_keys)}"
            )
            pytest.fail("Insufficient signing keys for multisig")

        # Add additional signatures
        for i in range(signatures_needed):
            if i < len(filtered_platform_keys):
                self.platform_tx_manager.sign_tx(
                    result.transaction, filtered_platform_keys[i]
                )
                logger.info(f"Added signature {i+1} of {signatures_needed}")

        # Submit the already signed transaction
        logger.info(f"Submitting transaction with {multisig_threshold} signatures")
        status, _ = await self.platform_tx_manager.sign_and_submit(
            result.transaction, [], wait_confirmation=True
        )

        logger.info(f"Transaction submission status: {status}")
        assert status == "confirmed", f"Platform Auth NFT transaction failed: {status}"

        # Wait for UTxOs to be indexed
        await wait_for_indexing(5)

        # Verify the NFT was created
        platform_utxo = await find_platform_auth_nft(
            self.platform_auth_finder, result.policy_id, [result.platform_address]
        )

        assert platform_utxo is not None, "Platform Auth NFT not found after minting"

        # Update the configuration file with the new policy ID
        logger.info(
            f"Updating configuration file with new policy ID: {result.policy_id}"
        )
        update_config_file(
            self.config_path, {"tokens.platform_auth_policy": result.policy_id}
        )

        logger.info(
            f"Updating configuration file with new platform address: {result.platform_address}"
        )
        update_config_file(
            self.config_path, {"multisig.platform_addr": str(result.platform_address)}
        )
        logger.info(
            "Platform Auth NFT minting and configuration update completed successfully"
        )
