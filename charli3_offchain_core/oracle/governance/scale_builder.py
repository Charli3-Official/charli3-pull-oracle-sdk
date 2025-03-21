"""Oracle scaling transaction builder for managing ODV capacity."""

import logging
from dataclasses import dataclass

from pycardano import (
    Address,
    ExtendedSigningKey,
    MultiAsset,
    NativeScript,
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
    AggState,
    PriceData,
)
from charli3_offchain_core.models.oracle_redeemers import (
    Scale,
    ScaleDown,
)
from charli3_offchain_core.oracle.exceptions import (
    ScalingError,
    StateValidationError,
)
from charli3_offchain_core.oracle.utils.asset_checks import (
    filter_utxos_by_token_name,
)
from charli3_offchain_core.oracle.utils.common import get_reference_script_utxo
from charli3_offchain_core.oracle.utils.state_checks import (
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
        self.network_config = self.tx_manager.chain_query.config.network_config
        self._standard_min_ada = self.MIN_UTXO_VALUE

    async def build_scale_up_tx(
        self,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        scale_amount: int,
        required_signers: list[VerificationKeyHash] | None = None,
        transport_name: str = "C3RT",
        aggstate_name: str = "C3AS",
    ) -> ScaleUpResult:
        """Build transaction to increase ODV capacity by creating new UTxO pairs."""
        try:
            script_utxo = get_reference_script_utxo(utxos)
            if not script_utxo:
                raise ValueError("Reference script UTxO not found")

            # Get standard min ADA from core settings
            _, settings_utxo = get_oracle_settings_by_policy_id(utxos, self.policy_id)
            self._standard_min_ada = settings_utxo.output.amount.coin
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
                            {self.policy_id.payload: {transport_name.encode(): 1}}
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
                            {self.policy_id.payload: {aggstate_name.encode(): 1}}
                        ),
                    ),
                    datum=AggState(price_data=PriceData.empty()),
                )
                for _ in range(scale_amount)
            ]

            # Get minting script
            nft_minting_script = await self.tx_manager.chain_query.get_plutus_script(
                self.policy_id
            )
            mint_map = {
                transport_name.encode(): scale_amount,
                aggstate_name.encode(): scale_amount,
            }
            mint = MultiAsset.from_primitive({self.policy_id.payload: mint_map})

            # Build transaction using TransactionManager
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (platform_utxo, None, platform_script),
                ],
                script_outputs=[
                    *new_transport_outputs,
                    *new_agg_state_outputs,
                    platform_utxo.output,
                ],
                reference_inputs={settings_utxo},
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
        platform_script: NativeScript,
        utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        scale_amount: int,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> ScaleDownResult:
        """Build transaction to decrease ODV capacity by removing UTxO pairs."""
        try:
            # Log initial parameters
            logger.info(
                "Starting scale down transaction build for %d pairs", scale_amount
            )

            script_utxo = get_reference_script_utxo(utxos)
            if not script_utxo:
                logger.error("Reference script UTxO not found")
                raise ValueError("Reference script UTxO not found")

            # Find and log UTxOs to remove
            transport_utxos = filter_utxos_by_token_name(utxos, self.policy_id, "C3RT")
            aggstate_utxos = filter_utxos_by_token_name(utxos, self.policy_id, "C3AS")

            logger.info(
                "Found UTxOs - Total Transports: %d, Total AggStates: %d",
                len(transport_utxos),
                len(aggstate_utxos),
            )

            # Get empty transports with detailed logging
            empty_transports = filter_empty_transports(transport_utxos)
            logger.info(
                "Empty transport UTxOs found: %d/%d",
                len(empty_transports),
                scale_amount,
            )

            # Get current time for filtering expired agg states
            current_time = self.tx_manager.chain_query.get_current_posix_chain_time_ms()

            # Get expired/empty agg states with detailed logging
            expired_and_empty_agg_states = filter_valid_agg_states(
                aggstate_utxos, current_time
            )
            logger.info(
                "Valid AggState UTxOs found: %d/%d",
                len(expired_and_empty_agg_states),
                scale_amount,
            )

            if (
                len(empty_transports) < scale_amount
                or len(expired_and_empty_agg_states) < scale_amount
            ):
                error_msg = (
                    f"Insufficient empty UTxOs for scaling down. "
                    f"Found {len(empty_transports)} empty transports and "
                    f"{len(expired_and_empty_agg_states)} expired agg states, "
                    f"need {scale_amount} of each"
                )
                logger.error(error_msg)
                raise StateValidationError(error_msg)

            # Select the specific UTxOs to use
            selected_transports = empty_transports[:scale_amount]
            selected_agg_states = expired_and_empty_agg_states[:scale_amount]

            # Log transport UTxO details
            for i, utxo in enumerate(selected_transports):
                logger.info(
                    "Transport UTxO %d: TxId=%s#%d",
                    i + 1,
                    utxo.input.transaction_id,
                    utxo.input.index,
                )

            # Log AggState UTxO details
            for i, utxo in enumerate(selected_agg_states):
                datum = utxo.output.datum
                if isinstance(datum, AggState):
                    if datum.price_data.is_empty:
                        state_type = "Empty"
                        expiry = None
                    else:
                        state_type = "Expired"
                        expiry = datum.price_data.get_expirity_time

                    logger.info(
                        "AggState UTxO %d: TxId=%s#%d, Type=%s, Expiry=%s",
                        i + 1,
                        utxo.input.transaction_id,
                        utxo.input.index,
                        state_type,
                        expiry,
                    )

            # Get minting script for burning
            nft_minting_script = await self.tx_manager.chain_query.get_plutus_script(
                self.policy_id
            )

            # Add burning
            mint_map = {
                b"C3RT": -scale_amount,
                b"C3AS": -scale_amount,
            }
            mint = MultiAsset.from_primitive({self.policy_id.payload: mint_map})

            # Prepare script inputs
            script_inputs = [
                (utxo, Redeemer(ScaleDown()), script_utxo)
                for utxo in (selected_transports + selected_agg_states)
            ]

            # Build transaction using TransactionManager
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[(platform_utxo, None, platform_script), *script_inputs],
                script_outputs=[platform_utxo.output],
                mint=mint,
                mint_redeemer=Redeemer(Scale()),
                mint_script=nft_minting_script,
                required_signers=required_signers,
                change_address=change_address,
                signing_key=signing_key,
            )

            return ScaleDownResult(
                transaction=tx,
                removed_transport_utxos=selected_transports,
                removed_agg_state_utxos=selected_agg_states,
            )

        except Exception as e:
            raise ScalingError(f"Failed to build scale down transaction: {e}") from e
