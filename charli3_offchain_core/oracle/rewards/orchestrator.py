"""Oracle reward orchestrator"""

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
from charli3_offchain_core.cli.config.token import TokenConfig
from charli3_offchain_core.cli.setup import setup_token
from charli3_offchain_core.constants.status import ProcessStatus
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
class RewardResult:
    """Result of reward operation"""

    status: ProcessStatus
    transaction: Transaction | None = None
    error: Exception | None = None


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
        user_address: Address | str,
        tokens: TokenConfig,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        network: Network,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> RewardResult:
        try:
            if not oracle_policy:
                raise ValueError("oracle_policy cannot be None or empty")

            validated_user_address = (
                Address.from_primitive(user_address)
                if isinstance(user_address, str)
                else user_address
            )

            # Contract UTxOs
            contract_utxos = await get_script_utxos(
                self.script_address, self.tx_manager
            )

            oracle_policy_hash = ScriptHash(bytes.fromhex(oracle_policy))
            reward_token = setup_token(
                tokens.reward_token_policy, tokens.reward_token_name
            )

            builder = NodeCollectBuilder(self.chain_query, self.tx_manager)

            result = await builder.build_tx(
                policy_hash=oracle_policy_hash,
                contract_utxos=contract_utxos,
                user_address=validated_user_address,
                reward_token=reward_token,
                network=network,
                signing_key=signing_key,
                required_signers=required_signers,
            )

            if result.transaction is None and result.reward_utxo is None:
                return RewardResult(ProcessStatus.CANCELLED_BY_USER)

            return RewardResult(
                status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
            )

        except Exception as e:
            logger.error("Collect Node failed: %s", str(e))
            return RewardResult(status=ProcessStatus.FAILED, error=e)

    async def collect_platform_oracle(
        self,
        oracle_policy: str | None,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        user_address: Address | str,
        tokens: TokenConfig,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        network: Network,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> RewardResult:
        try:
            if not oracle_policy:
                raise ValueError("oracle_policy cannot be None or empty")

            validated_user_address = (
                Address.from_primitive(user_address)
                if isinstance(user_address, str)
                else user_address
            )

            # Contract UTxOs
            contract_utxos = await get_script_utxos(
                self.script_address, self.tx_manager
            )

            oracle_policy_hash = ScriptHash(bytes.fromhex(oracle_policy))
            reward_token = setup_token(
                tokens.reward_token_policy, tokens.reward_token_name
            )

            builder = PlatformCollectBuilder(self.chain_query, self.tx_manager)

            result = await builder.build_tx(
                platform_utxo=platform_utxo,
                platform_script=platform_script,
                policy_hash=oracle_policy_hash,
                contract_utxos=contract_utxos,
                user_address=validated_user_address,
                reward_token=reward_token,
                network=network,
                signing_key=signing_key,
                required_signers=required_signers,
            )

            if result.transaction is None and result.reward_utxo is None:
                return RewardResult(ProcessStatus.CANCELLED_BY_USER)

            return RewardResult(
                status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
            )

        except Exception as e:
            logger.error("Collect Platform failed: %s", str(e))
            return RewardResult(status=ProcessStatus.FAILED, error=e)
