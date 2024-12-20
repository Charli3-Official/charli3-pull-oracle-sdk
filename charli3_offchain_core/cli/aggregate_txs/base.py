"""Base utilities and types for oracle transaction CLI commands."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import click
import yaml
from pycardano import Address, AssetName, PaymentSigningKey, ScriptHash

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.base import create_chain_query
from charli3_offchain_core.cli.config.deployment import NetworkConfig
from charli3_offchain_core.cli.config.keys import KeyManager, WalletConfig

logger = logging.getLogger(__name__)


@dataclass
class TxConfig:
    """Transaction configuration parameters."""

    network: NetworkConfig
    script_address: str  # Oracle script address
    policy_id: str  # Oracle NFT policy ID
    fee_token_policy_id: str  # Fee token policy ID
    fee_token_name: str  # Fee token name
    wallet: WalletConfig  # Wallet configuration with mnemonic

    def validate(self) -> None:
        """Validate complete configuration."""
        # Validate network configuration
        if not self.network:
            raise ValueError("Network configuration required")
        self.network.validate()

        # Validate addresses and IDs
        if not self.script_address:
            raise ValueError("Script address required")
        if not self.policy_id:
            raise ValueError("Policy ID required")
        if not self.fee_token_policy_id:
            raise ValueError("Fee token policy ID required")
        if not self.fee_token_name:
            raise ValueError("Fee token name required")

        # Validate wallet configuration
        if not self.wallet:
            raise ValueError("Wallet configuration required")
        if not self.wallet.mnemonic:
            raise ValueError("Wallet mnemonic required")

    @classmethod
    def from_yaml(cls, path: Path) -> "TxConfig":
        """Load transaction config from YAML file."""
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        try:
            with path.open("r") as f:
                data = yaml.safe_load(f)

            # Handle both old and new fee token field names
            if "fee_token" in data:
                fee_token = data["fee_token"]
                fee_token_policy_id = fee_token.get(
                    "fee_token_policy"
                ) or fee_token.get("fee_token_policy_id")
                fee_token_name = fee_token["fee_token_name"]
            else:
                raise ValueError("Missing fee_token configuration")

            if not fee_token_policy_id:
                raise ValueError("Missing fee token policy ID")

            return cls(
                network=NetworkConfig.from_dict(data.get("network", {})),
                script_address=data["oracle_address"],
                policy_id=data["policy_id"],
                fee_token_policy_id=fee_token_policy_id,
                fee_token_name=fee_token_name,
                wallet=WalletConfig.from_dict(data["wallet"]),
            )
        except KeyError as e:
            logger.error("Failed to load configuration: %s", e)
            raise ValueError(f"Invalid configuration file: {e}") from e
        except Exception as e:
            logger.error("Failed to load configuration: %s", e)
            raise ValueError(f"Error loading configuration: {e}") from e

    def get_script_address(self) -> Address:
        """Get script address as Address object."""
        return Address.from_primitive(self.script_address)

    def get_policy_id(self) -> ScriptHash:
        """Get policy ID as ScriptHash object."""
        return ScriptHash(bytes.fromhex(self.policy_id))


class TransactionContext:
    """Holds common transaction context and utilities."""

    def __init__(self, config: TxConfig) -> None:
        self.config = config
        self.chain_query = create_chain_query(config.network)
        self.tx_manager = TransactionManager(self.chain_query)
        self.script_address = config.get_script_address()
        self.policy_id = config.get_policy_id()
        self.fee_token_policy_id = ScriptHash(bytes.fromhex(config.fee_token_policy_id))
        self.fee_token_name = AssetName(bytes.fromhex(config.fee_token_name))

    def load_keys(self) -> tuple[PaymentSigningKey, Address]:
        """Load keys from mnemonic."""
        payment_sk, _, _, change_address = KeyManager.load_from_mnemonic(
            self.config.wallet.mnemonic, self.config.network.network
        )
        return payment_sk, change_address


def tx_options(f: Callable) -> Callable:
    """Common transaction command options.

    Args:
        f: Function to decorate

    Returns:
        Decorated function with common options
    """
    f = click.option(
        "--config",
        type=click.Path(exists=True, path_type=Path),
        required=True,
        help="Path to transaction configuration YAML",
    )(f)

    return f
