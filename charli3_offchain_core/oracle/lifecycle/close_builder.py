"""Close oracle transaction builder."""

from typing import Any

from pycardano import (
    Address,
    ExtendedSigningKey,
    NativeScript,
    PaymentSigningKey,
    Redeemer,
    TransactionOutput,
    UTxO,
)

from charli3_offchain_core.models.oracle_datums import (
    OracleSettingsDatum,
    OracleSettingsVariant,
)
from charli3_offchain_core.models.oracle_redeemers import CloseOracle
from charli3_offchain_core.oracle.exceptions import ClosingError
from charli3_offchain_core.oracle.utils.common import get_reference_script_utxo
from charli3_offchain_core.oracle.utils.state_checks import (
    get_oracle_settings_by_policy_id,
    is_oracle_closing,
)

from .base import BaseBuilder, LifecycleTxResult


class CloseBuilder(BaseBuilder):
    """Builds oracle close transaction"""

    FEE_BUFFER = 10_000

    async def build_tx(
        self,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        policy_hash: Any,
        utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
    ) -> LifecycleTxResult:
        try:
            settings_datum, settings_utxo = get_oracle_settings_by_policy_id(
                utxos, policy_hash
            )
            script_utxo = get_reference_script_utxo(utxos)

            if not script_utxo:
                raise ValueError("Reference script UTxO not found")

            if is_oracle_closing(settings_datum):
                raise ClosingError("Oracle already in closing period")

            current_time = self.chain_query.get_current_posix_chain_time_ms()

            updated_settings = OracleSettingsVariant(
                OracleSettingsDatum(
                    nodes=settings_datum.nodes,
                    required_node_signatures_count=settings_datum.required_node_signatures_count,
                    fee_info=settings_datum.fee_info,
                    aggregation_liveness_period=settings_datum.aggregation_liveness_period,
                    time_absolute_uncertainty=settings_datum.time_absolute_uncertainty,
                    iqr_fence_multiplier=settings_datum.iqr_fence_multiplier,
                    utxo_size_safety_buffer=settings_datum.utxo_size_safety_buffer,
                    closing_period_started_at=current_time,
                )
            )

            settings_output = TransactionOutput(
                address=settings_utxo.output.address,
                amount=settings_utxo.output.amount,
                datum=updated_settings,
            )

            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (
                        settings_utxo,
                        Redeemer(CloseOracle()),
                        script_utxo,
                    ),
                    (platform_utxo, None, platform_script),
                ],
                script_outputs=[settings_output, platform_utxo.output],
                change_address=change_address,
                signing_key=signing_key,
            )

            return LifecycleTxResult(transaction=tx, settings_utxo=settings_output)

        except Exception as e:
            raise ValueError(f"Failed to build close transaction: {e!s}") from e
