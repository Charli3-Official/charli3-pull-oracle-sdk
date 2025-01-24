"""Odv Client deployment configuration and YAML loader."""

from dataclasses import dataclass
from pathlib import Path

from charli3_offchain_core.cli.config.network import NetworkConfig
from charli3_offchain_core.cli.config.token import TokenConfig
from charli3_offchain_core.cli.config.utils import load_yaml_config


@dataclass
class OdvClientConfig:
    """Complete Odv Client configuration."""

    network: NetworkConfig
    oracle_script_address: str
    tokens: TokenConfig

    @classmethod
    def from_yaml(cls, path: Path | str) -> "OdvClientConfig":
        """Load configuration from YAML file."""
        data = load_yaml_config(path)

        return cls(
            network=NetworkConfig.from_dict(data.get("network", {})),
            oracle_script_address=data["oracle_address"],
            tokens=TokenConfig.from_dict(data.get("tokens", {})),
        )
