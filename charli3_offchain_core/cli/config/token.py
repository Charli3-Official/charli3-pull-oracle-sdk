from dataclasses import dataclass


@dataclass
class TokenConfig:
    """Token configuration."""

    platform_auth_policy: str
    fee_token_policy: str
    fee_token_name: str
    oracle_policy: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "TokenConfig":
        """Create token config from dictionary."""
        return cls(
            platform_auth_policy=data["platform_auth_policy"],
            fee_token_policy=data["fee_token_policy"],
            fee_token_name=data["fee_token_name"],
            oracle_policy=data.get("oracle_policy", None),
        )
