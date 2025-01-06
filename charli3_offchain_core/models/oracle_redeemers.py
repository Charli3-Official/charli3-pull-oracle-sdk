"""Oracle Redeemers for Oracle smart contract and Oracle NFTs"""

from dataclasses import dataclass

from pycardano import PlutusData


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


@dataclass
class OracleRedeemer(PlutusData):
    """Types of actions for Oracle smart contract"""

    CONSTR_ID = 0  # Base constructor ID


class OdvAggregate(OracleRedeemer):
    """User sends on demand validation request with oracle nodes message"""

    CONSTR_ID = 0


class CalculateRewards(OracleRedeemer):
    """Calculate reward consensus and transfer fees to reward UTxO"""

    CONSTR_ID = 1


class NodeCollect(OracleRedeemer):
    """Oracle node collects rewards"""

    CONSTR_ID = 2


class PlatformCollect(OracleRedeemer):
    """Oracle platform collects rewards"""

    CONSTR_ID = 3


class UpdateSettings(OracleRedeemer):
    """Oracle platform changes consensus, timing or fee settings"""

    CONSTR_ID = 4


class AddNodes(OracleRedeemer):
    """Oracle platform adds new nodes"""

    CONSTR_ID = 5


class DelNodes(OracleRedeemer):
    """Oracle platform deletes nodes"""

    CONSTR_ID = 6


class ScaleDown(OracleRedeemer):
    """Platform burns RewardTransport and AggState NFTs"""

    CONSTR_ID = 7


class DismissRewards(OracleRedeemer):
    """Platform turns RewardTransport UTxOs with pending rewards into NoRewards"""

    CONSTR_ID = 8


class PauseOracle(OracleRedeemer):
    """Platform starts pause period"""

    CONSTR_ID = 9


class ResumeOracle(OracleRedeemer):
    """Cancel oracle pause for temporary suspension"""

    CONSTR_ID = 10


class RemoveOracle(OracleRedeemer):
    """Remove oracle and destroy all UTxOs and NFTs"""

    CONSTR_ID = 11
