"""Escrow deployment configuration and YAML loader."""

from dataclasses import dataclass
from pathlib import Path

from pycardano import Address

from charli3_offchain_core.cli.config.network import NetworkConfig
from charli3_offchain_core.cli.config.utils import load_yaml_config


@dataclass
class EscrowConfig:
    """Complete Escrow deployment configuration."""

    network: NetworkConfig
    blueprint_path: Path = Path("artifacts/plutus.json")
    reference_script_addr: Address | None = None

    @classmethod
    def from_yaml(cls, path: Path | str) -> "EscrowConfig":
        """Load configuration from YAML file."""
        data = load_yaml_config(path)

        ref_addr = data.get("reference_script_addr", None)
        if ref_addr:
            ref_addr = Address.from_primitive(ref_addr)
        else:
            ref_addr = None

        return cls(
            network=NetworkConfig.from_dict(data.get("network", {})),
            blueprint_path=Path(data.get("blueprint_path", "artifacts/plutus.json")),
            reference_script_addr=ref_addr,
        )
