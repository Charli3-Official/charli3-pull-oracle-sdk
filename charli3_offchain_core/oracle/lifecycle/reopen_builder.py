"""Reopen oracle transaction builder."""

from copy import deepcopy
from typing import Any

from pycardano import (
    Address,
    ExtendedSigningKey,
    NativeScript,
    PaymentSigningKey,
    Redeemer,
    UTxO,
)

from charli3_offchain_core.models.oracle_datums import (
    NoDatum,
    OracleSettingsVariant,
)
from charli3_offchain_core.models.oracle_redeemers import ReopenOracle
from charli3_offchain_core.oracle.exceptions import ClosingError
from charli3_offchain_core.oracle.utils.common import get_reference_script_utxo
from charli3_offchain_core.oracle.utils.state_checks import (
    get_oracle_settings_by_policy_id,
    is_oracle_closing
)

from .base import BaseBuilder, LifecycleTxResult


class ReopenBuilder(BaseBuilder):
    """Builds oracle reopen transaction."""

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

            if not is_oracle_closing(settings_datum):
                raise ClosingError("Oracle not in closing period")

            modified_datum = deepcopy(settings_datum)
            modified_settings_utxo = deepcopy(settings_utxo)
            modified_datum.closing_period_started_at = NoDatum()
            
            modified_settings_utxo.output.datum = OracleSettingsVariant(modified_datum)

            validity_start = self.chain_query.last_block_slot 
            validity_end = validity_start + (settings_datum.time_absolute_uncertainty // 1000)

            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (
                        settings_utxo,
                        Redeemer(ReopenOracle()),
                        script_utxo,
                    ),
                    (platform_utxo, None, platform_script),
                ],
                script_outputs=[modified_settings_utxo.output, platform_utxo.output],
                validity_start=validity_start,
                validity_end=validity_end,
                fee_buffer=self.FEE_BUFFER,
                change_address=change_address,
                signing_key=signing_key,
            )

            return LifecycleTxResult(
                transaction=tx,
                settings_utxo=modified_settings_utxo
            )

        except Exception as e:
            raise ValueError(f"Failed to build reopen transaction: {e!s}") from e