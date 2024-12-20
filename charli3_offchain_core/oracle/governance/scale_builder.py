"""Oracle scaling transaction builder for managing ODV capacity."""

import logging
from dataclasses import dataclass

from pycardano import (
    Address,
    AssetName,
    ExtendedSigningKey,
    MultiAsset,
    PaymentSigningKey,
    Redeemer,
    ScriptHash,
    Transaction,
    TransactionOutput,
    UTxO,
    Value,
    VerificationKeyHash,
)

from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.models.oracle_datums import (
    AggStateVariant,
    NoDatum,
    NoRewards,
    RewardTransportVariant,
)
from charli3_offchain_core.models.oracle_redeemers import (
    Scale,
    ScaleDown,
)
from charli3_offchain_core.oracle.exceptions import (
    ScalingError,
    StateValidationError,
)
from charli3_offchain_core.oracle.utils.common import get_reference_script_utxo
from charli3_offchain_core.oracle.utils.state_checks import (
    filter_empty_transports,
    filter_valid_agg_states,
    get_oracle_settings_by_policy_id,
)

logger = logging.getLogger(__name__)


@dataclass
class ScaleUpResult:
    """Result of scale up transaction."""

    transaction: Transaction
    new_transport_outputs: list[TransactionOutput]
    new_agg_state_outputs: list[TransactionOutput]


@dataclass
class ScaleDownResult:
    """Result of scale down transaction."""

    transaction: Transaction
    removed_transport_utxos: list[UTxO]
    removed_agg_state_utxos: list[UTxO]


