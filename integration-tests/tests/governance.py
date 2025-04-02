import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from pycardano import Network, ScriptHash, UTxO

from charli3_offchain_core.cli.config.escrow import EscrowConfig
from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.config.nodes import NodeConfig, NodesConfig
from charli3_offchain_core.cli.governance import setup_management_from_config
from charli3_offchain_core.models.oracle_datums import (
    AggStateVariant,
    RewardTransportVariant,
)
from charli3_offchain_core.oracle.governance.orchestrator import GovernanceOrchestrator
from charli3_offchain_core.oracle.utils.asset_checks import filter_utxos_by_token_name
from charli3_offchain_core.oracle.utils.state_checks import (
    convert_cbor_to_agg_states,
    convert_cbor_to_transports,
)

from .test_utils import (
    logger,
)

TEST_RETRIES = 3


class GovernanceBase:
    """Base class for Oracle Governance integration tests.

    This class provides common setup and utility methods for testing oracle governance
    operations such as adding, removing, or updating node configurations. It loads
    configuration from a YAML file and initializes the necessary components for
    interacting with the blockchain.
    """

    NETWORK = Network.TESTNET
    DIR_PATH: ClassVar[str] = os.path.dirname(os.path.realpath(__file__))

    def setup_method(self, method: Any) -> None:
        """Set up test configuration and environment.

        This method loads the configuration from a YAML file, initializes blockchain
        connection components, and prepares the governance orchestrator for testing.

        Args:
            method (Any): The test method being run.

        Raises:
            FileNotFoundError: If the configuration file is not found.
            Exception: If there's an error during setup.
        """
        logger.info("Setting up test base environment")
        self.config_path = Path(self.DIR_PATH).parent / "configuration.yml"

        if not self.config_path.exists():
            logger.error(f"Configuration file not found at {self.config_path}")
            raise FileNotFoundError(
                f"Configuration file not found at {self.config_path}"
            )

        try:
            # Use the CLI setup function to load configuration
            logger.info(f"Loading configuration from {self.config_path}")
            setup_result = setup_management_from_config(self.config_path)

            # Unpack the result tuple
            (
                self.management_config,
                self.oracle_configuration,
                self.loaded_key,
                self.oracle_addresses,
                self.chain_query,
                self.tx_manager,
                self.platform_auth_finder,
            ) = setup_result

            self.escrow_config = EscrowConfig.from_yaml(self.config_path)
            self.governance_orchestrator = GovernanceOrchestrator(
                chain_query=self.chain_query,
                tx_manager=self.tx_manager,
                script_address=self.oracle_addresses.script_address,
                status_callback=format_status_update,
            )

            logger.info("Test Governance base environment setup complete")
        except Exception as e:
            logger.error(f"Error setting up test environment: {e}")
            raise

    def load_nodes_to_remove(
        self, nodes_config: NodesConfig, required_signatures: int, slice_count: int
    ) -> NodesConfig:
        """Create a node configuration for removing nodes.

        Creates a new NodesConfig with the first 'slice_count' nodes from the original
        configuration, which can be used for testing node removal operations.

        Args:
            nodes_config (NodesConfig): Original nodes configuration
            required_signatures (int): Number of required signatures for the new configuration
            slice_count (int): Number of nodes to include in the new configuration

        Returns:
            NodesConfig: A new nodes configuration with only the selected nodes
        """
        selected_nodes = nodes_config.nodes[:slice_count]

        return NodesConfig(
            required_signatures=required_signatures, nodes=selected_nodes
        )

    def load_nodes_to_add(
        self, nodes_config: NodesConfig, required_signatures: int, attach_count: int
    ) -> NodesConfig:
        """Create a node configuration for adding nodes.

        Creates a new NodesConfig based on the first 'attach_count' nodes from the original
        configuration, which can be used for testing node addition operations.

        Args:
            nodes_config (NodesConfig): Original nodes configuration
            required_signatures (int): Number of required signatures for the new configuration
            attach_count (int): Number of nodes to include in the new configuration

        Returns:
            NodesConfig: A new nodes configuration with the selected nodes recreated
        """
        selected_nodes = [
            NodeConfig(node_config.payment_vkh, node_config.feed_vkh)
            for node_config in nodes_config.nodes[:attach_count]
        ]

        return NodesConfig(
            required_signatures=required_signatures, nodes=selected_nodes
        )

    def filter_all_agg_states(
        self, utxos: Sequence[UTxO], policy_hash: str
    ) -> list[UTxO]:
        """Filter UTxOs for empty or expired aggregation states.

        Args:
            utxos: List of UTxOs to filter

        Returns:
            List of AggState UTxOs
        """
        agg_state = filter_utxos_by_token_name(
            utxos, ScriptHash(bytes.fromhex(policy_hash)), "AggregationState"
        )
        utxos_with_datum = convert_cbor_to_agg_states(agg_state)

        return [
            utxo
            for utxo in utxos_with_datum
            if utxo.output.datum and isinstance(utxo.output.datum, AggStateVariant)
        ]

    def filter_all_reward_transports(
        self, utxos: Sequence[UTxO], policy_hash: str
    ) -> list[UTxO]:
        """Filter UTxOs for Reward Transports.

        Args:
            utxos: List of UTxOs to filter

        Returns:
            List of RewardTransport UTxOs
        """
        reward_transports = filter_utxos_by_token_name(
            utxos, ScriptHash(bytes.fromhex(policy_hash)), "RewardTransport"
        )
        utxos_with_datum = convert_cbor_to_transports(reward_transports)

        return [
            utxo
            for utxo in utxos_with_datum
            if utxo.output.datum
            and isinstance(utxo.output.datum, RewardTransportVariant)
        ]
