"""Oracle Redeemers for Oracle smart contract and Oracle NFTs"""

from dataclasses import dataclass

from pycardano import IndefiniteList, PlutusData, VerificationKeyHash


### Oracle NFTs
@dataclass
class MintingRedeemer(PlutusData):
    """Types of actions for Oracle NFTs (protocol tokens)"""

    CONSTR_ID = 0  # For Mint


class Mint(MintingRedeemer):
    """One time mint for CoreSettings and RewardAccount"""

    CONSTR_ID = 0


class Scale(MintingRedeemer):
    """Scale RewardTransport and AggState UTxOs"""

    CONSTR_ID = 1


class Burn(MintingRedeemer):
    """Oracle remove: all tokens are burned"""

    CONSTR_ID = 2


## Reward Redeemer
@dataclass
class RewardRedeemer(PlutusData):
    """RewardRedeem"""

    CONSTR_ID = 0


class NodeCollect(RewardRedeemer):
    """Node Collect"""

    CONSTR_ID = 0


class PlatformCollect(RewardRedeemer):
    """Platform Collect"""

    CONSTR_ID = 1


### Oracle Manager
@dataclass
class OracleRedeemer(PlutusData):
    """Types of actions for Oracle smart contract"""

    CONSTR_ID = 0  # Base constructor ID


@dataclass
class OdvAggregate(OracleRedeemer):
    """User sends on demand validation request with oracle nodes message."""

    CONSTR_ID = 0
    message: dict  # Map of VKH -> feed_value

    @classmethod
    def create_sorted(
        cls, node_feeds: dict[VerificationKeyHash, int]
    ) -> "OdvAggregate":
        """Create OdvAggregate with message in the provided order.

        Args:
            node_feeds: Dictionary mapping VerificationKeyHash to node feed values
                       MUST be pre-sorted by (feed_value, VKH) as required by validator

        Returns:
            OdvAggregate with message as dict (serializes as CBOR Map)

        """
        return cls(message=node_feeds)


class OdvAggregateMsg(OracleRedeemer):
    """Marks the AggState UTxO as spent during aggregation"""

    CONSTR_ID = 1


class RedeemRewards(OracleRedeemer):
    """Redeem rewards"""

    CONSTR_ID = 2

    collector: RewardRedeemer
    corresponding_out_ix: int


class ManageSettings(OracleRedeemer):
    """Calculate reward consensus and transfer fees to reward UTxO"""

    CONSTR_ID = 3


class ScaleDown(OracleRedeemer):
    """Platform burns RewardTransport and AggState NFTs"""

    CONSTR_ID = 4


class DismissRewards(OracleRedeemer):
    """Platform turns RewardTransport UTxOs with pending rewards into NoRewards"""

    CONSTR_ID = 5


## Settings Redeemer
@dataclass
class SettingsRedeemer(PlutusData):
    """Oracle Setttings Redeemer"""

    CONSTR_ID = 0


class UpdateSettings(SettingsRedeemer):
    """Oracle platform changes consensus, timing or fee settings"""

    CONSTR_ID = 0


class AddNodes(SettingsRedeemer):
    """Oracle platform adds new nodes"""

    CONSTR_ID = 1


class DelNodes(SettingsRedeemer):
    """Oracle platform deletes nodes"""

    CONSTR_ID = 2


class PauseOracle(SettingsRedeemer):
    """Platform starts pause period"""

    CONSTR_ID = 3


class ResumeOracle(SettingsRedeemer):
    """Cancel oracle pause for temporary suspension"""

    CONSTR_ID = 4


class RemoveOracle(SettingsRedeemer):
    """Remove oracle and destroy all UTxOs and NFTs"""

    CONSTR_ID = 5


@dataclass
class AggregateMessage:
    """Off-chain representation of aggregate message.

    This is NOT serialized to chain. When building transactions, use
    OdvAggregate.create_sorted() to create the properly formatted redeemer.

    IMPORTANT: On-chain, AggregateMessage is just Pairs<FeedVkh, NodeFeed>.
    Count and timestamp are NOT part of the on-chain structure.
    """

    node_feeds_sorted_by_feed: dict[VerificationKeyHash, int]

    def to_redeemer(self) -> OdvAggregate:
        """Convert to properly formatted redeemer."""
        return OdvAggregate.create_sorted(self.node_feeds_sorted_by_feed)

    @property
    def node_feeds_count(self) -> int:
        """Calculate count from the map (not stored)."""
        return len(self.node_feeds_sorted_by_feed)
