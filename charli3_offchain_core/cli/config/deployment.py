"""Oracle deployment configuration and YAML loader."""

from dataclasses import dataclass
from pathlib import Path

from .multisig import MultisigConfig
from .network import NetworkConfig
from .settings import FeeConfig, TimingConfig
from .token import TokenConfig
from .utils import load_yaml_config


@dataclass
class DeploymentConfig:
    """Complete deployment configuration."""

    network: NetworkConfig
    tokens: TokenConfig
    fees: FeeConfig
    timing: TimingConfig
    transport_count: int = 4
    multi_sig: MultisigConfig | None = None
    blueprint_path: Path = Path("artifacts/plutus.json")
    create_reference: bool = True

    @classmethod
    def from_yaml(cls, path: Path | str) -> "DeploymentConfig":
        """Load configuration from YAML file."""
        data = load_yaml_config(path)

        return cls(
            network=NetworkConfig.from_dict(data.get("network", {})),
            tokens=TokenConfig.from_dict(data.get("tokens", {})),
            multi_sig=MultisigConfig.from_dict(data.get("multisig", {})),
            fees=FeeConfig.from_dict(data.get("fees", {})),
            timing=TimingConfig.from_dict(data.get("timing", {})),
            transport_count=data.get("transport_count", 4),
            blueprint_path=Path(data.get("blueprint_path", "artifacts/plutus.json")),
            create_reference=data.get("create_reference", True),
        )
