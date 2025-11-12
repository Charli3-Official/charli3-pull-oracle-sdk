"""Dismiss Reward builder"""

import logging
from copy import deepcopy
from dataclasses import dataclass, replace

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

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.network import NetworkConfig
from charli3_offchain_core.cli.base import LoadedKeys
from charli3_offchain_core.cli.config.formatting import (
    print_information,
    print_progress,
    print_status,
    print_title,
)
from charli3_offchain_core.models.base import PosixTimeDiff
from charli3_offchain_core.models.oracle_datums import (
    NoDatum,
    SomeAsset,
)
from charli3_offchain_core.models.oracle_redeemers import (
    DismissRewards,
)
from charli3_offchain_core.oracle.exceptions import (
    DismissRewardCancelledError,
    NoExpiredTransportsYetError,
    NoPendingTransportsFoundError,
    NoRewardsAvailableError,
)
from charli3_offchain_core.oracle.rewards.base import BaseBuilder, RewardTxResult
from charli3_offchain_core.oracle.utils import asset_checks
from charli3_offchain_core.oracle.utils.common import (
    get_reference_script_utxo,
)
from charli3_offchain_core.oracle.utils.state_checks import (
    filter_pending_transports,
    get_oracle_settings_by_policy_id,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidityWindow:
    """Represents the validity window for a transaction."""

    start: int
    end: int
    current_time: int


class DismissRewardsBuilder(BaseBuilder):
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
        reward_dismission_period_length: int,
        max_inputs: int,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> RewardTxResult:
        try:

            # Input Core Settings UTxO
            in_core_datum, _ = get_oracle_settings_by_policy_id(
                contract_utxos, policy_hash
            )

            # Contract Script
            script_utxo = get_reference_script_utxo(contract_utxos)

            # validity window
            validity_window = self._calculate_validity_window(
                in_core_datum.time_uncertainty_platform
            )

            # Conversion
            start_slot, end_slot = validity_window_to_slot(
                self.tx_manager.chain_query.config.network_config,
                validity_window.start,
                validity_window.end,
            )
            # Find pending transports and the accumulated reward
            unprocessed_transports, platform_reward = self.find_pending_transports(
                max_inputs,
                contract_utxos,
                policy_hash,
                validity_window,
                reward_dismission_period_length,
            )

            # Empty transports
            empty_transports = create_empty_transports(
                unprocessed_transports,
                in_core_datum.utxo_size_safety_buffer,
                reward_token,
            )

            # Get withdrawal address
            requested_address = await confirm_withdrawal_amount_and_address(
                loaded_key,
                reward_token,
                platform_reward,
                network,
                len(empty_transports),
            )

            # Create withdrawal output UTxO
            out_platform_reward = self.platform_operator_output(
                requested_address,
                reward_token,
                platform_reward,
            )

            # Build transaction
            reward_transport_inputs = [
                (t, Redeemer(DismissRewards()), script_utxo)
                for t in unprocessed_transports
            ]

            platform_auth = (platform_utxo, None, platform_script)

            tx = await self.tx_manager.build_script_tx(
                script_inputs=[*reward_transport_inputs, platform_auth],
                script_outputs=[
                    *empty_transports,
                    platform_utxo.output,
                    out_platform_reward,
                ],
                change_address=loaded_key.address,
                signing_key=loaded_key.payment_sk,
                validity_start=start_slot,
                validity_end=end_slot,
                required_signers=required_signers,
            )

            return RewardTxResult(transaction=tx)

        except NoRewardsAvailableError as e:
            logging.error("No rewards available error")
            return RewardTxResult(exception_type=e)

        except NoPendingTransportsFoundError as e:
            logging.error("No pending transports found")
            return RewardTxResult(exception_type=e)

        except DismissRewardCancelledError as e:
            logging.error("Dismiss Reward cancelled")
            return RewardTxResult(exception_type=e)

        except NoExpiredTransportsYetError as e:
            logging.error("No expired transports yet")
            return RewardTxResult(exception_type=e)

    def _calculate_validity_window(
        self,
        time_uncertainty_platform: PosixTimeDiff,
    ) -> ValidityWindow:
        """Calculate the validity window for transactions."""
        start, end, current = calculate_validity_window(
            self.tx_manager.chain_query,
            time_uncertainty_platform,
        )

        return ValidityWindow(start=start, end=end, current_time=current)

    def _must_be_after_dismissing_period(
        self,
        pending_transports: list[UTxO],
        validity_window: ValidityWindow,
        reward_dismissal_period_length: int,
    ) -> list[UTxO]:
        """
        Filter transports that have exceeded the reward dismissal period.

        Args:
            pending_transports: List of UTxO objects to filter
            validity_window: Transaction validation information
            reward_dismissal_period_length: Length of the dismissal period

        Returns:
            List of UTxO objects that have exceeded the dismissal period
        """
        eligible_transports = []
        start_slot = validity_window.start

        if start_slot is None:
            raise ValueError("start_slot is None")

        for transport in pending_transports:
            transport_datum = transport.output.datum

            if not isinstance(transport_datum, RewardTransportVariant):  # noqa: F821
                continue

            if not isinstance(
                transport_datum.datum, RewardConsensusPending  # noqa: F821
            ):
                continue

            # Message creation time
            creation_time = transport_datum.datum.aggregation.message.timestamp

            # Dismissal start
            expiration_time = creation_time + reward_dismissal_period_length

            logger.info(f"Creation Message time: {creation_time}")
            logger.info(f"Expiration Message time: {expiration_time}")
            logger.info(f"Start tx validation: {start_slot}")
            # Check if the dismissal period has passed and the validity start transaction can begin.
            if expiration_time <= start_slot:
                eligible_transports.append(transport)

        return eligible_transports

    def find_pending_transports(
        self,
        max_inputs: int,
        input_utxos: list[UTxO],
        policy_id: ScriptHash,
        validity_window: ValidityWindow,
        reward_dismission_period_length: int,
    ) -> tuple[list[UTxO], int]:
        pending_transports = filter_pending_transports(
            asset_checks.filter_utxos_by_token_name(input_utxos, policy_id, "C3RT")
        )[:max_inputs]

        if not pending_transports:
            raise NoPendingTransportsFoundError("No pending transport UTxOs found")

        validated_pending_transports = self._must_be_after_dismissing_period(
            pending_transports,
            validity_window,
            reward_dismission_period_length,
        )
        if not validated_pending_transports:
            raise NoExpiredTransportsYetError(
                "No expired transport UTxOs found\n"
                f"Total transport UTxOs: {len(pending_transports)}\n"
            )

        total_claimable_transport_rewards = sum(
            valid_transport.output.datum.datum.aggregation.rewards_amount_paid
            for valid_transport in validated_pending_transports
        )
        return validated_pending_transports, total_claimable_transport_rewards

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
                    f"The ADA amount is too small {platform_reward:_}"
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


def create_empty_transports(
    pending_transports: list[UTxO],
    safety_buffer: int,
    reward_token: NoDatum | SomeAsset,
) -> list[TransactionOutput]:
    new_transports = [
        create_empty_transport(transport, safety_buffer, reward_token)
        for transport in pending_transports
    ]
    return new_transports


def create_empty_transport(
    transport: UTxO, safety_buffer: int, reward_token: NoDatum | SomeAsset
) -> TransactionOutput:
    """Create empty reward transport output."""
    modified_utxo = deepcopy(transport)

    # Just set the fee token quantity to 0 - MultiAsset normalize() will handle cleanup
    if isinstance(reward_token, SomeAsset):

        policy_id_bytes = reward_token.asset.policy_id
        policy_id = ScriptHash.from_primitive(policy_id_bytes.hex())

        asset_name_bytes = reward_token.asset.name
        asset_name = AssetName(asset_name_bytes)

        modified_utxo.output.amount.multi_asset[policy_id][asset_name] = 0
    elif isinstance(reward_token, NoDatum):
        modified_utxo.output.amount.coin = safety_buffer

    return replace(
        modified_utxo.output,
        datum=RewardTransportVariant(datum=NoRewards()),  # noqa: F821
        datum_hash=None,
    )


def calculate_validity_window(
    chain_query: ChainQuery, time_absolute_uncertainty: int
) -> tuple[int, int, int]:
    """Calculate transaction validity window and current time."""
    validity_start = chain_query.get_current_posix_chain_time_ms()
    validity_end = validity_start + time_absolute_uncertainty
    current_time = (validity_end + validity_start) // 2
    return validity_start, validity_end, current_time


def validity_window_to_slot(
    network_config: NetworkConfig | None, validity_start: int, validity_end: int
) -> tuple[int, int]:
    """Convert validity window to slot numbers."""
    validity_start_slot = network_config.posix_to_slot(validity_start)
    validity_end_slot = network_config.posix_to_slot(validity_end)
    return validity_start_slot, validity_end_slot


async def confirm_withdrawal_amount_and_address(
    loaded_key: LoadedKeys,
    reward_token: SomeAsset | NoDatum,
    platform_reward: int,
    network: Network,
    total_transports: int,
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
    print_information(f"Total Rewards transport to proccess: {total_transports}")

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
            "Enter your choice (1-3, q):",
            type=click.Choice(["1", "2", "3", "q"]),  # Add 'q' to choices
            default="1",  # Default to the base address
        )

        if choice == "q":
            click.echo("Exiting.")
            raise DismissRewardCancelledError()
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
                    raise DismissRewardCancelledError()
                try:
                    new_address = Address.from_primitive(new_address_str)
                    return new_address
                except Exception as e:
                    click.echo(
                        f"Invalid Cardano address format: {e}. Please try again."
                    )
