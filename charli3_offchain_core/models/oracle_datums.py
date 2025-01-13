"""Oracle datums for the oracle core contract"""

from dataclasses import dataclass
from typing import Any, Dict, List, Union

from pycardano import PlutusData, VerificationKeyHash

from charli3_offchain_core.models.extension_types import PosixTime, PosixTimeDiff

PolicyId = bytes
AssetName = bytes
ScriptHash = bytes
OracleFeed = int
NodeFeed = int
FeedVkh = VerificationKeyHash
PaymentVkh = VerificationKeyHash

MINIMUM_ADA_AMOUNT_HELD_AT_MAXIMUM_EXPECTED_REWARD_ACCOUNT_UTXO_SIZE = 5_500_000


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
    Represents a map of feed VKHs to payment VKHs.
    Keys must be sorted to match Aiken's requirements.
    """

    CONSTR_ID = 0
    node_map: Dict[FeedVkh, PaymentVkh]

    @classmethod
    def from_primitive(cls, data: Any) -> "Nodes":
        """Create Nodes from primitive data."""
        while hasattr(data, "value"):
            data = data.value

        if not data:
            return cls(node_map={})

        return cls(
            node_map={
                VerificationKeyHash.from_primitive(
                    k
                ): VerificationKeyHash.from_primitive(v)
                for k, v in data.items()
            }
        )

    def to_primitive(self) -> Dict[str, Any]:
        """Convert to primitive map representation."""
        return {
            k.to_primitive(): v.to_primitive()
            for k, v in sorted(self.node_map.items(), key=lambda x: str(x[0]))
        }

    @classmethod
    def empty(cls) -> "Nodes":
        """
        Creates an empty Nodes instance with an empty node_map.
        Returns:
            Nodes: A new Nodes instance with an empty map.
        """
        return cls(node_map={})

    @property
    def length(self) -> int:
        return len(self.node_map)


@dataclass
class RewardPrices(PlutusData):
    """Represents reward prices configuration"""

    CONSTR_ID = 0
    node_fee: int
    platform_fee: int

    def __post_init__(self) -> None:
        if self.node_fee < 0 or self.platform_fee < 0:
            raise ValueError("Must not have negative reward prices")


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
class SomeAsset(PlutusData):
    """Represents a native token asset"""

    CONSTR_ID = 0
    asset: Asset


FeeRateNFT = Union[SomeAsset, NoDatum]


@dataclass
class FeeConfig(PlutusData):
    """Represents fee configuration"""

    CONSTR_ID = 0
    rate_nft: FeeRateNFT
    reward_prices: RewardPrices


@dataclass
class SomePosixTime(PlutusData):
    """Represents a Posix time in a wrapper"""

    CONSTR_ID = 0
    value: int


@dataclass
class OracleConfiguration(PlutusData):
    """Immutable oracle settings"""

    CONSTR_ID = 0
    platform_auth_nft: PolicyId
    pause_period_length: PosixTimeDiff
    reward_dismissing_period_length: PosixTimeDiff
    fee_token: Union[SomeAsset, NoDatum]
    reward_escrow_script_hash: ScriptHash

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
    utxo_size_safety_buffer: int  # Lovelace
    pause_period_started_at: Union[SomePosixTime, NoDatum]

    def __post_init__(self) -> None:
        if (
            len(self.nodes.node_map) < self.required_node_signatures_count
            or self.required_node_signatures_count <= 0
        ):
            raise ValueError("Oracle Settings Validator: Must not break multisig")

        if self.aggregation_liveness_period <= self.time_absolute_uncertainty:
            raise ValueError("Oracle Settings Validator: Must measure time precisely")

        if self.time_absolute_uncertainty <= 0:
            raise ValueError(
                "Oracle Settings Validator: Must have positive time interval lengths"
            )

        if self.iqr_fence_multiplier <= 100:
            raise ValueError("Oracle Settings Validator: Must be fair about outliers")

    def validate_based_on_config(self, oracle_conf: OracleConfiguration) -> None:
        """Validate contents and throw ValueError if this instance will not satisfy on-chain checks"""
        if oracle_conf.fee_token == NoDatum() and self.utxo_size_safety_buffer <= 0:
            raise ValueError(
                "Oracle Settings Validator: Must have positive utxo_size_safety_buffer"
            )
        if oracle_conf.fee_token != NoDatum() and self.utxo_size_safety_buffer != 0:
            raise ValueError(
                "Oracle Settings Validator: Must have zero utxo_size_safety_buffer"
            )

        if (
            oracle_conf.pause_period_length <= self.time_absolute_uncertainty
            or oracle_conf.reward_dismissing_period_length
            <= self.time_absolute_uncertainty
        ):
            raise ValueError("Oracle Settings Validator: Must measure time precisely")

        return super().validate()


@dataclass
class RewardAccountDatum(PlutusData):
    """Reward distribution datum"""

    CONSTR_ID = 0
    nodes_to_rewards: List[int]


@dataclass
class AggregateMessage(PlutusData):
    """Represents an aggregate message from nodes"""

    CONSTR_ID = 0
    node_feeds_sorted_by_feed: Dict[VerificationKeyHash, NodeFeed]
    node_feeds_count: int
    timestamp: PosixTime


@dataclass
class AggStateDatum(PlutusData):
    """AggState contains oracle feed data and timing information"""

    CONSTR_ID = 0
    oracle_feed: OracleFeed
    expiry_timestamp: PosixTime
    created_at: PosixTime


@dataclass
class SomeAggStateDatum(PlutusData):
    """AggState contains oracle feed data"""

    CONSTR_ID = 0
    aggstate: AggStateDatum


@dataclass
class NoRewards(PlutusData):
    """Reward transport with no rewards state"""

    CONSTR_ID = 0


@dataclass
class Aggregation(PlutusData):
    """Represents information on aggregation specific details"""

    CONSTR_ID = 0
    oracle_feed: OracleFeed
    message: AggregateMessage
    node_reward_price: int
    rewards_amount_paid: int


@dataclass
class RewardConsensusPending(PlutusData):
    """Reward transport with pending consensus state"""

    CONSTR_ID = 1
    aggregation: Aggregation


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
    datum: Union[SomeAggStateDatum, NoDatum]


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
