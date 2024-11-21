"""Oracle datums for the oracle core contract"""

from dataclasses import dataclass
from typing import List, Tuple, Union

from pycardano import PlutusData, VerificationKeyHash

PolicyId = bytes
AssetName = bytes
PosixTime = int
PosixTimeDiff = int
OracleFeed = int
NodeFeed = int


@dataclass
class NoDatum(PlutusData):
    """Universal None type for PlutusData"""

    CONSTR_ID = 1


@dataclass
class OutputReference(PlutusData):
    """Represents a reference to a transaction output"""

    CONSTR_ID = 0
    tx_hash: bytes
    index: int


@dataclass
class Nodes(PlutusData):
    """
    Represents a list of node pairs (feed_vkh, payment_vkh).
    Must be sorted by feed_vkh to match Aiken's requirements.
    """

    CONSTR_ID = 0
    pairs: List[Tuple[VerificationKeyHash, VerificationKeyHash]]

    @classmethod
    def from_primitive(cls, pairs: List[Tuple[str, str]]) -> "Nodes":
        """
        Create Nodes from a list of hex-encoded VKH pairs.
        Automatically sorts by feed_vkh.
        """
        vkh_pairs = [
            (
                VerificationKeyHash(bytes.fromhex(feed)),
                VerificationKeyHash(bytes.fromhex(payment)),
            )
            for feed, payment in pairs
        ]
        # Sort by feed_vkh as required by Aiken
        vkh_pairs.sort(key=lambda x: x[0])
        return cls(pairs=vkh_pairs)

    def ensure_sorted(self) -> None:
        """Ensure pairs are sorted by feed_vkh"""
        self.pairs.sort(key=lambda x: x[0])


@dataclass
class RewardPrices(PlutusData):
    """Represents reward prices configuration"""

    CONSTR_ID = 0
    node_fee: int
    platform_fee: int


@dataclass
class Asset(PlutusData):
    """Represents a native token asset"""

    CONSTR_ID = 0
    policy_id: PolicyId
    name: AssetName

    def __post_init__(self) -> None:
        # Add validation for policy_id length (28 bytes for Cardano)
        if len(self.policy_id) != 28:
            raise ValueError("Policy ID must be 28 bytes long")


@dataclass
class FeeConfig(PlutusData):
    """Represents fee configuration"""

    CONSTR_ID = 0
    rate_nft: Union[Asset, NoDatum]
    reward_prices: RewardPrices


@dataclass
class OracleConfiguration(PlutusData):
    """Immutable oracle settings"""

    CONSTR_ID = 0
    platform_auth_nft: PolicyId
    closing_period_length: PosixTimeDiff
    reward_dismissing_period_length: PosixTimeDiff
    fee_token: Asset

    def __post_init__(self) -> None:
        # Add validation for platform_auth_nft length (28 bytes for Cardano)
        if len(self.platform_auth_nft) != 28:
            raise ValueError("Policy ID must be 28 bytes long")


@dataclass
class OracleSettingsDatum(PlutusData):
    """Mutable oracle settings"""

    CONSTR_ID = 0
    nodes: Nodes
    required_node_signatures_count: int
    fee_info: FeeConfig
    aggregation_liveness_period: PosixTimeDiff
    time_absolute_uncertainty: PosixTimeDiff
    iqr_fence_multiplier: int  # Percent
    closing_period_started_at: Union[PosixTime, NoDatum]


@dataclass
class RewardAccountDatum(PlutusData):
    """Reward distribution datum"""

    CONSTR_ID = 0
    nodes_to_rewards: List[int]


@dataclass
class AggregateMessage(PlutusData):
    """Represents an aggregate message from nodes"""

    CONSTR_ID = 0
    node_feeds_sorted_by_feed: List[Tuple[VerificationKeyHash, NodeFeed]]
    node_feeds_count: int
    timestamp: PosixTime

    @classmethod
    def from_primitive(
        cls, feeds: List[Tuple[str, int]], timestamp: int
    ) -> "AggregateMessage":
        """Create from hex-encoded VKHs and feed values"""
        sorted_feeds = [
            (VerificationKeyHash(bytes.fromhex(vkh)), feed)
            for vkh, feed in sorted(feeds)  # Sort by VKH
        ]
        return cls(
            node_feeds_sorted_by_feed=sorted_feeds,
            node_feeds_count=len(feeds),
            timestamp=timestamp,
        )


@dataclass
class AggStateDatum(PlutusData):
    """AggState contains oracle feed data and timing information"""

    CONSTR_ID = 0
    oracle_feed: OracleFeed
    expiry_timestamp: PosixTime
    created_at: PosixTime


@dataclass
class NoRewards(PlutusData):
    """Reward transport with no rewards state"""

    CONSTR_ID = 0


@dataclass
class RewardConsensusPending(PlutusData):
    """Reward transport with pending consensus state"""

    CONSTR_ID = 1
    oracle_feed: OracleFeed
    message: AggregateMessage
    node_reward_price: int


# Main datum variants
@dataclass
class OracleSettingsVariant(PlutusData):
    """Oracle settings variant of OracleDatum"""

    CONSTR_ID = 0
    datum: OracleSettingsDatum


@dataclass
class RewardAccountVariant(PlutusData):
    """Reward account variant of OracleDatum"""

    CONSTR_ID = 1
    datum: RewardAccountDatum


@dataclass
class RewardTransportVariant(PlutusData):
    """Reward transport variant of OracleDatum"""

    CONSTR_ID = 2
    datum: Union[NoRewards, RewardConsensusPending]


@dataclass
class AggStateVariant(PlutusData):
    """Agg state variant of OracleDatum"""

    CONSTR_ID = 3
    datum: Union[AggStateDatum, NoDatum]


@dataclass
class OracleDatum(PlutusData):
    """
    Main oracle datum with four possible variants:
    1. OracleSettingsVariant
    2. RewardAccountVariant
    3. RewardTransportVariant
    4. AggStateVariant
    """

    variant: (
        OracleSettingsVariant
        | RewardAccountVariant
        | RewardTransportVariant
        | AggStateVariant
    )
