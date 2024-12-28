"""Remove oracle transaction builder."""

from pycardano import (
    Address,
    Asset,
    AssetName,
    ExtendedSigningKey,
    MultiAsset,
    NativeScript,
    PaymentSigningKey,
    Redeemer,
    ScriptHash,
    TransactionOutput,
    UTxO,
)

from charli3_offchain_core.blockchain.transactions import (
    TransactionConfig,
    TransactionManager,
)
from charli3_offchain_core.models.oracle_redeemers import Burn, RemoveOracle
from charli3_offchain_core.oracle.exceptions import ClosingError
from charli3_offchain_core.oracle.utils.asset_checks import filter_utxos_by_token_name
from charli3_offchain_core.oracle.utils.common import get_reference_script_utxo
from charli3_offchain_core.oracle.utils.state_checks import (
    filter_empty_transports,
    filter_valid_agg_states,
    get_oracle_settings_by_policy_id,
    get_reward_account_by_policy_id,
    is_oracle_closing,
)

from .base import BaseBuilder, LifecycleTxResult


class RemoveBuilder(BaseBuilder):
    """Builds oracle remove transaction that burns all NFTs and cleans up UTxOs."""

    FEE_BUFFER = 10_000
    EXTRA_COLLATERAL = 10_000_000

    TOKEN_CORE_SETTINGS = "CoreSettings"  # noqa
    TOKEN_REWARD_ACCOUNT = "RewardAccount"  # noqa
    TOKEN_AGG_STATE = "AggregationState"  # noqa
    TOKEN_REWARD_TRANSPORT = "RewardTransport"  # noqa

    async def build_tx(
        self,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        policy_hash: ScriptHash,
        utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        pair_count: int | None = None,
    ) -> LifecycleTxResult:
        """Build transaction to remove oracle and burn NFTs."""
        self.tx_manager = TransactionManager(
            self.chain_query, TransactionConfig(extra_collateral=self.EXTRA_COLLATERAL)
        )
        try:
            settings_datum, settings_utxo = get_oracle_settings_by_policy_id(
                utxos, policy_hash
            )
            if not is_oracle_closing(settings_datum):
                raise ClosingError("Closing period has not started")

            _, reward_utxo = get_reward_account_by_policy_id(utxos, policy_hash)
            script_utxo = get_reference_script_utxo(utxos)
            minting_script = await self.chain_query.get_plutus_script(policy_hash)

            # Calculate validity range
            validity_start_slot = self.chain_query.last_block_slot
            validity_end_slot = validity_start_slot + (
                settings_datum.time_absolute_uncertainty // 1000
            )
            current_slot_time = self.chain_query.config.network_config.slot_to_posix(
                validity_start_slot
            )

            empty_transports = filter_empty_transports(
                filter_utxos_by_token_name(
                    utxos, policy_hash, self.TOKEN_REWARD_TRANSPORT
                )
            )
            expired_and_empty_agg_states = filter_valid_agg_states(
                filter_utxos_by_token_name(utxos, policy_hash, self.TOKEN_AGG_STATE),
                current_slot_time,
            )

            burn_value, selected_agg_states, selected_transports = (
                self._calculate_burn_tokens(
                    policy_hash=policy_hash,
                    agg_states=expired_and_empty_agg_states,
                    transports=empty_transports,
                    pair_count=pair_count,
                )
            )

            ada_collect_utxo = self._collect_ada_from_utxos(
                [
                    reward_utxo,
                    settings_utxo,
                    *selected_agg_states,
                    *selected_transports,
                ],
                change_address,
            )

            script_inputs = [
                (reward_utxo, Redeemer(RemoveOracle()), script_utxo),
                (settings_utxo, Redeemer(RemoveOracle()), script_utxo),
                (platform_utxo, None, platform_script),
                *[
                    (state, Redeemer(RemoveOracle()), script_utxo)
                    for state in selected_agg_states
                ],
                *[
                    (transport, Redeemer(RemoveOracle()), script_utxo)
                    for transport in selected_transports
                ],
            ]

            tx = await self.tx_manager.build_script_tx(
                script_inputs=script_inputs,
                script_outputs=[platform_utxo.output, ada_collect_utxo],
                validity_start=validity_start_slot,
                validity_end=validity_end_slot,
                fee_buffer=self.FEE_BUFFER,
                change_address=change_address,
                signing_key=signing_key,
                mint=burn_value,
                mint_redeemer=Redeemer(Burn()),
                mint_script=minting_script,
            )

            return LifecycleTxResult(transaction=tx, settings_utxo=None)

        except Exception as e:
            raise ValueError(f"Failed to build remove transaction: {e}") from e

    def _calculate_burn_tokens(
        self,
        policy_hash: ScriptHash,
        agg_states: list[UTxO],
        transports: list[UTxO],
        pair_count: int | None = None,
    ) -> tuple[MultiAsset, list[UTxO], list[UTxO]]:
        """Calculate tokens to burn based on provided UTxO lists."""
        burn_value = MultiAsset()
        policy_assets = burn_value[policy_hash] = Asset()

        policy_assets[AssetName(self.TOKEN_CORE_SETTINGS.encode())] = -1
        policy_assets[AssetName(self.TOKEN_REWARD_ACCOUNT.encode())] = -1

        total_pairs = min(len(agg_states), len(transports))
        if pair_count is not None:
            if pair_count > total_pairs:
                raise ValueError(
                    f"Requested to burn {pair_count} pairs but only {total_pairs} "
                    "complete pairs available"
                )
            pairs_to_burn = pair_count
        else:
            pairs_to_burn = total_pairs

        if pairs_to_burn > 0:
            policy_assets[AssetName(self.TOKEN_AGG_STATE.encode())] = policy_assets[
                AssetName(self.TOKEN_REWARD_TRANSPORT.encode())
            ] = -pairs_to_burn
            return burn_value, agg_states[:pairs_to_burn], transports[:pairs_to_burn]

        return burn_value, [], []

    def _collect_ada_from_utxos(
        self, utxos: list[UTxO], change_address: Address
    ) -> TransactionOutput:
        """return utxo output with collected amount from all to be consumed utxos."""
        ada_collected = sum(utxo.output.amount.coin for utxo in utxos)
        return TransactionOutput(address=change_address, amount=ada_collected)