class OracleScaleBuilder:
    """Builder for scaling ODV capacity up or down."""

    MIN_UTXO_VALUE = 2_000_000

    def __init__(
        self,
        tx_manager: TransactionManager,
        script_address: Address,
        policy_id: ScriptHash,
        fee_token_hash: ScriptHash,
        fee_token_name: AssetName,
    ) -> None:
        """Initialize transaction builder.

        Args:
            tx_manager: Transaction manager
            script_address: Script address
            policy_id: Policy ID for tokens
        """
        self.tx_manager = tx_manager
        self.script_address = script_address
        self.policy_id = policy_id
        self.fee_token_hash = fee_token_hash
        self.fee_token_name = fee_token_name
        self.network_config = self.tx_manager.chain_query.config.network_config
        self._standard_min_ada = self.MIN_UTXO_VALUE

    def _get_standard_min_ada(self, utxos: list[UTxO], policy_hash: ScriptHash) -> int:
        """Get standard minimum ADA amount from core settings UTxO."""
        try:
            # Get core settings UTxO and use its amount
            _, settings_utxo = get_oracle_settings_by_policy_id(utxos, policy_hash)
            return settings_utxo.output.amount.coin

        except Exception as e:  # pylint: disable=broad-except
            logger.warning("Failed to get min ADA from core settings: %s", e)
            return self.MIN_UTXO_VALUE

    async def build_scale_up_tx(
        self,
        platform_utxo: UTxO,
        utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        scale_amount: int,
        required_signers: list[VerificationKeyHash] | None = None,
        transport_name: str = "RewardTransport",
        aggstate_name: str = "AggState",
    ) -> ScaleUpResult:
        """Build transaction to increase ODV capacity by creating new UTxO pairs."""
        try:
            script_utxo = get_reference_script_utxo(utxos)
            if not script_utxo:
                raise ValueError("Reference script UTxO not found")

            # Get standard min ADA from core settings
            self._standard_min_ada = await self._get_standard_min_ada(
                utxos, self.policy_id
            )
            logger.info(
                "Using standard min ADA amount: %s lovelace", self._standard_min_ada
            )

            # Create new empty outputs
            new_transport_outputs = [
                TransactionOutput(
                    address=self.script_address,
                    amount=Value(
                        coin=self._standard_min_ada,
                        multi_asset=MultiAsset.from_primitive(
                            {self.policy_id: {transport_name.encode(): 1}}
                        ),
                    ),
                    datum=RewardTransportVariant(datum=NoRewards()),
                )
                for _ in range(scale_amount)
            ]

            new_agg_state_outputs = [
                TransactionOutput(
                    address=self.script_address,
                    amount=Value(
                        coin=self._standard_min_ada,
                        multi_asset=MultiAsset.from_primitive(
                            {self.policy_id: {aggstate_name.encode(): 1}}
                        ),
                    ),
                    datum=AggStateVariant(datum=NoDatum()),
                )
                for _ in range(scale_amount)
            ]

            # Get minting script
            nft_minting_script = self.tx_manager.chain_query.get_plutus_script(
                self.policy_id
            )
            mint_map = {
                transport_name.encode(): scale_amount,
                aggstate_name.encode(): scale_amount,
            }
            mint = MultiAsset.from_primitive({self.policy_id: mint_map})

            # Build transaction using TransactionManager
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[],  # No script inputs for minting
                script_outputs=[*new_transport_outputs, *new_agg_state_outputs],
                reference_inputs={platform_utxo},
                mint=mint,
                mint_redeemer=Redeemer(Scale()),
                mint_script=nft_minting_script,
                required_signers=required_signers,
                change_address=change_address,
                signing_key=signing_key,
            )

            return ScaleUpResult(
                transaction=tx,
                new_transport_outputs=new_transport_outputs,
                new_agg_state_outputs=new_agg_state_outputs,
            )

        except Exception as e:
            raise ScalingError(f"Failed to build scale up transaction: {e}") from e

    async def build_scale_down_tx(
        self,
        platform_utxo: UTxO,
        utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        scale_amount: int,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> ScaleDownResult:
        """Build transaction to decrease ODV capacity by removing UTxO pairs."""
        try:
            script_utxo = get_reference_script_utxo(utxos)
            if not script_utxo:
                raise ValueError("Reference script UTxO not found")

            # Calculate validity window
            settings_datum, _ = get_oracle_settings_by_policy_id(utxos, self.policy_id)
            validity_start = (
                self.tx_manager.chain_query.get_current_posix_chain_time_ms()
            )
            validity_end = validity_start + settings_datum.time_absolute_uncertainty
            current_time = (validity_end + validity_start) // 2

            # Find UTxOs to remove
            empty_transports = filter_empty_transports(utxos)[:scale_amount]
            expired_and_empty_agg_states = filter_valid_agg_states(utxos, current_time)[
                :scale_amount
            ]

            if (
                len(empty_transports) < scale_amount
                or len(expired_and_empty_agg_states) < scale_amount
            ):
                raise StateValidationError(
                    f"Insufficient empty UTxOs for scaling down. "
                    f"Found {len(empty_transports)} empty transports and "
                    f"{len(expired_and_empty_agg_states)} expired agg states"
                )

            # Get minting script for burning
            nft_minting_script = self.tx_manager.chain_query.get_plutus_script(
                self.policy_id
            )

            # Add burning
            mint_map = {
                b"RewardTransport": -scale_amount,
                b"AggState": -scale_amount,
            }
            mint = MultiAsset.from_primitive({self.policy_id: mint_map})

            # Prepare script inputs
            script_inputs = [
                (utxo, Redeemer(ScaleDown()), script_utxo)
                for utxo in empty_transports + expired_and_empty_agg_states
            ]

            # Build transaction using TransactionManager
            tx = await self.tx_manager.build_script_tx(
                script_inputs=script_inputs,
                script_outputs=[platform_utxo.output],
                reference_inputs={platform_utxo},
                mint=mint,
                mint_redeemer=Redeemer(ScaleDown()),
                mint_script=nft_minting_script,
                required_signers=required_signers,
                change_address=change_address,
                signing_key=signing_key,
                validity_start=validity_start,
                validity_end=validity_end,
            )

            return ScaleDownResult(
                transaction=tx,
                removed_transport_utxos=empty_transports,
                removed_agg_state_utxos=expired_and_empty_agg_states,
            )

        except Exception as e:
            raise ScalingError(f"Failed to build scale down transaction: {e}") from e
