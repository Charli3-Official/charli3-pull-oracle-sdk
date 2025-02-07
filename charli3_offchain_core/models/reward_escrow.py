from dataclasses import dataclass

from pycardano import Address, PlutusData, ScriptHash, VerificationKeyHash

from charli3_offchain_core.models.base import PosixTime


@dataclass
class RewardEscrowDatum(PlutusData):
    """Information on escrow script user and owner"""

    CONSTR_ID = 0
    reward_issuer_nft: (
        ScriptHash  # policy ID - an authorization NFT minting script hash
    )
    reward_issuer_address: (
        Address  # issuer will receive locked utxo ada fee to this address
    )
    reward_receiver: VerificationKeyHash  # user vkh that signs tx claiming the rewards
    escrow_expiration_timestamp: PosixTime  # reward issuer can return unclaimed rewards after this moment in time


@dataclass
class RewardEscrowRedeemer(PlutusData):
    """Types of actions for Reward Escrow smart contract"""

    CONSTR_ID = 0  # Base constructor ID


class ReceiveReward(RewardEscrowRedeemer):
    """User - in this context oracle node, redeems escrowed rewards"""

    CONSTR_ID = 0


class ReturnToIssuer(RewardEscrowRedeemer):
    """Reward issuer - in this context oracle platform, returns unclaimed rewards"""

    CONSTR_ID = 1
