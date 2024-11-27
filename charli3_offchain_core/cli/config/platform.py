import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from charli3_offchain_core.cli.config.deployment import NetworkConfig
from charli3_offchain_core.cli.config.multisig import MultisigConfig


@dataclass
class PlatformAuthConfig:
    """Configuration for platform authorization."""

    network: NetworkConfig
    multisig: MultisigConfig
    min_utxo_value: int = 2_000_000

    @classmethod
    def from_yaml(cls, path: Path | str) -> "PlatformAuthConfig":
        """Load platform auth configuration from YAML."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        # Load and parse YAML
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Resolve environment variables
        data = _resolve_env_vars(data)
        return cls(
            network=NetworkConfig.from_dict(data.get("network", {})),
            multisig=MultisigConfig.from_dict(data.get("multisig", {})),
            min_utxo_value=data.get("min_utxo_value", 2_000_000),
        )


def _resolve_env_vars(data: dict) -> dict:
    """Recursively resolve environment variables in configuration."""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, dict):
            resolved[key] = _resolve_env_vars(value)
        elif isinstance(value, str) and value.startswith("$"):
            env_var = value[1:]  # Remove $ prefix
            resolved[key] = os.environ.get(env_var, value)
        else:
            resolved[key] = value
    return resolved
