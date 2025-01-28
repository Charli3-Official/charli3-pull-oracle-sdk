from dataclasses import dataclass
from typing import Union

from pycardano import Address, DatumHash, PlutusData, VerificationKeyHash

from charli3_offchain_core.models.extension_types import PosixTime
from charli3_offchain_core.models.oracle_datums import PolicyId

PaymentVkh = bytes


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


@dataclass
class ReceiverDatum(PlutusData):
    """The receiver address."""

    CONSTR_ID = 0
    datum_hash: DatumHash | None = None


@dataclass
class PlutusPartAddress(PlutusData):
    """Encode a plutus address part (i.e. payment, stake, etc)."""

    CONSTR_ID = 0
    address: bytes


@dataclass
class PlutusScriptPartAddress(PlutusPartAddress):
    """Encode a plutus address part (i.e. payment, stake, etc)."""

    CONSTR_ID = 1


@dataclass
class PlutusNone(PlutusData):
    """Placeholder for a receiver datum."""

    CONSTR_ID = 1


@dataclass
class _PlutusConstrWrapper(PlutusData):
    """Hidden wrapper to match Minswap stake address constructs."""

    CONSTR_ID = 0
    wrapped: Union["_PlutusConstrWrapper", PlutusPartAddress, PlutusScriptPartAddress]


@dataclass
class PlutusFullAddress(PlutusData):
    """A full address, including payment and staking keys."""

    # Do not remove noqa
    CONSTR_ID = 0
    payment: Union[PlutusPartAddress, PlutusScriptPartAddress]  # noqa: UP007
    stake: Union[_PlutusConstrWrapper, PlutusNone, None] = None  # noqa: UP007

    @classmethod
    def from_address(cls, address: Address) -> "PlutusFullAddress":
        """Parse an Address object to a PlutusFullAddress."""
        error_msg = "Only addresses with staking and payment parts are accepted."
        if None in [address.staking_part, address.payment_part]:
            raise ValueError(error_msg)
        stake: _PlutusConstrWrapper | PlutusNone = PlutusNone()
        if address.staking_part is not None:
            stake = _PlutusConstrWrapper(
                _PlutusConstrWrapper(
                    PlutusPartAddress(bytes.fromhex(str(address.staking_part))),
                ),
            )

        return PlutusFullAddress(
            PlutusPartAddress(bytes.fromhex(str(address.payment_part))),
            stake=stake,
        )

    def to_address(self) -> Address:
        """Convert back to an address."""
        payment_part = VerificationKeyHash(self.payment.address[:28])
        if isinstance(self.stake, PlutusNone) or self.stake is None:
            stake_part = None
        else:
            stake_part = VerificationKeyHash(self.stake.wrapped.wrapped.address[:28])
        return Address(payment_part=payment_part, staking_part=stake_part)


@dataclass
class PlutusScriptAddress(PlutusFullAddress):
    """A full address, including payment and staking keys."""

    payment: PlutusScriptPartAddress


@dataclass
class RewardEscrowDatum(PlutusData):
    """Information on escrow script user and owner"""

    CONSTR_ID = 0
    reward_issuer_nft: PolicyId  # policy ID - an authorization NFT minting script hash
    reward_issuer_address: PlutusFullAddress  # locked ada to this address
    reward_receiver: PaymentVkh  # user vkh that signs tx claiming the rewards
    escrow_expiration_timestamp: PosixTime  # reward issuer can return unclaimed rewards after this moment in time
