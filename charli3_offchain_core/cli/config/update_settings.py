"""Oracle update settings configuraiton and YAML loader."""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pycardano import Address, TransactionId, TransactionInput

from charli3_offchain_core.cli.config.deployment import (
    DeploymentConfig,
)
from charli3_offchain_core.oracle.config import OracleTokenNames


@dataclass
class PlatformTxConfig(DeploymentConfig):
    contract_address: Address | None = None
    token_names: OracleTokenNames | None = None

    @classmethod
    def from_yaml(cls, path: Path | str) -> "PlatformTxConfig":
        path = Path(path)

        parent_config = super().from_yaml(path)

        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as err:
            raise ValueError("Invalid YAML file") from err
        except FileNotFoundError as err:
            raise FileNotFoundError("Configuration file not found") from err

        contract_address = cls._parse_contract_address(data.get("oracle_address"))
        token_names = OracleTokenNames.from_network(parent_config.network.network)

        instance = cls(
            network=parent_config.network,
            tokens=parent_config.tokens,
            fees=parent_config.fees,
            timing=parent_config.timing,
            transport_count=parent_config.transport_count,
            multi_sig=parent_config.multi_sig,
            blueprint_path=parent_config.blueprint_path,
            create_reference=False,
            contract_address=contract_address,
            token_names=token_names,
        )
        return instance

    @staticmethod
    def _parse_contract_address(address_data: str) -> Address:
        """Parse and validate contract address from configuration."""
        if not isinstance(address_data, str):
            raise ValueError("script_address must be a string")
        try:
            return Address.from_primitive(address_data)
        except Exception as err:
            raise ValueError("Invalid contract address format") from err

    @staticmethod
    def _parse_token_hash(hash_data: str) -> bytes:
        """Parse and validate script hash from configuration."""
        if not isinstance(hash_data, str):
            raise ValueError("script_hash must be a string")
        try:
            return bytes.fromhex(hash_data)
        except ValueError as err:
            raise ValueError("Invalid script hash format") from err

    @staticmethod
    def _parse_reference_input(reference: str) -> TransactionInput:
        """Parse reference script input"""
        tx_id_hex, index = reference.split("#")
        tx_id = TransactionId(bytes.fromhex(tx_id_hex))
        index = int(index)
        return TransactionInput(tx_id, index)
