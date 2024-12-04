"""Simulated node implementation using real node keys."""

import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from nacl.signing import VerifyKey
from pycardano import PaymentSigningKey, PaymentVerificationKey, VerificationKeyHash

from charli3_offchain_core.cli.config.deployment import NetworkConfig, WalletConfig
from charli3_offchain_core.cli.txs.base import TxConfig
from charli3_offchain_core.oracle.transactions.builder import RewardsResult
from charli3_offchain_core.oracle.utils.signature_checks import encode_oracle_feed


class SimulatedNode:
    """Represents a simulated oracle node using real keys."""

    def __init__(
        self,
        signing_key: PaymentSigningKey,
        verification_key: PaymentVerificationKey,
        feed_vkh: VerificationKeyHash,
        payment_vkh: VerificationKeyHash,
    ) -> None:
        """Initialize node with provided keys.

        Args:
            signing_key: Payment signing key
            verification_key: Payment verification key
            feed_vkh: Feed verification key hash
            payment_vkh: Payment verification key hash
        """
        self.signing_key = signing_key
        self.verification_key = verification_key
        self.feed_vkh = feed_vkh
        self.payment_vkh = payment_vkh

        # Create nacl verify key for signature verification
        self._nacl_verify_key = VerifyKey(self.verification_key.payload)

    @classmethod
    def from_key_directory(cls, node_dir: Path) -> "SimulatedNode":
        """Create node from generated key directory.

        Args:
            node_dir: Directory containing node keys

        Returns:
            SimulatedNode: New node instance

        Raises:
            ValueError: If key files are missing or invalid
        """
        try:
            # Load keys from files
            signing_key = PaymentSigningKey.load(node_dir / "feed.skey")
            verification_key = PaymentVerificationKey.load(node_dir / "feed.vkey")

            # Load VKH values
            feed_vkh = VerificationKeyHash(
                bytes.fromhex((node_dir / "feed.vkh").read_text().strip())
            )
            payment_vkh = VerificationKeyHash(
                bytes.fromhex((node_dir / "payment.vkh").read_text().strip())
            )

            # Create instance using __init__
            return cls(signing_key, verification_key, feed_vkh, payment_vkh)

        except FileNotFoundError as e:
            raise ValueError(f"Missing key file in {node_dir}: {e}") from e
        except Exception as e:
            raise ValueError(f"Failed to load node keys from {node_dir}: {e}") from e

    @property
    def hex_feed_vkh(self) -> str:
        """Get feed verification key hash as hex."""
        return self.feed_vkh.to_primitive().hex()

    @property
    def hex_payment_vkh(self) -> str:
        """Get payment verification key hash as hex."""
        return self.payment_vkh.to_primitive().hex()

    def sign_feed(self, value: int, timestamp: int | None = None) -> tuple[int, bytes]:
        """Sign feed value and return signature.

        Args:
            value: Feed value to sign
            timestamp: Optional timestamp (uses current time if None)

        Returns:
            Tuple of (timestamp, signature bytes)
        """
        if timestamp is None:
            timestamp = int(time.time() * 1000)  # Convert to milliseconds

        # Create message bytes
        message = encode_oracle_feed(value, timestamp)

        # Use pycardano's signing key for signatures
        signature = self.signing_key.sign(message)

        return timestamp, signature

    def verify_feed_signature(
        self, value: int, timestamp: int, signature: bytes
    ) -> bool:
        """Verify a feed signature.

        Args:
            value: Feed value
            timestamp: Timestamp in milliseconds
            signature: Signature to verify

        Returns:
            bool: True if signature is valid
        """
        try:
            message = encode_oracle_feed(value, timestamp)
            # Use nacl's VerifyKey for verification
            self._nacl_verify_key.verify(message, signature)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    @property
    def verify_key_bytes(self) -> bytes:
        """Get raw verification key bytes for signature validation."""
        return self.verification_key.payload

    def to_dict(self) -> dict:
        """Convert node to dictionary representation."""
        return {
            "feed_vkh": self.hex_feed_vkh,
            "payment_vkh": self.hex_payment_vkh,
            "verification_key": self.verify_key_bytes.hex(),
        }


@dataclass
class SimulationSettings:
    """Simulation-specific configuration."""

    node_keys_dir: Path
    base_feed: int
    variance: float = 0.01
    wait_time: int = 60
    required_signatures: int | None = None

    def __post_init__(self) -> None:
        """Validate and set defaults."""
        if not self.node_keys_dir.is_dir():
            raise ValueError(f"Node keys directory not found: {self.node_keys_dir}")

        # Load required signatures from file if not specified
        if self.required_signatures is None:
            try:
                self.required_signatures = int(
                    (self.node_keys_dir / "required_signatures").read_text()
                )
            except (FileNotFoundError, ValueError) as e:
                raise ValueError("Could not load required_signatures") from e

    @property
    def node_count(self) -> int:
        """Get number of nodes from directory structure."""
        return len(list(self.node_keys_dir.glob("node_*")))

    def get_node_dirs(self) -> list[Path]:
        """Get sorted list of node directories."""
        return sorted(self.node_keys_dir.glob("node_*"))


@dataclass
class SimulationResult:
    """Results of oracle simulation."""

    nodes: list[SimulatedNode]
    feeds: dict[int, dict]  # node_id -> {feed, signature, verification_key}
    odv_tx: str
    rewards: RewardsResult


class SimulationConfig(TxConfig):
    """Extends base transaction config with simulation settings."""

    def __init__(
        self,
        network: NetworkConfig,
        script_address: str,
        policy_id: str,
        wallet: WalletConfig,
        simulation: SimulationSettings,
    ) -> None:
        """Initialize simulation config with base config and simulation settings."""
        super().__init__(network, script_address, policy_id, wallet)
        self.simulation = simulation

    @classmethod
    def from_yaml(cls, path: Path) -> "SimulationConfig":
        """Load simulation config from YAML file."""
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        # Load base config first
        with path.open("r") as f:
            data = yaml.safe_load(f)

        # Load simulation settings
        sim_data = data.get("simulation", {})
        if not sim_data:
            raise ValueError("Missing simulation settings in config file")

        sim_settings = SimulationSettings(
            node_keys_dir=Path(sim_data["node_keys_dir"]),
            base_feed=sim_data["base_feed"],
            variance=sim_data.get("variance", 0.01),
            wait_time=sim_data.get("wait_time", 60),
            required_signatures=sim_data.get("required_signatures"),
        )

        return cls(
            network=NetworkConfig.from_dict(data.get("network", {})),
            script_address=data["script_address"],
            policy_id=data["policy_id"],
            wallet=WalletConfig.from_dict(data["wallet"]),
            simulation=sim_settings,
        )

    def validate(self) -> None:
        """Validate complete configuration."""
        # Validate base config
        self.network.validate()

        # Validate simulation settings
        if self.simulation.node_count < self.simulation.required_signatures:
            raise ValueError(
                f"Number of nodes ({self.simulation.node_count}) must be >= "
                f"required signatures ({self.simulation.required_signatures})"
            )

        if not 0 < self.simulation.variance < 1:
            raise ValueError("Variance must be between 0 and 1")

        if self.simulation.wait_time < 0:
            raise ValueError("Wait time cannot be negative")
