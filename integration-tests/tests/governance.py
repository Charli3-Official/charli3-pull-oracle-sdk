import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from pycardano import ScriptHash, UTxO
from pycardano.hash import VerificationKeyHash

from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.config.nodes import NodesConfig
from charli3_offchain_core.cli.governance import setup_management_from_config
from charli3_offchain_core.models.oracle_datums import (
    AggState,
    RewardAccountVariant,
)
from charli3_offchain_core.oracle.governance.orchestrator import GovernanceOrchestrator
from charli3_offchain_core.oracle.utils.asset_checks import filter_utxos_by_token_name
from charli3_offchain_core.oracle.utils.state_checks import (
    convert_cbor_to_agg_states,
    convert_cbor_to_reward_accounts,
)

from .test_utils import logger

# Number of retry attempts for test operations
MAX_TEST_RETRIES = 3


class GovernanceBase:
    """Base class for Oracle Governance integration tests.

    This class provides common setup and utility methods for testing oracle governance
    operations such as adding, removing, or updating node configurations. It loads
    configuration from a YAML file and initializes the necessary components for
    interacting with the blockchain.

    Attributes:
        NETWORK (Network): The blockchain network to use for testing (TESTNET).
        DIR_PATH (str): The directory path where this test file is located.
        config_path (Path): Path to the configuration YAML file.
        management_config: Configuration for managing the oracle.
        oracle_configuration: Configuration for the oracle.
        loaded_key: The cryptographic keys used for signing transactions.
        oracle_addresses: Addresses associated with the oracle.
        chain_query: Interface for querying the blockchain.
        tx_manager: Manager for building and submitting transactions.
        platform_auth_finder: Component to find platform authentication.
        governance_orchestrator (GovernanceOrchestrator): Orchestrator for governance operations.
    """

    DIR_PATH: ClassVar[str] = os.path.dirname(os.path.realpath(__file__))

    def setup_method(self, method: Any) -> None:
        """Set up test configuration and environment for each test method.

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

            # Initialize escrow configuration and governance orchestrator
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

    def prepare_nodes_for_removal(
        self, nodes_config: NodesConfig, count_to_remove: int
    ) -> tuple[int, list[VerificationKeyHash]]:
        """Prepare a list of nodes for removal testing.

        Creates a subset of nodes from the original configuration that will be
        used for testing node removal operations. Also calculates the updated
        signature threshold after removal.

        Args:
            nodes_config (NodesConfig): Original nodes configuration
            count_to_remove (int): Number of nodes to select for removal

        Returns:
            Tuple[int, List[VerificationKeyHash]]: A tuple containing:
                - The adjusted signature threshold after removal
                - List of node configurations to be removed
        """
        nodes_to_remove: list[VerificationKeyHash] = nodes_config.nodes[
            :count_to_remove
        ]
        adjusted_signature_threshold = (
            nodes_config.required_signatures - count_to_remove
        )

        return (adjusted_signature_threshold, nodes_to_remove)

    def prepare_nodes_for_addition(
        self, nodes_config: NodesConfig, required_signatures: int, count_to_add: int
    ) -> NodesConfig:
        """Create a node configuration for adding new nodes.

        Creates a new NodesConfig with a subset of nodes from the original
        configuration, which can be used for testing node addition operations.

        Args:
            nodes_config (NodesConfig): Original nodes configuration
            required_signatures (int): Number of required signatures for the new configuration
            count_to_add (int): Number of nodes to include in the new configuration

        Returns:
            NodesConfig: A new nodes configuration with the selected nodes
        """
        new_nodes = nodes_config.nodes[:count_to_add]

        return NodesConfig(required_signatures=required_signatures, nodes=new_nodes)

    def extract_aggregation_state_utxos(
        self, utxos: Sequence[UTxO], policy_hash: str
    ) -> list[UTxO]:
        """Extract UTxOs containing valid AggState tokens and datums.

        Filters and returns UTxOs that contain AggState tokens with
        valid AggState datums.

        Args:
            utxos (Sequence[UTxO]): List of UTxOs to filter
            policy_hash (str): The policy hash to filter tokens by

        Returns:
            List[UTxO]: List of UTxOs with valid AggState datums
        """
        # Filter UTxOs containing AggState tokens
        agg_state_utxos = filter_utxos_by_token_name(
            utxos, ScriptHash(bytes.fromhex(policy_hash)), "C3AS"
        )

        # Convert CBOR encoded datums to AggState objects
        utxos_with_datum = convert_cbor_to_agg_states(agg_state_utxos)

        # Return only UTxOs with valid AggState datums
        return [
            utxo
            for utxo in utxos_with_datum
            if utxo.output.datum and isinstance(utxo.output.datum, AggState)
        ]

    def extract_reward_account_utxos(
        self, utxos: Sequence[UTxO], policy_hash: str
    ) -> list[UTxO]:
        """Extract UTxOs containing valid RewardAccount tokens and datums.

        Filters and returns UTxOs that contain RewardAccount tokens with
        valid RewardAccountVariant datums.

        Args:
            utxos (Sequence[UTxO]): List of UTxOs to filter
            policy_hash (str): The policy hash to filter tokens by

        Returns:
            List[UTxO]: List of UTxOs with valid RewardAccountVariant datums
        """
        # Filter UTxOs containing RewardAccount tokens
        reward_account_utxos = filter_utxos_by_token_name(
            utxos, ScriptHash(bytes.fromhex(policy_hash)), "C3RA"
        )

        # Convert CBOR encoded datums to RewardAccountVariant objects
        utxos_with_datum = convert_cbor_to_reward_accounts(reward_account_utxos)

        # Return only UTxOs with valid RewardAccountVariant datums
        return [
            utxo
            for utxo in utxos_with_datum
            if utxo.output.datum and isinstance(utxo.output.datum, RewardAccountVariant)
        ]
