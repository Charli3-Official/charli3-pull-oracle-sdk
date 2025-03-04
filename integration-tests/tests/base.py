"""Base functionality for ODV integration tests."""

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any, ClassVar

import yaml
from pycardano import (
    Address,
    ExtendedSigningKey,
    Network,
    OgmiosV6ChainContext,
)
from pycardano.backend.kupo import KupoChainContextExtension
from pycardano.key import HDWallet
from retry import retry

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.cli.config.token import TokenConfig
from charli3_offchain_core.cli.setup import setup_token
from charli3_offchain_core.models.oracle_datums import (
    OracleConfiguration,
)

TEST_RETRIES = 6


class TestBase:
    """Base class for ODV system integration tests."""

    NETWORK = Network.TESTNET
    OGMIOS_WS = "ws://localhost:1337"
    KUPO_URL = "http://localhost:1442"
    _, ws_host = OGMIOS_WS.split("ws://")
    ws_url, port = ws_host.split(":")
    ogmios_context = OgmiosV6ChainContext(
        host=ws_url,
        port=port,
        secure=False,
        refetch_chain_tip_interval=None,
        network=NETWORK,
    )
    kupo_context = KupoChainContextExtension(
        ogmios_context,
        kupo_url=KUPO_URL,
    )

    CHAIN_CONTEXT: ClassVar[ChainQuery] = ChainQuery(kupo_ogmios_context=kupo_context)
    DIR_PATH: ClassVar[str] = os.path.dirname(os.path.realpath(__file__))
    wallet_keys: ClassVar[list] = []

    def setup_method(self, method: Any) -> None:
        """Set up test configuration."""
        self.load_configuration()
        self.initialize_wallet_keys()
        self.initialize_oracle_configuration()

    def load_configuration(self) -> None:
        """Load test configuration from YAML file."""
        config_path = os.path.join(self.DIR_PATH, "../configuration.yml")
        with open(config_path) as stream:
            self.config = yaml.safe_load(stream)

    def initialize_wallet_keys(self) -> None:
        """Initialize wallet keys for testing."""
        mnemonic = self.config["mnemonic"]
        hdwallet = HDWallet.from_mnemonic(mnemonic=mnemonic)
        key_variations = [0, 1, 2, 3, 4, 5, 6, 7, 8]

        for key in key_variations:
            child_wallet = hdwallet.derive(key)
            signing_key = ExtendedSigningKey.from_hdwallet(child_wallet)
            verification_key = signing_key.to_verification_key()
            self.wallet_keys.append((signing_key, verification_key))

        # Admin/deployer credentials
        self.admin_signing_key, self.admin_verification_key = self.wallet_keys[0]
        self.admin_address = Address(
            self.admin_verification_key.hash(), None, self.NETWORK
        )

        # Node operator credentials
        self.node_signing_keys = []
        self.node_verification_keys = []
        self.node_vkhs = []

        for i in range(1, 6):
            signing_key, verification_key = self.wallet_keys[i]
            self.node_signing_keys.append(signing_key)
            self.node_verification_keys.append(verification_key)
            self.node_vkhs.append(verification_key.hash())

        # Platform credentials
        self.platform_signing_key, self.platform_verification_key = self.wallet_keys[6]
        self.platform_vkh = self.platform_verification_key.hash()

    def initialize_oracle_configuration(self) -> None:
        """Initialize oracle configuration for testing."""
        # Load oracle addresses
        self.oracle_script_address = Address.from_primitive(
            self.config["oracle_script_address"]
        )
        self.multisig_oracle_script_address = Address.from_primitive(
            self.config["multisig_oracle_script_address"]
        )

        # Set up token configuration
        self.token_config = TokenConfig(
            platform_auth_policy=self.config["oracle_owner"]["platform_auth_policy"],
            reward_token_policy=self.config["oracle_owner"]["reward_token_policy"],
            reward_token_name=self.config["oracle_owner"]["reward_token_name"],
            rate_token_policy=None,
            rate_token_name=None,
            oracle_policy=None,
        )

        # Set up reward token
        self.reward_token = setup_token(
            self.token_config.reward_token_policy,
            self.token_config.reward_token_name,
        )

        # Oracle configuration
        self.oracle_config = OracleConfiguration(
            platform_auth_nft=bytes.fromhex(self.token_config.platform_auth_policy),
            pause_period_length=self.config["oracle_settings"]["pause_period"],
            reward_dismissing_period_length=self.config["oracle_settings"][
                "reward_dismissing_period"
            ],
            fee_token=self.reward_token,
            reward_escrow_script_hash=bytes.fromhex(
                "00" * 28
            ),  # Placeholder, will be updated
        )

        # Oracle settings
        self.aggregation_liveness_period = self.config["oracle_settings"][
            "aggregation_liveness_period"
        ]
        self.time_uncertainty_aggregation = self.config["oracle_settings"][
            "time_uncertainty_aggregation"
        ]
        self.time_uncertainty_platform = self.config["oracle_settings"][
            "time_uncertainty_platform"
        ]
        self.iqr_fence_multiplier = self.config["oracle_settings"][
            "iqr_fence_multiplier"
        ]
        self.node_fee = self.config["oracle_settings"]["node_fee"]
        self.platform_fee = self.config["oracle_settings"]["platform_fee"]
        self.transport_count = self.config["oracle_settings"]["transport_count"]
        self.multisig_threshold = self.config["oracle_settings"]["multisig_threshold"]

    @retry(tries=TEST_RETRIES, delay=3)
    async def assert_output(
        self, target_address: str, predicate_function: Callable
    ) -> None:
        """Check that at least one UTxO at the address satisfies the predicate function."""
        utxos = await self.CHAIN_CONTEXT.get_utxos(target_address)
        found = False

        for utxo in utxos:
            if predicate_function(utxo):
                found = True
                break

        assert found, f"No UTxO matching the predicate at address: {target_address}"

    @retry(tries=TEST_RETRIES, delay=3)
    async def wait_for_transaction(self, tx_id: str, timeout: int = 60) -> Any | None:
        """Wait for a transaction to be confirmed on the blockchain."""
        start_time = asyncio.get_event_loop().time()

        while True:
            try:
                tx = await self.CHAIN_CONTEXT.get_transaction(tx_id)
                if tx:
                    return tx
            # For S110: Add logging instead of silently passing
            except Exception as e:
                logging.debug(f"Exception while waiting for transaction {tx_id}: {e}")

            if asyncio.get_event_loop().time() - start_time > timeout:
                return None

            await asyncio.sleep(3)


class MultisigTestBase(TestBase):
    """Base class for multisig tests."""

    def setup_method(self, method: "Callable") -> None:
        """Setup for multisig tests."""
        super().setup_method(method)

        # Use multisig addresses
        self.oracle_address = self.multisig_oracle_script_address

        # Override threshold for multisig tests
        self.multisig_threshold = 2

        # Add another platform signer for multisig
        self.platform_signing_key_2, self.platform_verification_key_2 = (
            self.wallet_keys[7]
        )
        self.platform_vkh_2 = self.platform_verification_key_2.hash()
