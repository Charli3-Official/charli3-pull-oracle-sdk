"""Oracle deployment configuration models."""

from dataclasses import dataclass

from pycardano import Network

MinimumRewardTransportCount = 4


@dataclass
class OracleTokenNames:
    """Token names for oracle NFTs"""

    core_settings: str
    reward_account: str
    reward_transport: str
    aggstate: str

    @classmethod
    def from_network(cls, network: Network) -> "OracleTokenNames":
        """Create token names configuration based on network"""
        # For now use same token names for testnet and mainnet
        # due to validator is not able to handle testnet token names
        if network in (Network.TESTNET, Network.MAINNET):
            return cls(
                core_settings="C3CS",
                reward_account="C3RA",
                reward_transport="C3RT",
                aggstate="C3AS",
            )
        # TESTNET
        return cls(
            core_settings="CoreSettings",
            reward_account="RewardAccount",
            reward_transport="RewardTransport",
            aggstate="AggregationState",
        )


@dataclass
class OracleDeploymentConfig:
    """Configuration for oracle deployment"""

    network: Network
    reward_transport_count: int
    disallow_less_than_four_nodes: bool | None = None
    token_names: OracleTokenNames | None = None

    def __post_init__(self) -> None:
        """Set default values based on network"""
        if self.token_names is None:
            self.token_names = OracleTokenNames.from_network(self.network)

        if self.disallow_less_than_four_nodes is None:
            self.disallow_less_than_four_nodes = self.network == Network.MAINNET

        if self.reward_transport_count <= 0:
            raise ValueError("reward_transport_count must be greater than 0")

        if (
            self.disallow_less_than_four_nodes
            and self.reward_transport_count < MinimumRewardTransportCount
        ):
            raise ValueError("Mainnet requires at least 4 reward transport UTxOs")


@dataclass
class OracleScriptConfig:
    """Configuration for oracle reference scripts"""

    create_manager_reference: bool = True
    create_nft_reference: bool = False
    reference_ada_amount: int = 55_000_000  # Default 55 ADA for reference scripts
