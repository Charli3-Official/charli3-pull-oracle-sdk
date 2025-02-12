"""Platform transaction builder. """

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
    NativeScript,
    Network,
    PaymentSigningKey,
    Redeemer,
    ScriptHash,
    TransactionOutput,
    UTxO,
    Value,
    VerificationKeyHash,
)

from charli3_offchain_core.cli.config.formatting import (
    print_information,
    print_title,
)
from charli3_offchain_core.models.oracle_datums import (
    NoDatum,
    OracleSettingsDatum,
    RewardAccountDatum,
    SomeAsset,
)
from charli3_offchain_core.models.oracle_redeemers import (
    PlatformCollect,
)
from charli3_offchain_core.oracle.exceptions import (
    CollectingPlatformError,
    PlatformCollectCancelled,
    PlatformCollectValidationError,
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


class PlatformCollectBuilder(BaseBuilder):
    FEE_BUFFER = 10_000

    async def build_tx(
        self,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        policy_hash: ScriptHash,
        contract_utxos: list[UTxO],
        user_address: Address,
        reward_token: NoDatum | SomeAsset,
        network: Network,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
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

            # Modified Reward Account: Removed withdrawal amount
            out_reward_account_utxo, platform_reward = self.modified_reward_utxo(
                in_reward_account_utxo,
                in_reward_account_datum,
                in_core_datum,
                reward_token,
            )

            # Get withdrawal address
            requested_address = await confirm_withdrawal_amount_and_address(
                user_address,
                platform_reward,
                reward_token,
            )

            # Create withdrawal output UTxO
            out_platform_reward = self.platform_operator_output(
                requested_address,
                reward_token,
                platform_reward,
            )

            # Build transaction
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (
                        in_reward_account_utxo,
                        Redeemer(PlatformCollect()),
                        script_utxo,
                    ),
                    (platform_utxo, None, platform_script),
                ],
                script_outputs=[
                    out_reward_account_utxo.output,
                    out_platform_reward,
                    platform_utxo.output,
                ],
                reference_inputs={in_core_utxo},
                required_signers=required_signers,
                change_address=user_address,
                signing_key=signing_key,
            )
            return RewardTxResult(
                transaction=tx, reward_utxo=out_reward_account_utxo.output
            )

        except PlatformCollectValidationError as e:
            error_msg = f"Failed to validate Delete Nodes rules: {e}"
            logger.error(error_msg)
            return RewardTxResult(reason=error_msg)

        except CollectingPlatformError as e:
            error_msg = (
                f"Provided inputs do not account for payment rewards processing: {e}"
            )
            logger.info(error_msg)
            return RewardTxResult(reason=error_msg)

        except (PlatformCollectCancelled, click.Abort):
            logger.info("Operation cancelled")
            return RewardTxResult()

    def modified_reward_utxo(
        self,
        in_reward_utxo: UTxO,
        in_reward_datum: RewardAccountDatum,
        settings: OracleSettingsDatum,
        reward_token: NoDatum | SomeAsset,
    ) -> tuple[UTxO, int]:

        safety_buffer = settings.utxo_size_safety_buffer

        if isinstance(reward_token, NoDatum):
            return self.ada_payment_token_withdrawal(
                in_reward_utxo, in_reward_datum, safety_buffer
            )

        return self.custom_payment_token_withdrawal(
            in_reward_utxo,
            in_reward_datum,
            reward_token,
        )

    def ada_payment_token_withdrawal(
        self,
        in_reward_utxo: UTxO,
        in_reward_datum: RewardAccountDatum,
        safety_buffer: int,
    ) -> tuple[UTxO, int]:

        modified_utxo = deepcopy(in_reward_utxo)
        lovelace_balance = modified_utxo.output.amount.coin

        nodes_to_rewards = sum(in_reward_datum.nodes_to_rewards)
        fixed_amount = nodes_to_rewards + safety_buffer

        withdrawal_amount = lovelace_balance - fixed_amount

        logger.info(f"Total ADA balance: {lovelace_balance:_}")
        logger.info(f"Total Node Rewards amount: {nodes_to_rewards:_}")
        logger.info(f"Safety Buffer: {safety_buffer:_}")

        logger.info(f"Platform Reward amount: {withdrawal_amount:_} ")
        if withdrawal_amount <= 0:
            raise CollectingPlatformError(
                "There are no rewards available for withdrawal.\n"
                "Consider lowering the safety_buffer value to potentially access more funds"
            )

        modified_utxo.output.amount.coin -= withdrawal_amount
        modified_utxo = replace(
            modified_utxo,
            output=replace(
                modified_utxo.output,
                datum_hash=None,
            ),
        )

        return modified_utxo, withdrawal_amount

    def custom_payment_token_withdrawal(
        self,
        in_reward_utxo: UTxO,
        in_reward_datum: RewardAccountDatum,
        reward_token: SomeAsset,
    ) -> tuple[UTxO, int]:

        modified_utxo = deepcopy(in_reward_utxo)

        asset_name_bytes = reward_token.asset.name
        policy_id_bytes = reward_token.asset.policy_id

        asset_name = AssetName(asset_name_bytes)
        policy_hash = ScriptHash.from_primitive(policy_id_bytes.hex())

        token_balance = modified_utxo.output.amount.multi_asset.get(
            policy_hash, {}
        ).get(asset_name, 0)

        total_rewards = sum(in_reward_datum.nodes_to_rewards)
        withdrawal_amount = token_balance - total_rewards

        logger.info(f"Total token balance: {token_balance}")
        logger.info(f"Total Node Rewards amount: {total_rewards}")

        logger.info(f"Platform Reward amount: {withdrawal_amount:_} ")
        if withdrawal_amount <= 0:
            raise CollectingPlatformError(
                f"Insufficient rewards available for withdrawal. "
                f"Available: {token_balance}, Required: {total_rewards}"
            )

        modified_utxo.output.amount.multi_asset[policy_hash][
            asset_name
        ] -= withdrawal_amount

        modified_utxo = replace(
            modified_utxo,
            output=replace(
                modified_utxo.output,
                datum_hash=None,
            ),
        )

        return modified_utxo, withdrawal_amount

    def platform_operator_output(
        self,
        address: Address,
        reward_token: SomeAsset | NoDatum,
        node_reward: int,
    ) -> TransactionOutput:
        """Creates a transaction output for a node operator.

        Args:
            address: The output address
            reward_token: The reward token (SomeAsset) or NoDatum if ADA.
            node_reward: The amount of the reward.

        Returns:
            A TransactionOutput object.

        """

        if isinstance(reward_token, NoDatum):
            value = Value(coin=node_reward)
        elif isinstance(reward_token, SomeAsset):
            payment_asset = MultiAsset.from_primitive(
                {reward_token.asset.policy_id: {reward_token.asset.name: node_reward}}
            )
            value = Value(coin=self.MIN_UTXO_VALUE, multi_asset=payment_asset)

        return TransactionOutput(address=address, amount=value)


