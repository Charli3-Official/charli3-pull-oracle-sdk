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

    @classmethod
    def from_yaml(cls, path: Path) -> "TxConfig":
        """Load transaction config from YAML file."""
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with path.open("r") as f:
            data = yaml.safe_load(f)

        return cls(
            network=NetworkConfig.from_dict(data.get("network", {})),
            script_address=data["script_address"],
            policy_id=data["policy_id"],
            fee_token_policy_id=data["fee_token"]["fee_token_policy_id"],
            fee_token_name=data["fee_token"]["fee_token_name"],
            wallet=WalletConfig.from_dict(data["wallet"]),
        )

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
