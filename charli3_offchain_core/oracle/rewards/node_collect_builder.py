"""Reward transaction builder. """

import logging
from copy import deepcopy
from dataclasses import replace

import click
from pycardano import (
    Address,
    AssetName,
    MultiAsset,
    Network,
    Redeemer,
    ScriptHash,
    TransactionOutput,
    UTxO,
    Value,
    VerificationKeyHash,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.exceptions import CollateralError
from charli3_offchain_core.cli.base import LoadedKeys
from charli3_offchain_core.cli.config.formatting import (
    CliColor,
    print_information,
    print_progress,
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
    ADABalanceNotFoundError,
    CollectingNodesError,
    NodeCollectCancelled,
    NodeNotRegisteredError,
    NoRewardsAvailableError,
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
        reward_token: NoDatum | SomeAsset,
        loaded_key: LoadedKeys,
        network: Network,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> RewardTxResult:
        try:

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

            # Modified Reward Account
            out_reward_account_utxo, node_reward = self.modified_reward_utxo(
                in_reward_account_utxo,
                in_reward_account_datum,
                loaded_key.payment_vk.hash(),
                in_core_datum,
                reward_token,
            )

            # Modified Reward Account: Removed withdrawal amount
            requested_address = await confirm_withdrawal_amount_and_address(
                loaded_key,
                reward_token,
                node_reward,
                self.EXTRA_COLLATERAL,
                self.chain_query,
                network=network,
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
                change_address=loaded_key.address,
                signing_key=loaded_key.payment_sk,
                external_collateral=self.EXTRA_COLLATERAL,
            )
            return RewardTxResult(
                transaction=tx, reward_utxo=out_reward_account_utxo.output
            )

        except CollectingNodesError as e:
            logger.info("Collecting nodes error")
            return RewardTxResult(exception_type=e)

        except NodeCollectCancelled as e:
            logger.info("Node collect cancelled")
            return RewardTxResult(exception_type=e)

        except NodeNotRegisteredError as e:
            logger.error("Node not registered error")
            return RewardTxResult(exception_type=e)

        except NoRewardsAvailableError as e:
            logging.error("No rewards available error")
            return RewardTxResult(exception_type=e)

        except (ADABalanceNotFoundError, CollateralError) as e:
            logging.error("ADA balance not found error")
            return RewardTxResult(exception_type=e)

    def modified_reward_utxo(
        self,
        in_reward_utxo: UTxO,
        in_reward_datum: RewardAccountDatum,
        node_to_redeem: VerificationKeyHash,
        settings: OracleSettingsDatum,
        reward_token: NoDatum | SomeAsset,
    ) -> tuple[UTxO, int]:

        node_rewards = in_reward_datum.nodes_to_rewards
        payment_vkhs = list(settings.nodes.node_map.values())

        try:
            node_index = payment_vkhs.index(node_to_redeem)
        except ValueError as err:
            raise NodeNotRegisteredError(str(node_to_redeem)) from err

        registered_reward = node_rewards[node_index]
        new_rewards = [0 if i == node_index else r for i, r in enumerate(node_rewards)]
        modified_datum = RewardAccountDatum(new_rewards)

        if registered_reward <= 0:
            raise NoRewardsAvailableError(str(node_to_redeem))

        if isinstance(reward_token, NoDatum):
            return self.ada_payment_token_withdrawal(
                in_reward_utxo,
                registered_reward,
                modified_datum,
                settings.utxo_size_safety_buffer,
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
        safety_buffer: int,
    ) -> tuple[UTxO, int]:

        modified_utxo = deepcopy(in_reward_utxo)

        lovelace_amount = modified_utxo.output.amount.coin

        logger.info(f"Reward balance: {lovelace_amount:_}")
        logger.info(f"Node reward amount: {registered_reward:_}")
        logger.info(f"Safety buffer: {safety_buffer:_}")

        if lovelace_amount < registered_reward + safety_buffer:
            raise CollectingNodesError("Insufficient rewards available for withdrawal.")

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

        logger.info(f"Reward balance: {token_balance:_}")
        logger.info(f"Node reward amount: {registered_reward:_}")

        if token_balance < registered_reward:
            raise CollectingNodesError("Insufficient rewards available for withdrawal.")

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
            address: The address of the node operator.
            reward_token: The reward token (SomeAsset) or NoDatum if ADA.
            node_reward: The amount of the reward.

        Returns:
            A TransactionOutput object.

        """

        if isinstance(reward_token, NoDatum):
            if node_reward < self.MIN_UTXO_VALUE:
                raise NoRewardsAvailableError(
                    f"The ADA amount is too small {node_reward}"
                )
            value = Value(coin=node_reward)
        elif isinstance(reward_token, SomeAsset):
            payment_asset = MultiAsset.from_primitive(
                {reward_token.asset.policy_id: {reward_token.asset.name: node_reward}}
            )
            value = Value(coin=self.MIN_UTXO_VALUE, multi_asset=payment_asset)

        return TransactionOutput(address=address, amount=value)


async def confirm_withdrawal_amount_and_address(
    loaded_key: LoadedKeys,
    reward_token: SomeAsset | NoDatum,
    node_reward: int,
    extra_collateral: int,
    chain_query: ChainQuery,
    network: Network,
) -> Address:
    """
    Prompts the user to confirm or change an address.
    """
    print_progress("Loading wallet configuration...")

    user_message = (
        "You need 5 ADA in a UTxO to claim rewards.\n"
        "If you lack it, we'll create a 5 ADA collateral UTxO\n"
        "from your existing funds. This is automatic.\n"
        "This collateral is used to cover the transaction fees\n"
        "when you withdraw your rewards.\n"
    )
    if not click.confirm(click.style(user_message, fg=CliColor.WARNING, bold=True)):
        raise NodeCollectCancelled()

    collateral_utxo = await chain_query.get_or_create_collateral(
        loaded_key.address, loaded_key.payment_sk, extra_collateral
    )

    if collateral_utxo is None:
        raise ADABalanceNotFoundError("No collateral UTXO found")

    symbol = "₳ (lovelace)" if isinstance(reward_token, NoDatum) else "C3 (Charli3)"

    print_status(
        "Verififcaion Key Hash associated with user's wallet",
        message=f"{loaded_key.payment_vk.hash()}",
    )
    print_information(f"Total Accumulated Rewards: {node_reward:_} {symbol}")

    print_title(
        "Select a withdrawal address (derived from your mnemonic configuration):"
    )

    enterprise_addr = Address(
        payment_part=loaded_key.payment_vk.hash(), network=network
    )
    click.secho("1. Base Address:", fg="blue")
    print(loaded_key.address)
    click.secho("2. Enterprise Address:", fg="blue")
    print(enterprise_addr)
    click.secho("3. Enter a new address", fg="blue")
    click.secho("q. Quit", fg="blue")

    while True:  # Loop until valid choice is made
        choice = click.prompt(
            "Enter your choice (1-3, q):",
            type=click.Choice(["1", "2", "3", "q"]),  # Add 'q' to choices
            default="1",  # Default to the base address
        )

        if choice == "q":
            click.echo("Exiting.")
            raise NodeCollectCancelled()
        elif choice == "1":
            return loaded_key.address
        elif choice == "2":
            return enterprise_addr
        else:  # choice == "3"
            while True:  # Keep prompting until a valid address is entered
                new_address_str = click.prompt(
                    "Please enter a new address (or 'q' to quit)"
                )
                if new_address_str.lower() == "q":
                    click.echo("Exiting.")
                    raise NodeCollectCancelled()
                try:
                    new_address = Address.from_primitive(new_address_str)
                    return new_address
                except Exception as e:
                    click.echo(
                        f"Invalid Cardano address format: {e}. Please try again."
                    )
