from dataclasses import dataclass
from pathlib import Path

from .multisig import MultisigConfig
from .network import NetworkConfig
from .token import TokenConfig
from .utils import load_yaml_config


@dataclass
class ManagementConfig:
    """Minimal config required for lifecycle operations."""
    network: NetworkConfig
    tokens: TokenConfig
    oracle_address: str
    multi_sig: MultisigConfig
    blueprint_path: Path = Path("artifacts/plutus.json")

    @classmethod
    def from_yaml(cls, path: Path | str) -> "ManagementConfig":
        data = load_yaml_config(path)
        return cls(
            network=NetworkConfig.from_dict(data.get("network", {})),
            tokens=TokenConfig.from_dict(data.get("tokens", {})),
            oracle_address=data.get("oracle_address", ""),
            multi_sig=MultisigConfig.from_dict(data.get("multisig", {})),
            blueprint_path=Path(data.get("blueprint_path", "artifacts/plutus.json")),
        )