"""Oracle datums for the oracle core contract"""

from dataclasses import dataclass
from typing import Any, Dict, List, Union

from pycardano import PlutusData, VerificationKeyHash

PolicyId = bytes
AssetName = bytes
PosixTime = int
PosixTimeDiff = int
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
        """Handle deserialization of empty maps properly"""
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

    @classmethod
    def from_string_list(
        cls,
        parties: List[str],
    ) -> "Nodes":
        """
        Converts a list of strings into a Nodes instance. If a single list is provided,
        each value is used as both the feed VKH and payment VKH (duplicated).
        The resulting map is sorted by keys to match Aiken's requirements.

        Args:
            parties: List of strings representing verification key hashes.
                    Each string should be a valid VKH.

        Returns:
            Nodes: A new Nodes instance with the sorted node_map.

        Raises:
            ValueError: If parties is not a list or if any VKH conversion fails.

        Example:
            parties = ["vkh1", "vkh2"]
            nodes = Nodes.from_string_list(parties)
            # Results in a map where each vkh maps to itself:
            # {
            #   VKH("vkh1"): VKH("vkh1"),
            #   VKH("vkh2"): VKH("vkh2")
            # }
            # The map is sorted by the string representation of the keys
        """
        if not isinstance(parties, list):
            raise ValueError("parties must be a list")

        # Convert strings to VKHs and create mapping
        node_map = {}
        for idx, party in enumerate(parties):
            try:
                vkh = VerificationKeyHash.from_primitive(party)
                node_map[vkh] = vkh  # Use same VKH as both key and value
            except Exception as err:
                raise ValueError(
                    "Failed to convert party at index idx: %s", idx
                ) from err

        # Sort the map by string representation of keys as required by Aiken
        sorted_map = dict(sorted(node_map.items(), key=lambda x: str(x[0])))

        return cls(node_map=sorted_map)

    def to_primitive(self) -> Dict[Any, Any]:
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
    fee_token: Union[Asset, NoDatum]

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
    node_feeds_sorted_by_feed: Dict[VerificationKeyHash, VerificationKeyHash]
    node_feeds_count: int
    timestamp: PosixTime

    @classmethod
    def from_primitive(
        cls, feeds: Dict[str, str], timestamp: int
    ) -> "AggregateMessage":
        """
        Create from hex-encoded VKHs and feed values.

        Args:
            feeds (Dict[str, str]): A dictionary where each key-value pair is a
                hex-encoded verification key hash for node feeds.
            timestamp (int): The timestamp in POSIX format.

        Returns:
            AggregateMessage: An instance of AggregateMessage.
        """
        # Convert hex-encoded VKHs to VerificationKeyHash
        sorted_feeds = {
            VerificationKeyHash(bytes.fromhex(vkh)): VerificationKeyHash(
                bytes.fromhex(feed)
            )
            for vkh, feed in feeds.items()
        }
        # Ensure feeds are sorted by their keys
        sorted_feeds = dict(
            sorted(sorted_feeds.items(), key=lambda x: x[0].__bytes__())
        )

        return cls(
            node_feeds_sorted_by_feed=sorted_feeds,
            node_feeds_count=len(feeds),
            timestamp=PosixTime(timestamp),
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
