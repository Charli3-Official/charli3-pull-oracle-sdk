"""Platform transaction builder. """

import logging
from copy import deepcopy
from dataclasses import replace

import click
from pycardano import (
    Address,
    AssetName,
    MultiAsset,
    NativeScript,
    Network,
    Redeemer,
    ScriptHash,
    TransactionOutput,
    UTxO,
    Value,
    VerificationKeyHash,
)

from charli3_offchain_core.blockchain.exceptions import CollateralError
from charli3_offchain_core.cli.base import LoadedKeys
from charli3_offchain_core.cli.config.formatting import (
    print_information,
    print_progress,
    print_status,
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
    NoRewardsAvailableError,
    PlatformCollectCancelled,
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

            # Modified Reward Account: Removed withdrawal amount
            out_reward_account_utxo, platform_reward = self.modified_reward_utxo(
                in_reward_account_utxo,
                in_reward_account_datum,
                in_core_datum,
                reward_token,
            )

            # Get withdrawal address
            requested_address = await confirm_withdrawal_amount_and_address(
                loaded_key,
                reward_token,
                platform_reward,
                network,
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
                change_address=loaded_key.address,
                signing_key=loaded_key.payment_sk,
            )
            return RewardTxResult(
                transaction=tx, reward_utxo=out_reward_account_utxo.output
            )

        except CollectingPlatformError as e:
            logging.error("No rewards available error")
            return RewardTxResult(exception_type=e)

        except NoRewardsAvailableError as e:
            logging.error("No rewards available error")
            return RewardTxResult(exception_type=e)

        except PlatformCollectCancelled as e:
            logger.info("Platform collect cancelled")
            return RewardTxResult(exception_type=e)

        except CollateralError as e:
            logging.error("ADA balance not found error")
            return RewardTxResult(exception_type=e)

    def modified_reward_utxo(
        self,
        in_reward_utxo: UTxO,
        in_reward_datum: RewardAccountDatum,
        settings: OracleSettingsDatum,
        reward_token: NoDatum | SomeAsset,
    ) -> tuple[UTxO, int]:

        if isinstance(reward_token, NoDatum):
            return self.ada_payment_token_withdrawal(
                in_reward_utxo, in_reward_datum, settings.utxo_size_safety_buffer
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

        lovelace_amount = modified_utxo.output.amount.coin
        node_rewards = sum(in_reward_datum.nodes_to_rewards)

        allocated_amount = node_rewards + safety_buffer
        platform_amount = lovelace_amount - allocated_amount

        logger.info(f"Lovelace amount: {lovelace_amount:_}")
        logger.info(f"Node rewards amount: {node_rewards}")
        logger.info(f"Platform reward amount: {platform_amount:_} ")
        logger.info(f"Safety buffer: {safety_buffer:_}")

        if platform_amount <= 0:
            raise CollectingPlatformError(
                "Insufficient rewards available for withdrawal."
            )

        modified_utxo.output.amount.coin -= platform_amount
        modified_utxo = replace(
            modified_utxo,
            output=replace(
                modified_utxo.output,
                datum_hash=None,
            ),
        )

        return modified_utxo, platform_amount

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

        node_rewards = sum(in_reward_datum.nodes_to_rewards)
        platform_amount = token_balance - node_rewards

        logger.info(f"Reward balance: {token_balance:_}")
        logger.info(f"Node rewards amount: {node_rewards:_}")
        logger.info(f"Platform reward amount: {platform_amount:_}")

        if platform_amount <= 0:
            raise CollectingPlatformError(
                "Insufficient rewards available for withdrawal."
            )

        modified_utxo.output.amount.multi_asset[policy_hash][
            asset_name
        ] -= platform_amount

        modified_utxo = replace(
            modified_utxo,
            output=replace(
                modified_utxo.output,
                datum_hash=None,
            ),
        )

        return modified_utxo, platform_amount

    def platform_operator_output(
        self,
        address: Address,
        reward_token: SomeAsset | NoDatum,
        platform_reward: int,
    ) -> TransactionOutput:
        """Creates a transaction output for a node operator.

        Args:
            address: The address of the platform operator
            reward_token: The reward token (SomeAsset) or NoDatum if ADA.
            platform_reward: The amount of the reward.

        Returns:
            A TransactionOutput object.

        """

        if isinstance(reward_token, NoDatum):
            if platform_reward < self.MIN_UTXO_VALUE:
                raise NoRewardsAvailableError(
                    f"The ADA amount is too small {platform_reward}"
                )
            value = Value(coin=platform_reward)
        elif isinstance(reward_token, SomeAsset):
            payment_asset = MultiAsset.from_primitive(
                {
                    reward_token.asset.policy_id: {
                        reward_token.asset.name: platform_reward
                    }
                }
            )
            value = Value(coin=self.MIN_UTXO_VALUE, multi_asset=payment_asset)

        return TransactionOutput(address=address, amount=value)


async def confirm_withdrawal_amount_and_address(
    loaded_key: LoadedKeys,
    reward_token: SomeAsset | NoDatum,
    platform_reward: int,
    network: Network,
) -> Address:
    """
    Prompts the user to confirm or change an address.
    """
    print_progress("Loading wallet configuration...")

    symbol = "₳ (lovelace)" if isinstance(reward_token, NoDatum) else "C3 (Charli3)"

    print_status(
        "Verififcaion Key Hash associated with user's wallet",
        message=f"{loaded_key.payment_vk.hash()}",
    )

    print_information(f"Total Accumulated Rewards: {platform_reward:_} {symbol}")

    print_title(
        "Select a withdrawal address (derived from your mnemonic configuration):"
    )

    enterprise_addr = Address(
        payment_part=loaded_key.payment_vk.hash(), network=network
    )

    click.secho("1. Base Address:", fg="blue")
    print(loaded_key.address)
    click.secho("2. Enterprise Address", fg="blue")
    print(enterprise_addr)
    click.secho("3. Enter a new address", fg="blue")
    click.secho("q. Quit", fg="blue")

    while True:  # Loop until valid choice is made
        choice = click.prompt(
            "Enter your choice (1-2, q):",
            type=click.Choice(["1", "2", "q"]),  # Add 'q' to choices
            default="1",  # Default to the base address
        )

        if choice == "q":
            click.echo("Exiting.")
            raise PlatformCollectCancelled()
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
                    raise PlatformCollectCancelled()
                try:
                    new_address = Address.from_primitive(new_address_str)
                    return new_address
                except Exception as e:
                    click.echo(
                        f"Invalid Cardano address format: {e}. Please try again."
                    )
