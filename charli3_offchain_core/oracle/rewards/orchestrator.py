"""Oracle reward orchestrator"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pycardano import (
    Address,
    NativeScript,
    Network,
    ScriptHash,
    Transaction,
    UTxO,
    VerificationKeyHash,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.exceptions import CollateralError
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.base import LoadedKeys
from charli3_offchain_core.cli.config.token import TokenConfig
from charli3_offchain_core.cli.setup import setup_token
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.oracle.exceptions import (
    ADABalanceNotFoundError,
    CollectingNodesError,
    CollectingPlatformError,
    DismissRewardCancelledError,
    NodeCollectCancelled,
    NodeNotRegisteredError,
    NoExpiredTransportsYetError,
    NoPendingTransportsFoundError,
    NoRewardsAvailableError,
    PlatformCollectCancelled,
    RewardsError,
)
from charli3_offchain_core.oracle.rewards.dismiss_rewards_builder import (
    DismissRewardsBuilder,
)
from charli3_offchain_core.oracle.rewards.node_collect_builder import (
    NodeCollectBuilder,
)
from charli3_offchain_core.oracle.rewards.platform_collect_builder import (
    PlatformCollectBuilder,
)

# from charli3_offchain_core.oracle.rewards.platform_collect_builder import PlatformCollectBuilder
from charli3_offchain_core.oracle.utils.common import get_script_utxos

logger = logging.getLogger(__name__)


@dataclass
class RewardOrchestratorResult:
    """Result of reward operation"""

    status: ProcessStatus
    transaction: Transaction | None = None
    error: RewardsError | CollateralError | None = None


class RewardOrchestrator:
    def __init__(
        self,
        chain_query: ChainQuery,
        tx_manager: TransactionManager,
        script_address: Address | str,
        status_callback: Callable | None = None,
    ) -> None:
        self.chain_query = chain_query
        self.tx_manager = tx_manager
        self.script_address = (
            Address.from_primitive(script_address)
            if isinstance(script_address, str)
            else script_address
        )
        self.status_callback = status_callback
        self.current_status = ProcessStatus.NOT_STARTED

    def _update_status(self, status: ProcessStatus, message: str = "") -> None:
        self.current_status = status
        if self.status_callback:
            self.status_callback(status, message)

    async def collect_node_oracle(
        self,
        oracle_policy: str | None,
        tokens: TokenConfig,
        loaded_key: LoadedKeys,
        network: Network,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> RewardOrchestratorResult:
        if not oracle_policy:
            raise ValueError("oracle_policy cannot be None or empty")

        # Contract UTxOs
        contract_utxos = await get_script_utxos(self.script_address, self.tx_manager)

        oracle_policy_hash = ScriptHash(bytes.fromhex(oracle_policy))
        reward_token = setup_token(tokens.reward_token_policy, tokens.reward_token_name)

        builder = NodeCollectBuilder(self.chain_query, self.tx_manager)

        result = await builder.build_tx(
            policy_hash=oracle_policy_hash,
            contract_utxos=contract_utxos,
            reward_token=reward_token,
            loaded_key=loaded_key,
            network=network,
            required_signers=required_signers,
        )

        if isinstance(result.exception_type, NodeNotRegisteredError):
            return RewardOrchestratorResult(
                status=ProcessStatus.VERIFICATION_FAILURE,
                error=result.exception_type,
            )

        if isinstance(result.exception_type, NoRewardsAvailableError):
            return RewardOrchestratorResult(
                status=ProcessStatus.COMPLETED, error=result.exception_type
            )

        if isinstance(result.exception_type, NodeCollectCancelled):
            return RewardOrchestratorResult(
                status=ProcessStatus.CANCELLED_BY_USER, error=result.exception_type
            )

        if isinstance(result.exception_type, ADABalanceNotFoundError | CollateralError):
            return RewardOrchestratorResult(
                status=ProcessStatus.FAILED, error=result.exception_type
            )

        if isinstance(result.exception_type, CollectingNodesError):
            return RewardOrchestratorResult(
                status=ProcessStatus.FAILED, error=result.exception_type
            )

        return RewardOrchestratorResult(
            status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
        )

    async def collect_platform_oracle(
        self,
        oracle_policy: str | None,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        tokens: TokenConfig,
        loaded_key: LoadedKeys,
        network: Network,
        max_inputs: int = 10,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> RewardOrchestratorResult:
        if not oracle_policy:
            raise ValueError("oracle_policy cannot be None or empty")

        # Contract UTxOs
        contract_utxos = await get_script_utxos(self.script_address, self.tx_manager)

        oracle_policy_hash = ScriptHash(bytes.fromhex(oracle_policy))
        reward_token = setup_token(tokens.reward_token_policy, tokens.reward_token_name)

        builder = PlatformCollectBuilder(self.chain_query, self.tx_manager)

        result = await builder.build_tx(
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            policy_hash=oracle_policy_hash,
            contract_utxos=contract_utxos,
            reward_token=reward_token,
            loaded_key=loaded_key,
            network=network,
            max_inputs=max_inputs,
            required_signers=required_signers,
        )

        if isinstance(result.exception_type, CollectingPlatformError):
            return RewardOrchestratorResult(
                status=ProcessStatus.FAILED, error=result.exception_type
            )

        if isinstance(result.exception_type, NoRewardsAvailableError):
            return RewardOrchestratorResult(
                status=ProcessStatus.COMPLETED, error=result.exception_type
            )

        if isinstance(result.exception_type, PlatformCollectCancelled):
            return RewardOrchestratorResult(
                status=ProcessStatus.CANCELLED_BY_USER, error=result.exception_type
            )

        if isinstance(result.exception_type, CollateralError):
            return RewardOrchestratorResult(
                status=ProcessStatus.FAILED, error=result.exception_type
            )
        return RewardOrchestratorResult(
            status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
        )

    async def dismiss_rewards(
        self,
        oracle_policy: str | None,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        tokens: TokenConfig,
        loaded_key: LoadedKeys,
        network: Network,
        reward_dismission_period_length: int,
        max_inputs: int = 10,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> RewardOrchestratorResult:

        if not oracle_policy:
            raise ValueError("oracle_policy cannot be None or empty")

        # Contract UTxOs
        contract_utxos = await get_script_utxos(self.script_address, self.tx_manager)

        oracle_policy_hash = ScriptHash(bytes.fromhex(oracle_policy))
        reward_token = setup_token(tokens.reward_token_policy, tokens.reward_token_name)

        builder = DismissRewardsBuilder(self.chain_query, self.tx_manager)

        result = await builder.build_tx(
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            policy_hash=oracle_policy_hash,
            contract_utxos=contract_utxos,
            reward_token=reward_token,
            loaded_key=loaded_key,
            network=network,
            reward_dismission_period_length=reward_dismission_period_length,
            max_inputs=max_inputs,
            required_signers=required_signers,
        )

        if isinstance(result.exception_type, NoExpiredTransportsYetError):
            return RewardOrchestratorResult(
                status=ProcessStatus.COMPLETED, error=result.exception_type
            )

        if isinstance(result.exception_type, NoPendingTransportsFoundError):
            return RewardOrchestratorResult(
                status=ProcessStatus.COMPLETED, error=result.exception_type
            )

        if isinstance(result.exception_type, DismissRewardCancelledError):
            return RewardOrchestratorResult(
                status=ProcessStatus.CANCELLED_BY_USER, error=result.exception_type
            )

        if isinstance(result.exception_type, NoRewardsAvailableError):
            return RewardOrchestratorResult(
                status=ProcessStatus.COMPLETED, error=result.exception_type
            )

        return RewardOrchestratorResult(
            status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
        )
