import json
from pathlib import Path
from typing import Any, NamedTuple

from pycardano import (
    Address,
    PaymentSigningKey,
    PaymentVerificationKey,
    StakeVerificationKey,
)

from charli3_offchain_core.cli.config.formatting import format_status_update
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import (
    Asset,
    FeeConfig,
    NoDatum,
    OracleConfiguration,
    RewardPrices,
)
from charli3_offchain_core.oracle.config import (
    OracleDeploymentConfig,
    OracleScriptConfig,
)
from charli3_offchain_core.oracle.deployment.orchestrator import (
    OracleDeploymentOrchestrator,
)
from charli3_offchain_core.oracle.lifecycle.orchestrator import LifecycleOrchestrator
from charli3_offchain_core.platform.auth.token_finder import PlatformAuthFinder

from ..blockchain.chain_query import ChainQuery
from ..blockchain.transactions import TransactionManager
from ..platform.auth.orchestrator import (
    PlatformAuthOrchestrator,
)
from .base import (
    create_chain_query,
    derive_deployment_addresses,
    load_keys_with_validation,
    validate_deployment_config,
)
from .config.deployment import DeploymentConfig
from .config.keys import KeyManager
from .config.management import ManagementConfig
from .config.platform import PlatformAuthConfig


class OracleAddresses(NamedTuple):
    admin_address: str
    script_address: str
    platform_address: str


def setup_platform_from_config(config: Path, metadata: Path | None) -> tuple[
    PlatformAuthConfig,
    PaymentSigningKey,
    PaymentVerificationKey,
    StakeVerificationKey,
    Address,
    ChainQuery,
    TransactionManager,
    PlatformAuthOrchestrator,
    Any,
]:
    """Set up all required modules that are common across platform functions from config file."""
    auth_config = PlatformAuthConfig.from_yaml(config)
    payment_sk, payment_vk, stake_vk, default_addr = KeyManager.load_from_config(
        auth_config.network.wallet
    )

    chain_query = create_chain_query(auth_config.network)
    tx_manager = TransactionManager(chain_query)

    orchestrator = PlatformAuthOrchestrator(
        chain_query=chain_query,
        tx_manager=tx_manager,
        status_callback=format_status_update,
    )
    meta_data = None
    if metadata:
        with metadata.open() as f:
            meta_data = json.load(f)

    return (
        auth_config,
        payment_sk,
        payment_vk,
        stake_vk,
        default_addr,
        chain_query,
        tx_manager,
        orchestrator,
        meta_data,
    )


def setup_oracle_from_config(
    config: Path,
) -> tuple[
    DeploymentConfig,
    PaymentSigningKey,
    PaymentVerificationKey,
    OracleAddresses,
    ChainQuery,
    TransactionManager,
    OracleDeploymentOrchestrator,
    PlatformAuthFinder,
    dict,
]:
    """Set up all required modules for oracle deployment from config file."""
    # Load and validate configuration
    deployment_config = DeploymentConfig.from_yaml(config)
    validate_deployment_config(deployment_config)

    # Load base contracts
    base_contracts = OracleContracts.from_blueprint(deployment_config.blueprint_path)

    # Create oracle configuration
    oracle_config = OracleConfiguration(
        platform_auth_nft=bytes.fromhex(deployment_config.tokens.platform_auth_policy),
        closing_period_length=deployment_config.timing.closing_period,
        reward_dismissing_period_length=deployment_config.timing.reward_dismissing_period,
        fee_token=Asset(
            policy_id=bytes.fromhex(deployment_config.tokens.fee_token_policy),
            name=bytes.fromhex(deployment_config.tokens.fee_token_name),
        ),
    )

    # Parameterize contracts
    parameterized_contracts = OracleContracts(
        spend=base_contracts.apply_spend_params(oracle_config),
        mint=base_contracts.mint,
    )

    # Load keys and derive addresses
    keys = load_keys_with_validation(deployment_config, parameterized_contracts)
    addresses = derive_deployment_addresses(deployment_config, parameterized_contracts)
    platform_address = (
        deployment_config.multi_sig.platform_addr or addresses.admin_address
    )

    # In your setup function, replace the dictionary creation with:
    oracle_addresses = OracleAddresses(
        admin_address=addresses.admin_address,
        script_address=addresses.script_address,
        platform_address=platform_address,
    )

    chain_query = create_chain_query(deployment_config.network)

    tx_manager = TransactionManager(chain_query)

    # Create configurations
    configs = {
        "script": OracleScriptConfig(
            create_manager_reference=deployment_config.create_reference,
            reference_ada_amount=64_000_000,
        ),
        "deployment": OracleDeploymentConfig(
            network=deployment_config.network.network,
            reward_transport_count=deployment_config.transport_count,
        ),
        "fee": FeeConfig(
            rate_nft=NoDatum(),
            reward_prices=RewardPrices(
                node_fee=deployment_config.fees.node_fee,
                platform_fee=deployment_config.fees.platform_fee,
            ),
        ),
        "fee_token": Asset(
            policy_id=bytes.fromhex(deployment_config.tokens.fee_token_policy),
            name=bytes.fromhex(deployment_config.tokens.fee_token_name),
        ),
    }

    # Initialize platform auth finder
    platform_auth_finder = PlatformAuthFinder(chain_query)

    # Initialize orchestrator
    orchestrator = OracleDeploymentOrchestrator(
        chain_query=chain_query,
        contracts=parameterized_contracts,
        tx_manager=tx_manager,
        status_callback=format_status_update,
    )

    return (
        deployment_config,
        keys.payment_sk,
        keys.payment_vk,
        oracle_addresses,
        chain_query,
        tx_manager,
        orchestrator,
        platform_auth_finder,
        configs,
    )


def setup_management_from_config(config: Path) -> tuple[
    ManagementConfig,
    PaymentSigningKey,
    OracleAddresses,
    ChainQuery,
    TransactionManager,
    LifecycleOrchestrator,
    PlatformAuthFinder,
]:
    management_config = ManagementConfig.from_yaml(config)
    base_contracts = OracleContracts.from_blueprint(management_config.blueprint_path)

    keys = load_keys_with_validation(management_config, base_contracts)
    addresses = derive_deployment_addresses(management_config, base_contracts)

    platform_address = (
        management_config.multi_sig.platform_addr or addresses.admin_address
    )

    oracle_addresses = OracleAddresses(
        admin_address=addresses.admin_address,
        script_address=management_config.oracle_address,
        platform_address=platform_address,
    )

    chain_query = create_chain_query(management_config.network)
    tx_manager = TransactionManager(chain_query)
    platform_auth_finder = PlatformAuthFinder(chain_query)

    orchestrator = LifecycleOrchestrator(
        chain_query=chain_query,
        tx_manager=tx_manager,
        script_address=oracle_addresses.script_address,
        status_callback=format_status_update,
    )

    return (
        management_config,
        keys.payment_sk,
        oracle_addresses,
        chain_query,
        tx_manager,
        orchestrator,
        platform_auth_finder,
    )
