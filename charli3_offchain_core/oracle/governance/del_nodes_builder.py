"""Del Nodes transaction builder. """

import logging
from copy import deepcopy
from dataclasses import dataclass, replace

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
from tabulate import tabulate

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.network import NetworkConfig
from charli3_offchain_core.cli.config.formatting import (
    CliColor,
    print_confirmation_message_prompt,
    print_header,
    print_information,
    print_title,
)
from charli3_offchain_core.cli.config.nodes import NodesConfig
from charli3_offchain_core.models.base import PosixTimeDiff
from charli3_offchain_core.models.oracle_datums import (
    NoDatum,
    Nodes,
    OracleSettingsDatum,
    OracleSettingsVariant,
    PolicyId,
    RewardAccountDatum,
    RewardAccountVariant,
    SomeAsset,
)
from charli3_offchain_core.models.oracle_redeemers import (
    DelNodes,
)
from charli3_offchain_core.models.reward_escrow import (
    PlutusFullAddress,
    RewardEscrowDatum,
)
from charli3_offchain_core.oracle.exceptions import (
    RemoveNodesCancelled,
    RemoveNodesValidationError,
    RemovingNodesError,
)
from charli3_offchain_core.oracle.utils.common import (
    get_reference_script_utxo,
)
from charli3_offchain_core.oracle.utils.state_checks import (
    get_oracle_settings_by_policy_id,
    get_reward_account_by_policy_id,
)

from .base import BaseBuilder, GovernanceTxResult

logger = logging.getLogger(__name__)


@dataclass
class ValidityWindow:
    """Represents the validity window for a transaction."""

    start_slot: int | None = None
    end_slot: int | None = None
    current_time: int | None = None


