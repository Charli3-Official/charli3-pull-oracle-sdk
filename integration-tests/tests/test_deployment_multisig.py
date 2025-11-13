"""Test the deployment of the Charli3 ODV Oracle with multisignature support."""

from collections.abc import Callable
from pathlib import Path

import pytest
from pycardano import (
    PaymentExtendedSigningKey,
    PaymentVerificationKey,
    VerificationKeyHash,
)

from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.oracle.utils.common import get_script_utxos

from .base import TestBase
from .test_utils import (
    find_oracle_policy_hash,
    find_platform_auth_nft,
    logger,
    update_config_file,
    wait_for_indexing,
)


class TestMultisigDeployment(TestBase):
    """Test the deployment of the Charli3 ODV Oracle using multisignature."""

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment for multisig deployment testing."""
        logger.info("Setting up TestMultisigDeployment environment")
        super().setup_method(method)

        # Set up platform keys directory - same as in TestMultisigPlatformAuth
        self.platform_keys_dir = Path("./platform_keys")

        # Load platform configuration and keys
        self.load_platform_keys()

        logger.info("TestMultisigDeployment setup complete")

    def load_platform_keys(self) -> None:
        """
        Load platform multisig configuration and keys.

        This method loads the multisig configuration from the platform_keys directory
        and prepares the necessary keys for transaction signing.
        """
        if not self.platform_keys_dir.exists():
            logger.warning(
                "Platform keys directory not found - multisig tests may fail"
            )
            self.required_signers = 0
            self.parties = []
            self.platform_keys = []
            return

        # Load platform configuration
        (self.required_signers, self.parties) = self.load_platform_config(
            self.platform_keys_dir
        )
        logger.info(f"Loaded {len(self.parties)} platform administrators from config")
        logger.info(f"Configured with {self.required_signers} required signers")

        # Load platform signing keys
        self.platform_keys = []
        for platform_dir in sorted(self.platform_keys_dir.glob("platform_*")):
            try:
                skey = PaymentExtendedSigningKey.load(
                    platform_dir / "administrator.skey"
                )
                vkey = PaymentVerificationKey.load(platform_dir / "administrator.vkey")
                vkh = VerificationKeyHash(
                    bytes.fromhex(
                        (platform_dir / "administrator.vkh").read_text().strip()
                    )
                )
                self.platform_keys.append((skey, vkey, vkh))
                logger.info(f"Loaded platform key: {vkh}")
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
        """
        if not platform_dir.is_dir():
            raise ValueError(f"Keys directory not found: {platform_dir}")

        # Read required signatures count
        try:
            required_sigs = int((platform_dir / "required_signatures").read_text())
        except (ValueError, FileNotFoundError):
            logger.warning("Could not read required_signatures file, defaulting to 1")
            return (1, [])

        # Load all platform administrator configurations
        parties = []
        for admin_dir in sorted(platform_dir.glob("platform_*")):
            try:
                vkh = (admin_dir / "administrator.vkh").read_text().strip()
                parties.append(vkh)
            except FileNotFoundError:
                logger.warning(f"Missing vkh file in {admin_dir}")

        return (required_sigs, parties)

    @pytest.mark.asyncio
    async def test_deployment_with_multisig(self) -> None:
        """Test oracle deployment with multisignature configuration."""
        logger.info("Starting oracle deployment test with multisignature")

        # Log current configuration
        logger.info(f"Using admin address: {self.admin_address}")
        logger.info(f"Using platform address: {self.platform_address}")
        logger.info(f"Using oracle script address: {self.oracle_script_address}")
        logger.info(
            f"Using platform auth policy ID: {self.token_config.platform_auth_policy}"
        )

        # Verify we have the multisig configuration loaded
        if not hasattr(self, "platform_keys") or not self.platform_keys:
            pytest.skip("No platform keys found - please set up platform keys first")

        logger.info(f"Using multisig threshold: {self.required_signers}")
        logger.info(f"Available signers: {len(self.platform_keys)}")

        # Create collateral UTxOs first to ensure they're available
        await self.create_collateral_utxos(count=5, amount=13_000_000)

        # Find platform auth NFT at the platform address
        platform_utxo = await find_platform_auth_nft(
            self.platform_auth_finder,
            self.token_config.platform_auth_policy,
            [self.platform_address, self.admin_address],
        )

        # If not found, skip the test
        if not platform_utxo:
            pytest.skip("Platform auth NFT not found - please create one first")

        # Get platform script
        logger.info(f"Getting platform script for address: {self.platform_address}")
        platform_script = await self.platform_auth_finder.get_platform_script(
            str(self.platform_address)
        )

        # Build the deployment transaction
        logger.info("Building deployment transaction")
        result = await self.orchestrator.build_tx(
            oracle_config=self.oracle_config,
            platform_script=platform_script,
            admin_address=self.admin_address,
            script_address=self.oracle_script_address,
            aggregation_liveness_period=self.timing_config.aggregation_liveness,
            time_uncertainty_aggregation=self.timing_config.time_uncertainty_aggregation,
            time_uncertainty_platform=self.timing_config.time_uncertainty_platform,
            iqr_fence_multiplier=self.timing_config.iqr_multiplier,
            median_divergency_factor=self.timing_config.median_divergency_factor,
            deployment_config=self.configs["deployment"],
            nodes_config=self.nodes_config,
            rate_config=self.fee_config,
            signing_key=self.admin_signing_key,
            platform_utxo=platform_utxo,
        )

        assert (
            result.status == ProcessStatus.TRANSACTION_BUILT
        ), f"Deployment transaction build failed: {result.error}"

        tx = result.start_result.transaction
        logger.info(f"Deployment transaction built successfully: {tx.id}")

        # Extract oracle policy ID if available
        oracle_policy_id = result.start_result.minting_policy_id
        if oracle_policy_id:
            logger.info(f"Oracle policy ID from build result: {oracle_policy_id}")

        # Sign the transaction with admin key first
        self.tx_manager.sign_tx(tx, self.admin_signing_key)
        logger.info("Transaction signed with admin key")

        # Now add signatures from platform keys up to the required threshold
        sig_count = 0
        for skey, _, vkh in self.platform_keys:
            if sig_count >= self.required_signers:
                break

            self.tx_manager.sign_tx(tx, skey)
            vkh_hex = vkh.to_primitive().hex()
            sig_count += 1
            logger.info(
                f"Added platform signature {sig_count}/{self.required_signers} from {vkh_hex[:8]}..."
            )

        # Submit transaction (no additional signing needed as it's already signed)
        logger.info(
            f"Submitting deployment transaction with {sig_count} platform signatures"
        )
        status, _ = await self.tx_manager.sign_and_submit(
            tx, [], wait_confirmation=True  # Empty list since we've already signed
        )

        logger.info(f"Deployment transaction submission status: {status}")
        assert (
            status == "confirmed"
        ), f"Deployment transaction failed with status: {status}"

        # Wait for UTxOs to be indexed
        await wait_for_indexing(5)

        # Check that UTxOs exist at the oracle script address
        logger.info(
            f"Checking for UTxOs at oracle script address: {self.oracle_script_address}"
        )
        utxos = await get_script_utxos(self.oracle_script_address, self.tx_manager)
        logger.info(f"Found {len(utxos)} UTxOs at oracle script address")
        assert (
            len(utxos) > 0
        ), "No UTxOs found at oracle script address after deployment"

        # Find and update oracle policy ID in configuration
        oracle_policy_id = find_oracle_policy_hash(utxos, "C3CS")
        logger.info(f"Oracle policy ID from UTxOs: {oracle_policy_id}")

        # Update the configuration file with the new oracle details
        logger.info("Updating configuration file with deployment details")
        update_config_file(
            self.config_path,
            {
                "oracle_address": str(self.oracle_script_address),
                "tokens.oracle_policy": oracle_policy_id,
            },
        )

        logger.info("Oracle deployment test with multisig completed successfully")
