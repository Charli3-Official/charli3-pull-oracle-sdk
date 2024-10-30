"""Base CLI utilities and helper functions for oracle deployment."""

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import click
from pycardano import (
    Address,
    BlockFrostChainContext,
    Network,
    PaymentSigningKey,
    PaymentVerificationKey,
    ScriptHash,
    UTxO,
)
from pycardano.backend import OgmiosV6ChainContext
from pycardano.backend.kupo import KupoChainContextExtension

from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import Asset, OracleConfiguration
from charli3_offchain_core.oracle.deployment.orchestrator import DeploymentStatus

from .config.deployment import DeploymentConfig
from .config.keys import KeyManager

logger = logging.getLogger(__name__)

MIN_TRANSPORT_COUNT = 4


@dataclass
class LoadedKeys:
    """Container for loaded keys and address."""

    payment_sk: PaymentSigningKey
    payment_vk: PaymentVerificationKey
    stake_vk: PaymentVerificationKey
    address: Address


@dataclass
class DerivedAddresses:
    """Container for derived deployment addresses."""

    admin_address: Address
    script_address: Address


def derive_deployment_addresses(
    config: DeploymentConfig,
    contracts: OracleContracts,
) -> DerivedAddresses:
    """Derive both deployment addresses from config and contracts.

    Args:
        config: Deployment configuration
        contracts: Oracle contracts

    Returns:
        DerivedAddresses containing reference and script addresses

    Raises:
        ValueError: If wallet configuration is invalid
    """
    # Load wallet keys and derive reference address
    if config.network.wallet.mnemonic:
        _, _, _, admin_addr = KeyManager.load_from_mnemonic(
            config.network.wallet.mnemonic,
            config.network.network,
        )
    elif all(
        [
            config.network.wallet.payment_skey_path,
            config.network.wallet.payment_vkey_path,
            config.network.wallet.stake_vkey_path,
        ]
    ):
        _, _, _, admin_addr = KeyManager.load_from_files(
            config.network.wallet.payment_skey_path,
            config.network.wallet.payment_vkey_path,
            config.network.wallet.stake_vkey_path,
            config.network.network,
        )
    else:
        raise ValueError("Must provide either mnemonic or all key file paths")

    # Create oracle configuration for script address derivation
    oracle_config = OracleConfiguration(
        platform_auth_nft=bytes.fromhex(config.tokens.platform_auth_policy),
        closing_period_length=config.timing.closing_period,
        reward_dismissing_period_length=config.timing.reward_dismissing_period,
        fee_token=Asset(
            policy_id=bytes.fromhex(config.tokens.fee_token_policy),
            name=bytes.fromhex(config.tokens.fee_token_name),
        ),
    )

    # Derive script address from validator
    manager_contract = contracts.apply_spend_params(oracle_config)
    script_addr = (
        manager_contract.mainnet_addr
        if config.network.network == Network.MAINNET
        else manager_contract.testnet_addr
    )

    return DerivedAddresses(
        admin_address=admin_addr,
        script_address=script_addr,
    )


def validate_platform_auth_utxo(utxos: list[UTxO], auth_policy_id: str) -> UTxO:
    """Validate and return platform auth UTxO."""
    if not utxos:
        raise click.ClickException("No UTxOs found at reference address")

    auth_policy_hash = ScriptHash(bytes.fromhex(auth_policy_id))

    for utxo in utxos:
        assets = utxo.output.amount.multi_asset
        if assets and auth_policy_hash in assets:
            return utxo

    raise click.ClickException(
        f"No UTxO found with platform auth NFT (policy: {auth_policy_id})"
    )


def load_keys_with_validation(
    config: DeploymentConfig, contracts: OracleContracts
) -> LoadedKeys:
    """Load and validate keys from config."""
    try:
        # Load keys and get derived addresses
        derived = derive_deployment_addresses(config, contracts)

        if config.network.wallet.mnemonic:
            payment_sk, payment_vk, stake_vk, _ = KeyManager.load_from_mnemonic(
                config.network.wallet.mnemonic,
                config.network.network,
            )
        else:
            payment_sk, payment_vk, stake_vk, _ = KeyManager.load_from_files(
                config.network.wallet.payment_skey_path,
                config.network.wallet.payment_vkey_path,
                config.network.wallet.stake_vkey_path,
                config.network.network,
            )

        return LoadedKeys(payment_sk, payment_vk, stake_vk, derived.admin_address)

    except Exception as e:
        raise click.ClickException(f"Failed to load keys: {e}") from e


def validate_deployment_config(config: DeploymentConfig) -> None:
    """Validate deployment configuration parameters."""
    if config.transport_count < MIN_TRANSPORT_COUNT:
        raise click.ClickException(
            f"Transport count must be at least {MIN_TRANSPORT_COUNT}"
        )

    if config.timing.closing_period <= 0:
        raise click.ClickException("Closing period must be positive")

    if config.timing.reward_dismissing_period <= config.timing.closing_period:
        raise click.ClickException(
            "Reward dismissing period must be greater than closing period"
        )

    if config.fees.node_fee <= 0 or config.fees.platform_fee <= 0:
        raise click.ClickException("Fees must be positive")


def create_chain_context(
    config: DeploymentConfig,
) -> BlockFrostChainContext | KupoChainContextExtension:
    """Create appropriate chain context based on configuration."""
    if config.network.blockfrost:
        return BlockFrostChainContext(
            project_id=config.network.blockfrost.project_id,
            network=config.network.network,
        )
    else:
        # Must be Ogmios/Kupo
        ogmios_url = config.network.ogmios_kupo.ogmios_url
        host, port, secure = parse_ws_url(ogmios_url)

        ogmios_context = OgmiosV6ChainContext(
            host=host,
            port=port,
            secure=secure,
            network=config.network.network,
        )
        return KupoChainContextExtension(
            ogmios_context,
            config.network.ogmios_kupo.kupo_url,
        )


def format_status_update(status: DeploymentStatus, message: str) -> None:
    """Format and display deployment status updates."""
    status_colors = {
        DeploymentStatus.NOT_STARTED: "white",
        DeploymentStatus.CHECKING_REFERENCE_SCRIPTS: "blue",
        DeploymentStatus.CREATING_MANAGER_REFERENCE: "yellow",
        DeploymentStatus.CREATING_NFT_REFERENCE: "yellow",
        DeploymentStatus.BUILDING_START_TX: "blue",
        DeploymentStatus.SUBMITTING_START_TX: "yellow",
        DeploymentStatus.WAITING_CONFIRMATION: "yellow",
        DeploymentStatus.COMPLETED: "green",
        DeploymentStatus.FAILED: "red",
    }

    color = status_colors.get(status, "white")
    click.secho(f"\n[{status}]", fg=color, bold=True)
    click.secho(message)


def parse_ws_url(url: str) -> tuple[str, int, bool]:
    """Parse WebSocket URL into host, port, and secure flag."""
    parsed = urlparse(url)

    # Determine if secure based on scheme
    secure = parsed.scheme in ("wss", "https")

    # Extract host without port if port is in the URL
    host = parsed.hostname or parsed.netloc.split(":")[0]

    # Get port or use defaults
    if parsed.port:
        port = parsed.port
    else:
        port = 443 if secure else 1337  # Default ports

    return host, port, secure