class DelNodesBuilder(BaseBuilder):
    FEE_BUFFER = 10_000

    async def build_tx(
        self,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        policy_hash: ScriptHash,
        contract_utxos: list[UTxO],
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        new_nodes_config: NodesConfig,
        reward_token: NoDatum | SomeAsset,
        network: Network,
        auth_policy_id: PolicyId,
        reward_dismissing_period_length: PosixTimeDiff,
        reward_issuer_addr: Address | None = None,
        escrow_address: Address | None = None,
        required_signers: list[VerificationKeyHash] | None = None,
        test_mode: bool = False,
    ) -> GovernanceTxResult:
        """Builds a governance transaction for updating node configurations.

        This method constructs a transaction that updates the node configuration on the platform.
        It handles the creation of outputs, validation of inputs, and proper signing of the transaction.

        Args:
            platform_utxo: UTxO containing the platform's assets and datum
            platform_script: Native script that controls the platform's spending conditions
            policy_hash: Hash of the policy ID used for minting/burning tokens
            contract_utxos: List of UTxOs associated with the contract
            change_address: Address where any remaining assets will be sent
            signing_key: Key used to sign the transaction (can be payment or extended)
            new_nodes_config: New configuration for the nodes being updated
            reward_token: Token used for rewards, can be NoDatum or a specific asset
            network: Network configuration (testnet/mainnet) for the transaction
            auth_policy_id: Policy ID used for authorization validation
            reward_dismissing_period_length: Time period after which rewards can be dismissed
            reward_issuer_addr: Optional address authorized to issue rewards
            escrow_address: Optional address for holding funds in escrow
            required_signers: Optional list of additional verification key hashes required to sign

        Returns:
            GovernanceTxResult: Object containing the built transaction and related metadata

        Raises:
            ValueError: If any required parameters are invalid or missing
            RemoveNodesValidationError: If the new configuration fails validation rules
            RemoveNodesCancelled: If the transaction building process is cancelled
            TransactionBuildError: If there's an error during transaction construction

        Note:
            The transaction requires proper authorization and will fail if the signing key
            doesn't have the necessary permissions.
        """
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

            # Nodes to remove
            nodes_to_remove = {node.payment_vkh for node in new_nodes_config.nodes}

            # Compute the PKh that should receive a payment
            # and calculate the total sum of all payments
            payment_distribution, total_amount = reward_distribution(
                nodes_to_remove,
                in_core_datum,
                in_reward_account_datum,
            )

            # Modified Core Settings: removed `Nodes`
            out_core_utxo = modified_core_utxo(
                in_core_utxo,
                in_core_datum,
                nodes_to_remove,
                new_nodes_config.required_signatures,
            )

            # Modified Reward Account: removed payment amounts
            out_reward_account_utxo = modified_reward_utxo(
                in_reward_account_utxo,
                in_reward_account_datum,
                nodes_to_remove,
                in_core_datum,
                total_amount,
                reward_token,
            )

            # Creation of node UTxOs if payments are available
            node_operator_rewards, validity_window = (
                self.node_operator_reward_distribution(
                    payment_distribution,
                    reward_token,
                    escrow_address,
                    reward_issuer_addr,
                    auth_policy_id,
                    reward_dismissing_period_length,
                    in_core_datum.time_uncertainty_platform,
                    network=network,
                )
            )

            # Confirmation of changes
            confirm_node_updates(
                in_core_datum,
                out_core_utxo.output.datum.datum,
                nodes_to_remove,
                payment_distribution,
                reward_token,
                self.MIN_UTXO_VALUE,
                test_mode,
            )

            # Build the transaction
            tx = await self.tx_manager.build_script_tx(
                script_inputs=[
                    (in_reward_account_utxo, Redeemer(DelNodes()), script_utxo),
                    (in_core_utxo, Redeemer(DelNodes()), script_utxo),
                    (platform_utxo, None, platform_script),
                ],
                script_outputs=[
                    out_core_utxo.output,
                    out_reward_account_utxo.output,
                    platform_utxo.output,
                    *node_operator_rewards,
                ],
                fee_buffer=self.FEE_BUFFER,
                change_address=change_address,
                signing_key=signing_key,
                validity_start=validity_window.start_slot,
                validity_end=validity_window.end_slot,
                required_signers=required_signers,
            )
            return GovernanceTxResult(
                transaction=tx, settings_utxo=out_core_utxo.output
            )

        except RemoveNodesValidationError as e:
            error_msg = f"Failed to validate Delete Nodes rules: {e}"
            logger.error(error_msg)
            return GovernanceTxResult(reason=error_msg)

        except RemovingNodesError as e:
            error_msg = (
                f"Provided inputs do not account for payment rewards processing: {e}"
            )
            logger.info(error_msg)
            return GovernanceTxResult(reason=error_msg)

        except (RemoveNodesCancelled, click.Abort):
            logger.info("Operation cancelled")
            return GovernanceTxResult()

        except Exception as e:
            error_msg = f"Unexpected error building delete nodes transaction: {e}"
            logger.error(error_msg)
            raise e

    def node_operator_reward_distribution(
        self,
        payment_distribution: dict[VerificationKeyHash, int],
        reward_token: NoDatum | SomeAsset,
        escrow_address: Address | None,
        reward_issuer_addr: Address | None,
        auth_policy_id: PolicyId,
        reward_dismissing_period_length: PosixTimeDiff,
        time_uncertainty_platform: PosixTimeDiff,
        network: Network,
    ) -> tuple[list[TransactionOutput], ValidityWindow]:

        # Direct payment distribution
        if isinstance(reward_token, NoDatum):
            return (
                self._create_direct_payments(payment_distribution, network),
                ValidityWindow(),
            )

        validity_window = self._calculate_validity_window(time_uncertainty_platform)

        # Escrow payment distribution
        return (
            self._create_escrow_payments(
                payment_distribution=payment_distribution,
                reward_token=reward_token,
                escrow_address=escrow_address,
                reward_issuer_addr=reward_issuer_addr,
                auth_policy_id=auth_policy_id,
                reward_dismissing_period_length=reward_dismissing_period_length,
                validity_window=validity_window,
            ),
            validity_window,
        )

    def _create_direct_payments(
        self,
        payment_distribution: dict[VerificationKeyHash, int],
        network: Network,
    ) -> list[TransactionOutput]:
        """Create direct payment outputs for node operators."""
        return [
            TransactionOutput(
                address=Address(payment_part=node_id, network=network),
                amount=Value(coin=max(reward, self.MIN_UTXO_VALUE)),
            )
            for node_id, reward in payment_distribution.items()
            if reward > 0
        ]

    def _create_escrow_payments(
        self,
        payment_distribution: dict[VerificationKeyHash, int],
        reward_token: SomeAsset,
        escrow_address: Address,
        reward_issuer_addr: Address,
        auth_policy_id: PolicyId,
        reward_dismissing_period_length: int,
        validity_window: ValidityWindow,
    ) -> list[TransactionOutput]:
        """Create escrow payment outputs for node operators."""

        rewards: list[TransactionOutput] = []

        if reward_issuer_addr is None:
            raise ValueError("Reward issuer address cannot be None")

        for node_id, reward in payment_distribution.items():
            if reward <= 0:
                continue

            payment_asset = MultiAsset.from_primitive(
                {reward_token.asset.policy_id: {reward_token.asset.name: reward}}
            )

            datum = RewardEscrowDatum(
                reward_issuer_nft=auth_policy_id,
                reward_issuer_address=PlutusFullAddress.from_address(
                    reward_issuer_addr
                ),
                reward_receiver=node_id.to_primitive(),
                escrow_expiration_timestamp=validity_window.current_time
                + reward_dismissing_period_length,
            )

            rewards.append(
                TransactionOutput(
                    address=escrow_address,
                    amount=Value(coin=self.MIN_UTXO_VALUE, multi_asset=payment_asset),
                    datum_hash=None,
                    datum=datum,
                )
            )

        return rewards

    def _calculate_validity_window(
        self,
        time_uncertainty_platform: PosixTimeDiff,
    ) -> ValidityWindow:
        """Calculate the validity window for transactions."""
        start, end, current = calculate_validity_window(
            self.tx_manager.chain_query,
            time_uncertainty_platform,
        )

        start_slot, end_slot = validity_window_to_slot(
            self.tx_manager.chain_query.config.network_config,
            start,
            end,
        )

        return ValidityWindow(
            start_slot=start_slot, end_slot=end_slot, current_time=current
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


def modified_core_utxo(
    core_utxo: UTxO,
    core_datum: OracleSettingsDatum,
    nodes_to_remove: set[VerificationKeyHash],
    required_signatures: int,
) -> UTxO:
    modified_utxo = deepcopy(core_utxo)

    filtered_nodes = {
        feed: payment
        for feed, payment in core_datum.nodes.node_map.items()
        if payment not in nodes_to_remove
    }

    new_datum = replace(
        core_datum,
        nodes=Nodes(node_map=filtered_nodes),
        required_node_signatures_count=required_signatures,
    )

    modified_utxo = replace(
        modified_utxo,
        output=replace(
            modified_utxo.output,
            datum=OracleSettingsVariant(new_datum),
            datum_hash=None,
        ),
    )

    return modified_utxo


def modified_reward_utxo(
    reward_utxo: UTxO,
    reward_datum: RewardAccountDatum,
    nodes_to_remove: set[VerificationKeyHash],
    core_datum: OracleSettingsDatum,
    payment_amount: int,
    reward_token: NoDatum | SomeAsset,
) -> UTxO | None:
    modified_utxo = deepcopy(reward_utxo)

    existing_nodes = list(core_datum.nodes.node_map.values())

    # Create initial distribution mapping
    distribution: dict[VerificationKeyHash, int] = dict(
        zip(existing_nodes, reward_datum.nodes_to_rewards)
    )

    # Filter and sort distribution
    filtered_distribution = {
        node_pkh: reward
        for node_pkh, reward in distribution.items()
        if node_pkh not in nodes_to_remove
    }

    new_datum = RewardAccountDatum(
        nodes_to_rewards=list(filtered_distribution.values())
    )

    modified_utxo.output.datum = RewardAccountVariant(new_datum)
    modified_utxo.output.datum_hash = None

    if isinstance(reward_token, NoDatum):

        if modified_utxo.output.amount.coin < payment_amount:
            raise RemovingNodesError("Insufficient ADA funds for payment")

        modified_utxo.output.amount.coin -= payment_amount
        return modified_utxo

    multi_asset = modified_utxo.output.amount.multi_asset

    asset_name_bytes = reward_token.asset.name
    asset_name = AssetName(asset_name_bytes)

    policy_id_bytes = reward_token.asset.policy_id
    policy_id = ScriptHash.from_primitive(policy_id_bytes.hex())
    token_balance = multi_asset.get(policy_id, {}).get(asset_name, 0)

    # Check if payment token exists and covers withdrawal amount
    if token_balance <= 0 or token_balance < payment_amount:
        raise RemovingNodesError(
            "Insufficient funds in the payment token to complete the transaction. "
            f"token balance {token_balance} "
            f"payment amount {payment_amount}"
        )

    multi_asset[policy_id][asset_name] -= payment_amount
    modified_utxo.output.amount.multi_asset = multi_asset
    return modified_utxo


def print_nodes_table(
    node_map: dict[VerificationKeyHash, VerificationKeyHash],
    payment_distribution: dict[VerificationKeyHash, int],
    min_utxo_value: int,
    success: bool = True,
    is_ada: bool = True,
    is_current: bool = True,
) -> None:
    """Print nodes in a formatted table with improved headers."""
    color = CliColor.SUCCESS if success else CliColor.ERROR

    title = "NODES TO REMOVE" if is_current else "NODES REMOVED VS REMAINING"

    print_title(title)

    subtitle = (
        "Rewards distributed in ₳ (lovelace) with minimum UTxO validation"
        if is_ada
        else "Rewards distributed in CNT through escrow contract"
    )
    display_payment_method(subtitle)
    headers = [
        "Node #",
        "Feed Verification Key Hash",
        "Payment Verification Key Hash",
        "Reward Amount",
    ]
    table_data = [
        [
            f"{i}",
            feed_vkh,
            payment_vkh,
            payment_distribution.get(payment_vkh, 0),
        ]
        for i, (feed_vkh, payment_vkh) in enumerate(node_map.items(), 1)
    ]

    if is_ada:
        for row in table_data:
            reward = row[3]  # Get the reward amount
            if reward > 0 and reward < min_utxo_value:
                row[3] = (
                    f"Original: {reward:_} ₳, "
                    f"Final (Min UTxO): {min_utxo_value:r_} ₳"
                )
            else:
                row[3] = f"{reward:_} ₳ "

    table = tabulate(
        table_data,
        headers=headers,
        tablefmt="rst",
        stralign="center",
        numalign="center",
    )
    click.secho(table, fg=color)


def print_required_signatories(count: int, is_current: bool = True) -> None:
    """Print required signatories information with improved formatting."""
    status = "Current" if is_current else "New"
    message = f"{status} Required Signatures: {count}"
    click.secho(f"\n{message}", fg=CliColor.NEUTRAL, bold=True)


def print_validation_rules(
    new_node_count: int,
    new_signatures_count: int,
    has_deleted_nodes: bool,
    has_added_nodes: bool,
    has_all_nodes: bool,
) -> bool:
    """Print validation rules and their current status."""
    rules = [
        {
            "rule": "Must not break multisig requirements",
            "status": new_signatures_count > 0
            and new_signatures_count <= new_node_count,
            "details": (
                f"Required signatures ({new_signatures_count}) must be greater than 0 "
                f"and not exceed total nodes ({new_node_count})"
            ),
        },
        {
            "rule": "Must not add nodes",
            "status": not has_added_nodes,
            "details": "No existing nodes can be removed in this operation",
        },
        {
            "rule": "Must remove at least one node",
            "status": has_deleted_nodes,
            "details": "At least one new node must be added",
        },
        {
            "rule": "All removed nodes must exist",
            "status": has_all_nodes,
            "details": "All configured nodes must exist in the current configuration",
        },
    ]

    all_rules_pass = True

    print_header("Validation Rules")
    for rule in rules:
        status_color = CliColor.SUCCESS if rule["status"] else CliColor.ERROR
        status_symbol = "✓" if rule["status"] else "✗"
        click.secho(f"{status_symbol} {rule['rule']}", fg=status_color)
        print_information(f"   {rule['details']}")

        all_rules_pass = all_rules_pass and rule["status"]

    return all_rules_pass


def show_nodes_update_info(
    in_core_datum: OracleSettingsDatum,
    out_core_datum: OracleSettingsDatum,
    config_nodes_to_remove: set[VerificationKeyHash],
    payment_distribution: dict[VerificationKeyHash, int],
    reward_token: NoDatum | SomeAsset,
    min_utxo_value: int,
    test_mode: bool = False,
) -> bool:
    """
    Displays information about the changes that will be made to the nodes.

    Returns:
        bool: True if changes are valid and should proceed, False otherwise
    """

    nodes_to_remove = get_remove_nodes(in_core_datum, out_core_datum)
    added_nodes = get_added_nodes(in_core_datum, out_core_datum)

    current_signatures = in_core_datum.required_node_signatures_count
    new_signatures_count = out_core_datum.required_node_signatures_count
    signatures_changed = current_signatures != new_signatures_count

    # Handle cases where there are no actual changes
    if not (nodes_to_remove or signatures_changed):
        click.secho("\nNo changes detected", fg=CliColor.NEUTRAL, bold=True)
        click.secho("\n")
        return False

    # Display changes
    if nodes_to_remove and not test_mode:
        click.secho("\n", nl=True)
        print_nodes_table(
            nodes_to_remove,
            payment_distribution,
            min_utxo_value,
            is_current=True,
            is_ada=isinstance(reward_token, NoDatum),
        )

    if signatures_changed:
        print_required_signatories(new_signatures_count, is_current=False)
        display_signature_change(current_signatures, new_signatures_count)

    has_valid_nodes = all_valid_nodes(
        config_nodes_to_remove, in_core_datum.nodes.node_map
    )

    # Validate and return result
    return print_validation_rules(
        new_node_count=out_core_datum.nodes.length,
        new_signatures_count=new_signatures_count,
        has_deleted_nodes=bool(nodes_to_remove),
        has_added_nodes=bool(added_nodes),
        has_all_nodes=has_valid_nodes,
    )


def get_added_nodes(
    in_datum: OracleSettingsDatum, out_datum: OracleSettingsDatum
) -> dict:
    """Calculate nodes that have been added.

    Returns a dict mapping feed VKH to payment VKH for nodes present in out_datum
    but not in in_datum (i.e., newly added nodes).
    """
    added_feed_vkhs = set(out_datum.nodes.node_map) - set(in_datum.nodes.node_map)
    return {
        feed_vkh: out_datum.nodes.node_map[feed_vkh] for feed_vkh in added_feed_vkhs
    }


def get_remove_nodes(
    in_datum: OracleSettingsDatum, out_datum: OracleSettingsDatum
) -> dict:
    """Calculate nodes that will be removed.

    Returns a dict mapping feed VKH to payment VKH for nodes present in in_datum
    but not in out_datum (i.e., nodes being removed).
    """
    removed_feed_vkhs = set(in_datum.nodes.node_map) - set(out_datum.nodes.node_map)
    return {
        feed_vkh: in_datum.nodes.node_map[feed_vkh] for feed_vkh in removed_feed_vkhs
    }


def all_valid_nodes(
    nodes_to_remove: set[VerificationKeyHash],
    in_nodes: dict[VerificationKeyHash, VerificationKeyHash],
) -> bool:
    """Verify that all nodes marked for removal exist in the current contract"""
    return all(node in in_nodes.values() for node in nodes_to_remove)


def display_signature_change(current: int, new: int) -> None:
    """Display signature requirement changes."""
    click.secho(
        f"\nSignature requirement will change from {current} to {new}",
        fg=CliColor.WARNING if new < current else CliColor.SUCCESS,
        bold=True,
    )


def display_payment_method(text: str) -> None:
    """Display signature requirement changes."""
    click.secho(
        f"\n{text}",
        fg="red",
        bold=True,
    )


def confirm_node_updates(
    in_core_datum: OracleSettingsDatum,
    out_core_datum: OracleSettingsDatum,
    nodes_to_remove: set[VerificationKeyHash],
    payment_distribution: dict[VerificationKeyHash, int],
    reward_token: NoDatum | SomeAsset,
    min_utxo_value: int,
    test_mode: bool = False,
) -> bool:
    """
    Validate and confirm node updates with the user.

    Args:
        in_core_datum: Current oracle settings
        out_core_datum: Proposed oracle settings
        nodes_to_remove: Nodes to be removed, as specified by the user
    Returns:
        bool: True if changes are valid and confirmed, False otherwise

    Raises:
        UpdateCancelled: If the user cancels the update or validation fails
    """
    # Validate and display changes
    changes_valid = show_nodes_update_info(
        in_core_datum,
        out_core_datum,
        nodes_to_remove,
        payment_distribution,
        reward_token,
        min_utxo_value,
        test_mode,
    )
    if not changes_valid:
        logger.warning("Validation failed for delete nodes")
        raise RemoveNodesValidationError("Removing nodes validation failed")

    # Get user confirmation
    if not test_mode and not print_confirmation_message_prompt(
        "Do you want to continue with the detected changes?"
    ):
        logger.info("User cancelled operation: Delete Nodes")
        raise RemoveNodesCancelled("Update cancelled by user")

    return True


def reward_distribution(
    nodes_to_remove: set[VerificationKeyHash],
    core_datum: OracleSettingsDatum,
    reward_datum: RewardAccountDatum,
) -> tuple[dict[VerificationKeyHash, int], int]:

    existing_nodes = list(core_datum.nodes.node_map.values())

    # Create initial distribution mapping
    distribution = dict(zip(existing_nodes, reward_datum.nodes_to_rewards))

    # Filter and sort distribution
    filtered_distribution = {
        node_pkh: reward
        for node_pkh, reward in distribution.items()
        if node_pkh in nodes_to_remove
    }

    total_amount = sum(filtered_distribution.values())
    return (filtered_distribution, total_amount)
