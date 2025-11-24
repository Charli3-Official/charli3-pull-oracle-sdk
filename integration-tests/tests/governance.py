import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pycardano import Address, ScriptHash, UTxO

from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.cli.config.nodes import NodesConfig
from charli3_offchain_core.cli.governance import setup_management_from_config
from charli3_offchain_core.contracts.aiken_loader import RewardEscrowContract
from charli3_offchain_core.models.oracle_datums import (
    AggState,
    RewardTransportVariant,
)
from charli3_offchain_core.oracle.governance.orchestrator import GovernanceOrchestrator
from charli3_offchain_core.oracle.utils.asset_checks import filter_utxos_by_token_name
from charli3_offchain_core.oracle.utils.state_checks import (
    convert_cbor_to_agg_states,
    convert_cbor_to_transports,
)

from .async_utils import async_retry
from .test_utils import logger, update_config_file, wait_for_indexing

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
        escrow_config (EscrowConfig): Configuration for the escrow contract.
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
            self.escrow_config = EscrowConfig.from_yaml(self.config_path)  # noqa
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
    ) -> tuple[int, list[NodeConfig]]:  # noqa
        """Prepare a list of nodes for removal testing.

        Creates a subset of nodes from the original configuration that will be
        used for testing node removal operations. Also calculates the updated
        signature threshold after removal.

        Args:
            nodes_config (NodesConfig): Original nodes configuration
            count_to_remove (int): Number of nodes to select for removal

        Returns:
            Tuple[int, List[NodeConfig]]: A tuple containing:
                - The adjusted signature threshold after removal
                - List of node configurations to be removed
        """
        nodes_to_remove = nodes_config.nodes[:count_to_remove]
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
        new_nodes = [
            NodeConfig(node_config.payment_vkh, node_config.feed_vkh)  # noqa
            for node_config in nodes_config.nodes[:count_to_add]
        ]

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

    def extract_reward_transport_utxos(
        self, utxos: Sequence[UTxO], policy_hash: str
    ) -> list[UTxO]:
        """Extract UTxOs containing valid RewardTransport tokens and datums.

        Filters and returns UTxOs that contain RewardTransport tokens with
        valid RewardTransportVariant datums.

        Args:
            utxos (Sequence[UTxO]): List of UTxOs to filter
            policy_hash (str): The policy hash to filter tokens by

        Returns:
            List[UTxO]: List of UTxOs with valid RewardTransportVariant datums
        """
        # Filter UTxOs containing RewardTransport tokens
        reward_transport_utxos = filter_utxos_by_token_name(
            utxos, ScriptHash(bytes.fromhex(policy_hash)), "C3RT"
        )

        # Convert CBOR encoded datums to RewardTransportVariant objects
        utxos_with_datum = convert_cbor_to_transports(reward_transport_utxos)

        # Return only UTxOs with valid RewardTransportVariant datums
        return [
            utxo
            for utxo in utxos_with_datum
            if utxo.output.datum
            and isinstance(utxo.output.datum, RewardTransportVariant)
        ]

    @pytest.mark.asyncio
    @async_retry(tries=MAX_TEST_RETRIES, delay=5)
    async def test_create_escrow_reference_script(self) -> None:
        """Test the creation of an escrow reference script.

        This test creates a reference script for the escrow contract and verifies
        that it was successfully created on the blockchain. It also updates the
        configuration file with the newly created escrow address and reward issuer
        address.

        The test uses retry mechanisms to handle potential network issues.

        Raises:
            AssertionError: If the escrow reference script is not found after creation.
        """
        logger.info("Starting Escrow contract reference script creation")

        # Load the escrow contract from the blueprint
        escrow_script = RewardEscrowContract.from_blueprint(
            self.escrow_config.blueprint_path
        )

        # Generate the address for the escrow script
        escrow_script_address = Address(
            payment_part=escrow_script.escrow_manager.script_hash,
            network=self.escrow_config.network.network,
        )
        logger.info(f"Escrow address: {escrow_script_address}")

        # Create the reference script transaction
        logger.info("Creating Escrow reference script")
        tx_build_result = await self.tx_manager.build_reference_script_tx(
            script=escrow_script.escrow_manager.contract,
            reference_script_address=escrow_script_address,
            admin_address=self.loaded_key.address,
            signing_key=self.loaded_key.payment_sk,
            reference_ada=6107270,  # Amount of ADA to lock with the reference script
        )

        logger.info("Manager reference script transaction built")

        # Sign and submit the transaction
        tx_status, _tx = await self.tx_manager.sign_and_submit(
            tx_build_result, [self.loaded_key.payment_sk]
        )

        logger.info("Escrow reference script transaction submitted")

        # Wait for the transaction to be indexed
        await wait_for_indexing(10)

        # Verify that the reference script now exists
        escrow_reference_script_utxo = await self.get_escrow_reference_script_utxo(
            escrow_script_address
        )

        assert (
            escrow_reference_script_utxo is not None
        ), "Escrow reference script not found after creation"

        logger.info(
            "The Escrow contract reference script has been created successfully."
        )

        # Update configuration file with new escrow and reward issuer addresses
        logger.info(
            f"Updating configuration file with new escrow address: {escrow_script_address}"
        )
        update_config_file(
            self.config_path,
            {"reference_script_addr": str(escrow_script_address)},
        )

        logger.info(f"Updating reward issuer address: {self.loaded_key.address}")
        update_config_file(
            self.config_path,
            {"reward_issuer_address": str(self.loaded_key.address)},
        )

    async def get_escrow_reference_script_utxo(
        self, escrow_address: Address
    ) -> UTxO | None:
        """Retrieve the reference script UTxO for the escrow contract.

        Queries the blockchain for UTxOs at the given escrow address and returns
        the first UTxO containing a reference script.

        Args:
            escrow_address (Address): The address of the escrow contract.

        Returns:
            Optional[UTxO]: The UTxO containing the reference script, or None if not found.
        """
        # Get all UTxOs at the escrow address
        utxos = await self.chain_query.get_utxos(escrow_address)

        # Filter for UTxOs that contain a reference script
        reference_utxos = [utxo for utxo in utxos if utxo.output.script]

        # Return the first reference script UTxO, or None if none exist
        return reference_utxos[0] if reference_utxos else None
