"""Node configuration parameters."""

from dataclasses import dataclass

from pycardano import VerificationKeyHash


@dataclass
class NodeConfig:
    """Configuration for oracle node."""

    feed_vkh: VerificationKeyHash
    payment_vkh: VerificationKeyHash

    @classmethod
    def from_dict(cls, data: dict) -> "NodeConfig":
        """Create node config from dictionary."""
        return cls(
            feed_vkh=VerificationKeyHash(bytes.fromhex(data["feed_vkh"])),
            payment_vkh=VerificationKeyHash(bytes.fromhex(data["payment_vkh"])),
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
