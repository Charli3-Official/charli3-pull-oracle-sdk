"""Oracle deployment configuration and YAML loader."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from pycardano import Network

from charli3_offchain_core.cli.config.multisig import MultisigConfig

from .keys import WalletConfig


@dataclass
class BlockfrostConfig:
    """Blockfrost backend configuration."""

    project_id: str
    api_url: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "BlockfrostConfig":
        """Create Blockfrost config from dictionary."""
        return cls(project_id=data["project_id"], api_url=data.get("api_url"))


@dataclass
class OgmiosKupoConfig:
    """Ogmios/Kupo backend configuration."""

    ogmios_url: str
    kupo_url: str

    @classmethod
    def from_dict(cls, data: dict) -> "OgmiosKupoConfig":
        """Create Ogmios/Kupo config from dictionary."""
        return cls(ogmios_url=data["ogmios_url"], kupo_url=data["kupo_url"])


@dataclass
class NetworkConfig:
    """Network-specific configuration."""

    network: Network
    wallet: WalletConfig
    # Optional backend configurations
    blockfrost: BlockfrostConfig | None = None
    ogmios_kupo: OgmiosKupoConfig | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkConfig":
        """Create network config from dictionary."""
        return cls(
            network=Network[data.get("network", "TESTNET").upper()],
            wallet=WalletConfig.from_dict(data.get("wallet", {})),
            blockfrost=(
                BlockfrostConfig.from_dict(data["blockfrost"])
                if "blockfrost" in data
                else None
            ),
            ogmios_kupo=(
                OgmiosKupoConfig.from_dict(data["ogmios_kupo"])
                if "ogmios_kupo" in data
                else None
            ),
        )

    def validate(self) -> None:
        """Validate backend configuration."""
        if not self.blockfrost and not self.ogmios_kupo:
            raise ValueError(
                "Either Blockfrost or Ogmios/Kupo configuration must be provided"
            )
        if self.blockfrost and self.ogmios_kupo:
            raise ValueError(
                "Cannot specify both Blockfrost and Ogmios/Kupo configuration"
            )


@dataclass
class TokenConfig:
    """Token configuration."""

    platform_auth_policy: str
    fee_token_policy: str
    fee_token_name: str

    @classmethod
    def from_dict(cls, data: dict) -> "TokenConfig":
        """Create token config from dictionary."""
        return cls(
            platform_auth_policy=data["platform_auth_policy"],
            fee_token_policy=data["fee_token_policy"],
            fee_token_name=data["fee_token_name"],
        )


@dataclass
class FeeConfig:
    """Fee configuration."""

    node_fee: int
    platform_fee: int

    @classmethod
    def from_dict(cls, data: dict) -> "FeeConfig":
        """Create fee config from dictionary."""
        return cls(node_fee=data["node_fee"], platform_fee=data["platform_fee"])


@dataclass
class TimingConfig:
    """Timing parameters configuration."""

    closing_period: int = 3600000
    reward_dismissing_period: int = 7200000
    aggregation_liveness: int = 300000
    time_uncertainty: int = 60000
    iqr_multiplier: int = 150

    @classmethod
    def from_dict(cls, data: dict) -> "TimingConfig":
        """Create timing config from dictionary."""
        return cls(
            closing_period=data.get("closing_period", 3600000),
            reward_dismissing_period=data.get("reward_dismissing_period", 7200000),
            aggregation_liveness=data.get("aggregation_liveness", 300000),
            time_uncertainty=data.get("time_uncertainty", 60000),
            iqr_multiplier=data.get("iqr_multiplier", 150),
        )


@dataclass
class NodeConfig:
    """Configuration for oracle node."""

    feed_vkh: str  # Hex encoded feed verification key hash
    payment_vkh: str  # Hex encoded payment verification key hash

    @classmethod
    def from_dict(cls, data: dict) -> "NodeConfig":
        """Create node config from dictionary."""
        return cls(
            feed_vkh=data["feed_vkh"],
            payment_vkh=data["payment_vkh"],
        )


@dataclass
class NodesConfig:
    """Node configuration parameters."""

    required_signatures: int
    nodes: list[NodeConfig]

    @classmethod
    def from_dict(cls, data: dict) -> "NodesConfig":
        """Create nodes config from dictionary."""
        return cls(
            required_signatures=data["required_signatures"],
            nodes=[NodeConfig.from_dict(node) for node in data["nodes"]],
        )


@dataclass
class DeploymentConfig:
    """Complete deployment configuration."""

    network: NetworkConfig
    tokens: TokenConfig
    fees: FeeConfig
    timing: TimingConfig
    nodes: NodesConfig
    transport_count: int = 4
    multi_sig: MultisigConfig | None = None
    blueprint_path: Path = Path("artifacts/plutus.json")
    create_reference: bool = True

    @classmethod
    def from_yaml(cls, path: Path | str) -> "DeploymentConfig":
        """Load configuration from YAML file."""
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
            tokens=TokenConfig.from_dict(data.get("tokens", {})),
            multi_sig=MultisigConfig.from_dict(data.get("multisig", {})),
            fees=FeeConfig.from_dict(data.get("fees", {})),
            timing=TimingConfig.from_dict(data.get("timing", {})),
            nodes=NodesConfig.from_dict(data.get("nodes", {})),
            transport_count=data.get("transport_count", 4),
            blueprint_path=Path(data.get("blueprint_path", "artifacts/plutus.json")),
            create_reference=data.get("create_reference", True),
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
