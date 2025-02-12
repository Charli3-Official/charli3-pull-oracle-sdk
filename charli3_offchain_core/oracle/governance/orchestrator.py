"""Oracle governance orchestrator"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pycardano import (
    Address,
    ExtendedSigningKey,
    NativeScript,
    Network,
    PaymentSigningKey,
    ScriptHash,
    Transaction,
    UTxO,
    VerificationKeyHash,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.nodes import NodesConfig
from charli3_offchain_core.cli.config.token import TokenConfig
from charli3_offchain_core.cli.setup import setup_token
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.models.extension_types import PosixTimeDiff
from charli3_offchain_core.models.oracle_datums import OracleConfiguration
from charli3_offchain_core.oracle.exceptions import (
    AddingNodesError,
    AddNodesValidationError,
    RemoveNodesValidationError,
    RemovingNodesError,
)
from charli3_offchain_core.oracle.governance.add_nodes_builder import AddNodesBuilder
from charli3_offchain_core.oracle.governance.del_nodes_builder import DelNodesBuilder
from charli3_offchain_core.oracle.governance.update_builder import UpdateBuilder
from charli3_offchain_core.oracle.utils.common import get_script_utxos

logger = logging.getLogger(__name__)


@dataclass
class GovernanceResult:
    """Result of governance operation"""

    status: ProcessStatus
    transaction: Transaction | None = None
    error: Exception | None = None


class GovernanceOrchestrator:
    def __init__(
        self,
        chain_query: ChainQuery,
        tx_manager: TransactionManager,
        script_address: Address,
        status_callback: Callable | None = None,
    ) -> None:
        self.chain_query = chain_query
        self.tx_manager = tx_manager
        self.script_address = script_address
        self.status_callback = status_callback
        self.current_status = ProcessStatus.NOT_STARTED

    def _update_status(self, status: ProcessStatus, message: str = "") -> None:
        self.current_status = status
        if self.status_callback:
            self.status_callback(status, message)

    async def add_nodes_oracle(
        self,
        oracle_policy: str,
        new_nodes_config: NodesConfig,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> GovernanceResult:
        try:
            utxos = await get_script_utxos(self.script_address, self.tx_manager)
            policy_hash = ScriptHash(bytes.fromhex(oracle_policy))

            builder = AddNodesBuilder(self.chain_query, self.tx_manager)

            try:
                result = await builder.build_tx(
                    platform_utxo=platform_utxo,
                    platform_script=platform_script,
                    policy_hash=policy_hash,
                    utxos=utxos,
                    change_address=change_address,
                    signing_key=signing_key,
                    new_nodes_config=new_nodes_config,
                    required_signers=required_signers,
                )
            except (AddingNodesError, AddNodesValidationError):
                return GovernanceResult(status=ProcessStatus.FAILED)

            if result.reason:
                return GovernanceResult(ProcessStatus.VERIFICATION_FAILURE)

            if result.transaction is None and result.settings_utxo is None:
                return GovernanceResult(ProcessStatus.CANCELLED_BY_USER)

            return GovernanceResult(
                status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
            )

        except Exception as e:
            logger.error("Update oracle failed: %s", str(e))
            return GovernanceResult(status=ProcessStatus.FAILED, error=e)

    async def del_nodes_oracle(
        self,
        oracle_policy: str,
        new_nodes_config: NodesConfig,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        tokens: TokenConfig,
        reward_dismissing_period_length: PosixTimeDiff,
        network: Network,
        reward_issuer_addr: Address | None = None,
        escrow_address: Address | None = None,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> GovernanceResult:
        try:

            auth_policy_id = bytes.fromhex(tokens.platform_auth_policy)

            contract_utxos = await get_script_utxos(
                self.script_address, self.tx_manager
            )
            oracle_policy_hash = ScriptHash(bytes.fromhex(oracle_policy))
            reward_token = setup_token(
                tokens.reward_token_policy, tokens.reward_token_name
            )
            builder = DelNodesBuilder(self.chain_query, self.tx_manager)
            try:
                result = await builder.build_tx(
                    platform_utxo=platform_utxo,
                    platform_script=platform_script,
                    policy_hash=oracle_policy_hash,
                    contract_utxos=contract_utxos,
                    change_address=change_address,
                    signing_key=signing_key,
                    new_nodes_config=new_nodes_config,
                    reward_token=reward_token,
                    network=network,
                    auth_policy_id=auth_policy_id,
                    reward_dismissing_period_length=reward_dismissing_period_length,
                    reward_issuer_addr=reward_issuer_addr,
                    escrow_address=escrow_address,
                    required_signers=required_signers,
                )
            except (RemovingNodesError, RemoveNodesValidationError):
                return GovernanceResult(status=ProcessStatus.FAILED)

            if result.reason:
                return GovernanceResult(ProcessStatus.VERIFICATION_FAILURE)

            if result.transaction is None and result.settings_utxo is None:
                return GovernanceResult(ProcessStatus.CANCELLED_BY_USER)

            return GovernanceResult(
                status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
            )

        except Exception as e:
            logger.error("Update oracle failed: %s", str(e))
            return GovernanceResult(status=ProcessStatus.FAILED, error=e)

    async def update_oracle(
        self,
        oracle_policy: str,
        oracle_config: OracleConfiguration,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> GovernanceResult:
        try:
            utxos = await get_script_utxos(self.script_address, self.tx_manager)
            policy_hash = ScriptHash(bytes.fromhex(oracle_policy))

            builder = UpdateBuilder(self.chain_query, self.tx_manager)

            result = await builder.build_tx(
                oracle_config=oracle_config,
                platform_utxo=platform_utxo,
                platform_script=platform_script,
                policy_hash=policy_hash,
                utxos=utxos,
                change_address=change_address,
                signing_key=signing_key,
                required_signers=required_signers,
            )
            if result.transaction is None and result.settings_utxo is None:
                return GovernanceResult(ProcessStatus.CANCELLED_BY_USER)

            return GovernanceResult(
                status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
            )

        except Exception as e:
            logger.error("Update oracle failed: %s", str(e))
            return GovernanceResult(status=ProcessStatus.FAILED, error=e)
