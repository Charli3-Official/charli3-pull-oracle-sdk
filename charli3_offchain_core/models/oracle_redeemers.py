"""Oracle Redeemers for Oracle smart contract and Oracle NFTs"""

from dataclasses import dataclass

from pycardano import PlutusData, VerificationKeyHash

from charli3_offchain_core.models.base import (
    NodeFeed,
)


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
class AggregateMessage(PlutusData):
    """Represents an aggregate message from nodes"""

    CONSTR_ID = 0
    node_feeds_sorted_by_feed: dict[VerificationKeyHash, NodeFeed]


class OdvAggregate(OracleRedeemer):
    """User sends on demand validation request with oracle nodes message"""

    CONSTR_ID = 0
    message: AggregateMessage


class OdvAggregateMsg(OracleRedeemer):
    """Calculate reward consensus and transfer fees to reward UTxO"""

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
