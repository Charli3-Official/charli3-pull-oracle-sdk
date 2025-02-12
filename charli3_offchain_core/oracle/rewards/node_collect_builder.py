"""Reward transaction builder. """

import logging
import sys
from copy import deepcopy
from dataclasses import replace

import click
from pycardano import (
    Address,
    AssetName,
    ExtendedSigningKey,
    MultiAsset,
    Network,
    PaymentSigningKey,
    Redeemer,
    ScriptHash,
    TransactionOutput,
    UTxO,
    Value,
    VerificationKeyHash,
    min_lovelace_post_alonzo,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.cli.config.formatting import (
    CliColor,
    print_information,
    print_status,
    print_title,
)
from charli3_offchain_core.models.oracle_datums import (
    NoDatum,
    OracleSettingsDatum,
    RewardAccountDatum,
    RewardAccountVariant,
    SomeAsset,
)
from charli3_offchain_core.models.oracle_redeemers import (
    NodeCollect,
)
from charli3_offchain_core.oracle.exceptions import (
    CollectingNodesError,
    NodeCollectCancelled,
    NodeCollectValidationError,
)
from charli3_offchain_core.oracle.rewards.base import BaseBuilder, RewardTxResult
from charli3_offchain_core.oracle.utils.common import (
    get_reference_script_utxo,
)
from charli3_offchain_core.oracle.utils.state_checks import (
    get_oracle_settings_by_policy_id,
    get_reward_account_by_policy_id,
)

logger = logging.getLogger(__name__)


class NodeCollectBuilder(BaseBuilder):
    FEE_BUFFER = 10_000
    EXTRA_COLLATERAL = 5_000_000

    async def build_tx(
        self,
        policy_hash: ScriptHash,
        contract_utxos: list[UTxO],
        user_address: Address,
        reward_token: NoDatum | SomeAsset,
        network: Network,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> RewardTxResult:
        try:

            node_payment_vkh = node_id_for_withdrawal_prompt()

            if not node_payment_vkh:
                raise NodeCollectValidationError(
                    "Please provide the Node Operator Payment Verification Key Hash to proceed."
                )

            # Input Core Settings UTxO
            in_core_datum, in_core_utxo = get_oracle_settings_by_policy_id(
                contract_utxos, policy_hash
            )

            # Input Reward Account UTxO
            in_reward_account_datum, in_reward_account_utxo = (
                get_reward_account_by_policy_id(contract_utxos, policy_hash)
            )

            # Contract Script
            script_utxo = get_reference_script_utxo(contract_utxos)

            # Modified Reward Account: Removed withdrawal amount
            out_reward_account_utxo, node_reward = self.modified_reward_utxo(
                in_reward_account_utxo,
                in_reward_account_datum,
                node_payment_vkh,
                in_core_datum,
                reward_token,
            )

            # Get withdrawal address
            requested_address = await confirm_withdrawal_amount_and_address(
                user_address,
                node_payment_vkh,
                network,
                node_reward,
                reward_token,
                self.EXTRA_COLLATERAL,
                self.chain_query,
            )

            # Create withdrawal output UTxO
            out_operator_reward = self.node_operator_output(
                requested_address,
                reward_token,
                node_reward,
            )

            # Build transaction
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (
                        in_reward_account_utxo,
                        Redeemer(NodeCollect()),
                        script_utxo,
                    ),
                ],
                script_outputs=[out_reward_account_utxo.output, out_operator_reward],
                reference_inputs={in_core_utxo},
                required_signers=required_signers,
                change_address=user_address,
                signing_key=signing_key,
                external_collateral=self.EXTRA_COLLATERAL,
            )
            return RewardTxResult(
                transaction=tx, reward_utxo=out_reward_account_utxo.output
            )

        except NodeCollectValidationError as e:
            error_msg = f"Failed to validate Delete Nodes rules: {e}"
            logger.error(error_msg)
            return RewardTxResult(reason=error_msg)

        except CollectingNodesError as e:
            error_msg = (
                f"Provided inputs do not account for payment rewards processing: {e}"
            )
            logger.info(error_msg)
            return RewardTxResult(reason=error_msg)

        except (NodeCollectCancelled, click.Abort):
            logger.info("Operation cancelled")
            return RewardTxResult()

    def modified_reward_utxo(
        self,
        in_reward_utxo: UTxO,
        in_reward_datum: RewardAccountDatum,
        node_to_redeem: VerificationKeyHash,
        settings: OracleSettingsDatum,
        reward_token: NoDatum | SomeAsset,
    ) -> tuple[UTxO, int]:

        registered_reward: int = 0
        node_rewards = in_reward_datum.nodes_to_rewards
        nodes = list(settings.nodes.node_map.values())

        if node_to_redeem not in nodes:
            raise CollectingNodesError(
                "Input Payment Verification Key not found on registered Nodes"
            )

        node_index = nodes.index(node_to_redeem)
        registered_reward = node_rewards[node_index]
        new_rewards = [0 if i == node_index else r for i, r in enumerate(node_rewards)]
        modified_datum = RewardAccountDatum(new_rewards)

        if registered_reward <= 0:
            raise CollectingNodesError(
                "There are no rewards available in your account at this time"
            )

        if isinstance(reward_token, NoDatum):
            return self.ada_payment_token_withdrawal(
                in_reward_utxo, registered_reward, modified_datum
            )

        return self.custom_payment_token_withdrawal(
            in_reward_utxo,
            reward_token,
            registered_reward,
            modified_datum,
        )

    def ada_payment_token_withdrawal(
        self,
        in_reward_utxo: UTxO,
        registered_reward: int,
        modified_datum: RewardAccountDatum,
    ) -> tuple[UTxO, int]:

        modified_utxo = deepcopy(in_reward_utxo)

        lovelace_balance = modified_utxo.output.amount.coin
        minimum_lovelace_required = min_lovelace_post_alonzo(
            modified_utxo.output, self.chain_query.context
        )
        logger.info(
            f"Minimum lovelace required for Reward Account UTxO {minimum_lovelace_required}"
        )

        if lovelace_balance < minimum_lovelace_required + registered_reward:
            raise CollectingNodesError(
                f"The ADA payment amount ({registered_reward})"
                f"exceeds the quantity in the Reward Account UTxO ({lovelace_balance}), "
                "which must also satisfy a minimum lovelace requirement"
                f"of {minimum_lovelace_required}."
            )

        modified_utxo.output.amount.coin -= registered_reward
        modified_utxo = replace(
            modified_utxo,
            output=replace(
                modified_utxo.output,
                datum=RewardAccountVariant(datum=modified_datum),
                datum_hash=None,
            ),
        )

        return modified_utxo, registered_reward

    def custom_payment_token_withdrawal(
        self,
        in_reward_utxo: UTxO,
        reward_token: SomeAsset,
        registered_reward: int,
        modified_datum: RewardAccountDatum,
    ) -> tuple[UTxO, int]:

        modified_utxo = deepcopy(in_reward_utxo)

        asset_name_bytes = reward_token.asset.name
        policy_id_bytes = reward_token.asset.policy_id

        asset_name = AssetName(asset_name_bytes)
        policy_hash = ScriptHash.from_primitive(policy_id_bytes.hex())

        token_balance = modified_utxo.output.amount.multi_asset.get(
            policy_hash, {}
        ).get(asset_name, 0)

        if token_balance < registered_reward:
            raise CollectingNodesError(
                f"Insufficient rewards available for withdrawal. "
                f"Available: {token_balance}, Required: {registered_reward}"
            )
        modified_utxo.output.amount.multi_asset[policy_hash][
            asset_name
        ] -= registered_reward

        modified_utxo = replace(
            modified_utxo,
            output=replace(
                modified_utxo.output,
                datum=RewardAccountVariant(datum=modified_datum),
                datum_hash=None,
            ),
        )

        return modified_utxo, registered_reward

    def node_operator_output(
        self,
        address: Address,
        reward_token: SomeAsset | NoDatum,
        node_reward: int,
    ) -> TransactionOutput:
        """Creates a transaction output for a node operator.

        Args:
            node_vkh: The verification key hash of the node operator.
            reward_token: The reward token (SomeAsset) or NoDatum if ADA.
            network: The network the transaction is for.
            node_reward: The amount of the reward.

        Returns:
            A TransactionOutput object.

        """

        if isinstance(reward_token, NoDatum):
            value = Value(coin=max(node_reward, self.MIN_UTXO_VALUE))
        elif isinstance(reward_token, SomeAsset):
            payment_asset = MultiAsset.from_primitive(
                {reward_token.asset.policy_id: {reward_token.asset.name: node_reward}}
            )
            value = Value(coin=self.MIN_UTXO_VALUE, multi_asset=payment_asset)

        return TransactionOutput(address=address, amount=value)


