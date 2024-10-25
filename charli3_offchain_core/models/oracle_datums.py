"""Oracle datums for the oracle core contract"""

from dataclasses import dataclass

from pycardano import PlutusData, ScriptHash, VerificationKeyHash


@dataclass
class Node(PlutusData):
    """Represents an oracle node with payment and feed verification keys"""

    CONSTR_ID = 0
    payment_vkh: VerificationKeyHash
    feed_vkh: VerificationKeyHash


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
    policy_id: ScriptHash
    name: bytes  # AssetName


@dataclass
class FeeConfig(PlutusData):
    """Represents fee configuration"""

    CONSTR_ID = 0
    rate_nft: Asset | None
    reward_prices: RewardPrices


@dataclass
class OracleConfiguration(PlutusData):
    """Immutable oracle settings"""

    CONSTR_ID = 0
    platform_auth_nft: ScriptHash
    closing_period_length: int  # PosixTimeDiff
    reward_dismissing_period_length: int  # PosixTimeDiff
    fee_token: Asset


@dataclass
class OracleSettingsDatum(PlutusData):
    """Mutable oracle settings"""

    CONSTR_ID = 0
    nodes: list[Node]
    required_node_signatures_count: int
    fee_info: FeeConfig
    aggregation_liveness_period: int  # PosixTimeDiff
    time_absolute_uncertainty: int  # PosixTimeDiff
    iqr_fence_multiplier: int  # Percent
    closing_period_started_at: int | None  # Optional PosixTime


@dataclass
class RewardAccountDatum(PlutusData):
    """Reward distribution datum"""

    CONSTR_ID = 0
    nodes_to_rewards: list[int]  # Maps node ID to reward amount


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
class RewardTransportDatum(PlutusData):
    """Can be either NoRewards or RewardConsensusPending"""

    CONSTR_ID = 0  # For NoRewards


@dataclass
class RewardConsensusPendingDatum(PlutusData):
    """Represents pending reward consensus state"""

    CONSTR_ID = 1  # For RewardConsensusPending
    oracle_feed: int
    message: AggregateMessage


@dataclass
class OracleDatum(PlutusData):
    """Main oracle datum that can be one of four types:
    1. OracleSettings - single source of truth for settings and node list
    2. RewardAccount - single source of truth for reward distribution
    3. RewardTransport - handles ODV aggregation
    4. AggState - contains oracle feed value
    """

    CONSTR_ID = 0  # For OracleSettings
    settings: OracleSettingsDatum | None = None
    reward_account: RewardAccountDatum | None = None
    reward_transport: RewardTransportDatum | RewardConsensusPendingDatum | None = None
    agg_state: AggStateDatum | None = None
