from dataclasses import dataclass


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