def node_id_for_withdrawal_prompt() -> VerificationKeyHash | None:
    while True:
        payment_vkh = click.prompt(
            click.style(
                "Enter Node Operator Payment Verification Key Hash",
                fg=CliColor.WARNING,
                bold=True,
            ),
            type=str,
            default="",
        )

        if not payment_vkh:  # Check for empty input
            return None

        try:
            return VerificationKeyHash.from_primitive(bytes.fromhex(payment_vkh))
        except (ValueError, AssertionError, TypeError) as err:
            print_status(
                "Verification Key Hash valid utf-8 string (max 32 bytes)",
                str(err),
                success=False,
            )


async def confirm_withdrawal_amount_and_address(
    base_address: Address,
    node_vkh: VerificationKeyHash,
    network: Network,
    node_reward: int,
    reward_token: SomeAsset | NoDatum,
    extra_collateral: int,
    chain_query: ChainQuery,
) -> Address:
    """
    Prompts the user to confirm or change a Cardano address.
    """
    enterprise_address = Address(payment_part=node_vkh, network=network)

    symbol = "₳ (lovelace)" if isinstance(reward_token, NoDatum) else "C3 (Charli3)"

    print_information(f"VKH Total Accumulated Rewards: {node_reward:_} {symbol}")

    print_title("Select a withdrawal address (derived from your VKH):")
    click.secho("1. Enterprise Address:", fg="blue")
    print(enterprise_address)
    click.secho("2. Base Address:", fg="blue")
    print(base_address)
    click.secho("3. Enter a new address", fg="blue")
    click.secho("q. Quit", fg="blue")

    collateral_utxo = await chain_query.find_collateral(base_address, extra_collateral)
    amount = collateral_utxo.output.amount.coin // 1_000_000
    click.secho(
        f"To withdraw rewards, your base address needs to have enough ADA to cover transaction fees.\n"
        f"The minimum required is 5 ADA in one UTxO. I found {amount} ADA in your wallet.\n"
        f"If not found, the system will automatically create a new UTxO with 5 ADA from a larger UTxO.\n"
        "This will involve two transactions to ensure your withdrawal is successful\n",
        fg=CliColor.WARNING,
        bold=True,
    )
    while True:  # Loop until valid choice is made
        choice = click.prompt(
            "Enter your choice (1-3, q):",
            type=click.Choice(["1", "2", "3", "q"]),  # Add 'q' to choices
            default="1",  # Default to the enterprise address
        )

        if choice == "q":
            click.echo("Exiting.")
            sys.exit()
        elif choice == "1":
            return enterprise_address
        elif choice == "2":
            return base_address
        else:  # choice == "3"
            while True:  # Keep prompting until a valid address is entered
                new_address_str = click.prompt("Please enter a new address")
                try:
                    new_address = Address.from_primitive(new_address_str)
                    return new_address
                except Exception as e:
                    click.echo(
                        f"Invalid Cardano address format: {e}. Please try again."
                    )
