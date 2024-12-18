"""Add Nodes transaction builder. """

import logging
from typing import Any

import click
from pycardano import (
    Address,
    ExtendedSigningKey,
    NativeScript,
    PaymentSigningKey,
    Redeemer,
    UTxO,
    VerificationKeyHash,
)

from charli3_offchain_core.cli.config.formatting import (
    print_confirmation_message_prompt,
    print_header,
    print_information,
)
from charli3_offchain_core.cli.config.nodes import NodesConfig
from charli3_offchain_core.models.oracle_datums import (
    Nodes,
    OracleSettingsDatum,
    RewardAccountDatum,
)
from charli3_offchain_core.models.oracle_redeemers import (
    AddNodes,
)
from charli3_offchain_core.oracle.exceptions import (
    SettingsValidationError,
    UpdateCancelled,
    UpdatingError,
)
from charli3_offchain_core.oracle.utils.common import get_reference_script_utxo
from charli3_offchain_core.oracle.utils.state_checks import (
    get_oracle_settings_by_policy_id,
    get_reward_account_by_policy_id,
)

from .base import BaseBuilder, GovernanceTxResult

logger = logging.getLogger(__name__)


class AddNodesBuilder(BaseBuilder):
    REDEEMER = Redeemer(AddNodes())
    FEE_BUFFER = 10_000

    async def build_tx(
        self,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        policy_hash: Any,
        utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        new_nodes_config: NodesConfig,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> GovernanceTxResult:
        """Build the update transaction."""
        try:
            in_core_datum, in_core_utxo = get_oracle_settings_by_policy_id(
                utxos, policy_hash
            )
            in_reward_account_datum, in_reward_account_utxo = (
                get_reward_account_by_policy_id(utxos, policy_hash)
            )

            script_utxo = get_reference_script_utxo(utxos)

            if not script_utxo:
                raise ValueError("Reference script UTxO not found")

            try:

                show_nodes_update_info(in_core_datum, new_nodes_config)

                if not print_confirmation_message_prompt(
                    "Do you want to continue with the detected changes?"
                ):
                    raise UpdateCancelled()

                out_core_utxo = modified_core_utxo(
                    in_core_utxo,
                    in_core_datum,
                    new_nodes_config,
                )
                out_reward_account_utxo = modified_reward_utxo(
                    in_reward_account_utxo,
                    in_reward_account_datum,
                    new_nodes_config,
                    in_core_datum,
                )
            except (UpdateCancelled, click.Abort):
                return GovernanceTxResult()

            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (in_reward_account_utxo, self.REDEEMER, script_utxo),
                    (in_core_utxo, self.REDEEMER, script_utxo),
                    (platform_utxo, None, platform_script),
                ],
                script_outputs=[
                    out_core_utxo.output,
                    out_reward_account_utxo.output,
                    platform_utxo.output,
                ],
                fee_buffer=self.FEE_BUFFER,
                change_address=change_address,
                signing_key=signing_key,
                required_signers=required_signers,
            )
            return GovernanceTxResult(
                transaction=tx, settings_utxo=out_core_utxo.output
            )
        except SettingsValidationError as e:
            raise UpdatingError(f"Failed to build close transaction: {e!s}") from e


def modified_core_utxo(
    in_core_utxo: UTxO,
    in_core_datum: OracleSettingsDatum,
    new_nodes_config: NodesConfig,
) -> UTxO:

    new_nodes_dict = {
        node.feed_vkh: node.payment_vkh for node in new_nodes_config.nodes
    }
    existing_nodes_dict = in_core_datum.nodes.node_map

    merged_nodes = dict(
        sorted(
            {**new_nodes_dict, **existing_nodes_dict}.items(), key=lambda x: str(x[0])
        )
    )

    new_datum = OracleSettingsDatum(
        nodes=Nodes(node_map=merged_nodes),
        required_node_signatures_count=new_nodes_config.required_signatures,
        fee_info=in_core_datum.fee_info,
        aggregation_liveness_period=in_core_datum.aggregation_liveness_period,
        time_absolute_uncertainty=in_core_datum.time_absolute_uncertainty,
        iqr_fence_multiplier=in_core_datum.iqr_fence_multiplier,
        utxo_size_safety_buffer=in_core_datum.utxo_size_safety_buffer,
        closing_period_started_at=in_core_datum.closing_period_started_at,
    )

    in_core_utxo.output.datum = new_datum
    in_core_utxo.output.datum_hash = None
    return in_core_utxo


def modified_reward_utxo(
    in_reward_utxo: UTxO,
    in_reward_datum: RewardAccountDatum,
    new_nodes_config: NodesConfig,
    in_core_datum: OracleSettingsDatum,
) -> UTxO:

    new_nodes_dict = {
        node.feed_vkh: node.payment_vkh for node in new_nodes_config.nodes
    }
    existing_nodes_dict = in_core_datum.nodes.node_map

    merged_nodes = {
        **new_nodes_dict,
        **existing_nodes_dict,
    }  # Existing nodes take precedence

    sorted_feed_vkhs = sorted(merged_nodes.keys(), key=str)

    out_distribution = []

    for feed_vkh in sorted_feed_vkhs:
        if feed_vkh in existing_nodes_dict:

            old_position = sorted(existing_nodes_dict.keys(), key=str).index(feed_vkh)
            reward = (
                in_reward_datum.nodes_to_rewards[old_position]
                if old_position < len(in_reward_datum.nodes_to_rewards)
                else 0
            )
            out_distribution.append(reward)
        else:
            out_distribution.append(0)

    new_datum = RewardAccountDatum(nodes_to_rewards=out_distribution)
    in_reward_utxo.output.datum = new_datum
    in_reward_utxo.output.datum_hash = None
    return in_reward_utxo


def show_nodes_update_info(
    in_core_datum: OracleSettingsDatum,
    new_nodes_config: NodesConfig,
) -> None:
    """Muestra información sobre los cambios que se realizarán en los nodos."""
    print_header("Node Update Information")

    print_header("Current Nodes")
    for i, (feed_vkh, payment_vkh) in enumerate(
        in_core_datum.nodes.node_map.items(), 1
    ):
        print_information(f"{i}. Feed VKH: {feed_vkh}")
        print_information(f"   Payment VKH: {payment_vkh}")

    new_nodes = {
        node.feed_vkh: node.payment_vkh
        for node in new_nodes_config.nodes
        if node.feed_vkh not in in_core_datum.nodes.node_map
    }

    if new_nodes:
        print_header("New Nodes to Add")
        for i, (feed_vkh, payment_vkh) in enumerate(new_nodes.items(), 1):
            print_information(f"{i}. Feed VKH: {feed_vkh}")
            print_information(f"   Payment VKH: {payment_vkh}")
    else:
        print_information("No new nodes to add")

    if (
        new_nodes_config.required_signatures
        != in_core_datum.required_node_signatures_count
    ):
        print_header("Required Signatures Change")
        print_information(
            f"Current required signatures: {in_core_datum.required_node_signatures_count}"
        )
        print_information(
            f"New required signatures: {new_nodes_config.required_signatures}"
        )
