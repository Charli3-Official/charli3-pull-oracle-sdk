from typing import Any

from pycardano import (
    Address,
    Asset,
    AssetName,
    ExtendedSigningKey,
    MultiAsset,
    NativeScript,
    PaymentSigningKey,
    Redeemer,
    TransactionOutput,
    UTxO,
)

from charli3_offchain_core.blockchain.transactions import (
    TransactionConfig,
    TransactionManager,
)
from charli3_offchain_core.models.oracle_datums import (
    OracleSettingsDatum,
    RewardAccountDatum,
)
from charli3_offchain_core.models.oracle_redeemers import Burn, RemoveOracle
from charli3_offchain_core.oracle.exceptions import ClosingError
from charli3_offchain_core.oracle.utils.asset_checks import filter_utxos_by_token_name
from charli3_offchain_core.oracle.utils.common import get_reference_script_utxo
from charli3_offchain_core.oracle.utils.state_checks import (
    filter_empty_agg_states,
    filter_empty_transports,
    get_oracle_settings_by_policy_id,
    get_reward_account_by_policy_id,
    is_oracle_closing,
)

from .base import BaseBuilder, LifecycleTxResult


class RemoveBuilder(BaseBuilder):
    """Builds oracle remove transaction that burns all NFTs and cleans up UTxOs."""

    FEE_BUFFER = 10_000
    EXTRA_COLLATERAL = 10_000_000

    async def build_tx(
        self,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        policy_hash: Any,
        utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
    ) -> LifecycleTxResult:
        """Build transaction to remove oracle and burn NFTs."""
        self.tx_manager = TransactionManager(
            self.chain_query, TransactionConfig(extra_collateral=self.EXTRA_COLLATERAL)
        )
        try:
            settings_datum, settings_utxo = get_oracle_settings_by_policy_id(
                utxos, policy_hash
            )
            if not isinstance(settings_datum, OracleSettingsDatum):
                raise ValueError("settings_datum is not of type OracleSettingsDatum")

            reward_datum, reward_utxo = get_reward_account_by_policy_id(
                utxos, policy_hash
            )
            if not isinstance(reward_datum, RewardAccountDatum):
                raise ValueError("reward_datum is not of type RewardAccountDatum")

            script_utxo = get_reference_script_utxo(utxos)
            if not script_utxo:
                raise ValueError("Reference script UTxO not found")

            if not is_oracle_closing(settings_datum):
                raise ClosingError("Closing period has not started")

            minting_script = await self.chain_query.get_plutus_script(policy_hash)

            current_slot = self.chain_query.last_block_slot
            validity_end = current_slot + (
                settings_datum.time_absolute_uncertainty // 1000
            )

            transports = filter_empty_transports(
                filter_utxos_by_token_name(utxos, policy_hash, "RewardTransport")
            )
            agg_states = filter_empty_agg_states(
                filter_utxos_by_token_name(utxos, policy_hash, "AggregationState")
            )

            burn_value = self._calculate_burn_tokens(
                policy_hash=policy_hash, agg_states=agg_states, transports=transports
            )

            ada_to_collect = self._collect_ada_from_utxos(
                [*reward_utxo, *settings_utxo, *agg_states, *transports]
            )

            script_inputs = [
                (reward_utxo, Redeemer(RemoveOracle()), script_utxo),
                (settings_utxo, Redeemer(RemoveOracle()), script_utxo),
                (platform_utxo, None, platform_script),
            ]

            if agg_states:
                script_inputs.extend(
                    [
                        (state, Redeemer(RemoveOracle()), script_utxo)
                        for state in agg_states
                    ]
                )
            if transports:
                script_inputs.extend(
                    [
                        (transport, Redeemer(RemoveOracle()), script_utxo)
                        for transport in transports
                    ]
                )

            ada_collect_utxo = TransactionOutput(
                address=change_address, amount=ada_to_collect
            )

            tx = await self.tx_manager.build_script_tx(
                script_inputs=script_inputs,
                script_outputs=[platform_utxo.output, ada_collect_utxo],
                validity_start=current_slot,
                validity_end=validity_end,
                fee_buffer=self.FEE_BUFFER,
                change_address=change_address,
                signing_key=signing_key,
                mint=burn_value,
                mint_redeemer=Redeemer(Burn()),
                mint_script=minting_script,
            )

            return LifecycleTxResult(
                transaction=tx,
                settings_utxo=None,
            )

        except Exception as e:
            raise ValueError(f"Failed to build remove transaction: {e}") from e

    def _calculate_burn_tokens(
        self, policy_hash: Any, agg_states: list[UTxO], transports: list[UTxO]
    ) -> MultiAsset:
        """Calculate tokens to burn based on provided UTxO lists."""
        burn_value = MultiAsset()
        burn_value[policy_hash] = Asset()

        burn_value[policy_hash][AssetName(b"CoreSettings")] = -1
        burn_value[policy_hash][AssetName(b"RewardAccount")] = -1

        if len(agg_states) > 0:
            burn_value[policy_hash][AssetName(b"AggregationState")] = -len(agg_states)
        if len(transports) > 0:
            burn_value[policy_hash][AssetName(b"RewardTransport")] = -len(transports)

        return burn_value

    def _collect_ada_from_utxos(self, utxos: list[UTxO]) -> int:
        """Collect ADA from a list of UTxOs."""
        ada_collected = 0
        for utxo in utxos:
            ada_collected += utxo.output.amount.coin
        return ada_collected
