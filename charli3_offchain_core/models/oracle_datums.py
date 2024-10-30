"""Oracle datums for the oracle core contract"""

from dataclasses import dataclass, field
from typing import List

from pycardano import PlutusData


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
class Node(PlutusData):
    """Represents an oracle node with payment and feed verification keys"""

    CONSTR_ID = 0
    feed_vkh: bytes
    payment_vkh: bytes


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
    policy_id: bytes  # PolicyID
    name: bytes  # AssetName


@dataclass
class FeeConfig(PlutusData):
    """Represents fee configuration"""

    CONSTR_ID = 0
    reward_prices: RewardPrices
    rate_nft: Asset | None = field(default=None, metadata={"optional": True})


@dataclass
class OracleConfiguration(PlutusData):
    """Immutable oracle settings"""

    CONSTR_ID = 0
    platform_auth_nft: bytes  # PolicyID
    closing_period_length: int  # PosixTimeDiff
    reward_dismissing_period_length: int  # PosixTimeDiff
    fee_token: Asset


@dataclass
class OracleSettingsDatum(PlutusData):
    """Mutable oracle settings"""

    CONSTR_ID = 0
    nodes: List[Node]
    required_node_signatures_count: int
    fee_info: FeeConfig
    aggregation_liveness_period: int  # PosixTimeDiff
    time_absolute_uncertainty: int  # PosixTimeDiff
    iqr_fence_multiplier: int  # Percent
    closing_period_started_at: int | None = field(
        default=None, metadata={"optional": True}
    )


@dataclass
class RewardAccountDatum(PlutusData):
    """Reward distribution datum"""

    CONSTR_ID = 0
    nodes_to_rewards: List[int]  # Maps node ID to reward amount


@dataclass
class AggregateMessage(PlutusData):
    """Represents an aggregate message from nodes"""

    CONSTR_ID = 0
    node_feeds_sorted_by_feed: dict[int, int]  # NodeId -> NodeFeed
    node_feeds_count: int
    timestamp: int  # PosixTime


@dataclass
class AggStateDatum(PlutusData):
    """AggState contains oracle feed data and timing information"""

    CONSTR_ID = 0
    oracle_feed: int  # OracleFeed
    expiry_timestamp: int  # PosixTime
    created_at: int  # PosixTime


@dataclass
class NoRewards(PlutusData):
    """Reward transport with no rewards state"""

    CONSTR_ID = 0


@dataclass
class RewardConsensusPending(PlutusData):
    """Reward transport with pending consensus state"""

    CONSTR_ID = 1
    oracle_feed: int
    message: AggregateMessage


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
    datum: RewardConsensusPending | None = field(
        default=None, metadata={"optional": True}
    )


@dataclass
class AggStateVariant(PlutusData):
    """Agg state variant of OracleDatum"""

    CONSTR_ID = 3
    datum: AggStateDatum | None = field(default=None, metadata={"optional": True})


@dataclass
class OracleDatum(PlutusData):
    """
    Main oracle datum with four possible variants:
    1. OracleSettingsVariant
    2. RewardAccountVariant
    3. RewardTransportVariant
    4. AggStateVariant
    """

    CONSTR_ID = 0
    variant: (
        OracleSettingsVariant
        | RewardAccountVariant
        | RewardTransportVariant
        | AggStateVariant
    )