async def confirm_withdrawal_amount_and_address(
    base_address: Address,
    platform_reward: int,
    reward_token: SomeAsset | NoDatum,
) -> Address:
    """
    Prompts the user to confirm or change a Cardano address.
    """

    symbol = "₳ (lovelace)" if isinstance(reward_token, NoDatum) else "C3 (Charli3)"

    print_information(f"Total Accumulated Rewards: {platform_reward:_} {symbol}")

    print_title("Select an option:")
    click.secho("1. Base Address:", fg="blue")
    print(base_address)
    click.secho("2. Enter a new address", fg="blue")
    click.secho("q. Quit", fg="blue")

    while True:  # Loop until valid choice is made
        choice = click.prompt(
            "Enter your choice (1-2, q):",
            type=click.Choice(["1", "2", "q"]),  # Add 'q' to choices
            default="1",  # Default to the base address
        )

        if choice == "q":
            click.echo("Exiting.")
            sys.exit()
        elif choice == "1":
            return base_address
        else:  # choice == "2"
            while True:  # Keep prompting until a valid address is entered
                new_address_str = click.prompt("Please enter a new address")
                try:
                    new_address = Address.from_primitive(new_address_str)
                    return new_address
                except Exception as e:
                    click.echo(
                        f"Invalid Cardano address format: {e}. Please try again."
                    )
