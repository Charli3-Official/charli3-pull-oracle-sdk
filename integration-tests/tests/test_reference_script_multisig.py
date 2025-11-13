"""Test the creation of reference scripts for the Charli3 ODV Oracle with multisignature support."""

from collections.abc import Callable
from pathlib import Path

import pytest
from pycardano import (
    PaymentExtendedSigningKey,
    PaymentVerificationKey,
    VerificationKeyHash,
)

from charli3_offchain_core.oracle.config import OracleScriptConfig

from .async_utils import async_retry
from .base import TEST_RETRIES, TestBase
from .test_utils import logger, wait_for_indexing


class TestMultisigReferenceScript(TestBase):
    """Test the creation of reference scripts for the ODV Oracle with multisignature support."""

    def setup_method(self, method: "Callable") -> None:
        """Set up the test environment."""
        logger.info("Setting up TestCreateReferenceScript environment")
        super().setup_method(method)

        # Set up platform keys directory for multisig support
        self.platform_keys_dir = Path("./platform_keys")

        # Load platform configuration and keys
        self.load_platform_keys()

        # Script configuration
        self.script_config = OracleScriptConfig(
            create_manager_reference=True,
            reference_ada_amount=69528920,  # 69.52892 ADA for reference scripts
        )

        logger.info("TestCreateReferenceScript setup complete")

    def load_platform_keys(self) -> None:
        """
        Load platform multisig configuration and keys.

        This method loads the multisig configuration from the platform_keys directory
        and prepares the necessary keys for transaction signing.
        """
        if not self.platform_keys_dir.exists():
            logger.warning(
                "Platform keys directory not found - multisig will not be used"
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
    @async_retry(tries=TEST_RETRIES, delay=5)
    async def test_create_manager_reference_script(self) -> None:
        """Test creating the manager reference script with multisignature support."""
        logger.info("Starting manager reference script creation test")

        # Check if multisig is configured
        use_multisig = (
            hasattr(self, "platform_keys")
            and self.platform_keys
            and self.required_signers > 0
        )
        if use_multisig:
            logger.info(
                f"Using multisig with {self.required_signers} required signatures from {len(self.platform_keys)} available keys"
            )
        else:
            logger.info("Multisig not configured, using standard signing")

        # Prepare reference script transaction
        reference_result, needs_reference = (
            await self.orchestrator.handle_reference_scripts(
                script_config=self.script_config,
                script_address=self.oracle_script_address,
                admin_address=self.admin_address,
                signing_key=self.admin_signing_key,
            )
        )

        if not needs_reference:
            pytest.skip("Manager reference script already exists")

        assert (
            reference_result.manager_tx is not None
        ), "Failed to build manager reference script transaction"

        logger.info(
            f"Manager reference script transaction built: {reference_result.manager_tx.id}"
        )

        # Submit the transaction
        await self.orchestrator.submit_reference_script_tx(
            reference_result, self.admin_signing_key
        )

        logger.info("Manager reference script transaction submitted")

        # Verify that the reference script now exists
        await wait_for_indexing(10)
        manager_utxo = (
            await self.orchestrator.reference_builder.script_finder.find_manager_reference()
        )
        assert (
            manager_utxo is not None
        ), "Manager reference script not found after creation"

        logger.info("Manager reference script created successfully")
