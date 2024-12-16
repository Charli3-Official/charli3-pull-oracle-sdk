"""Oracle governance orchestrato"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pycardano import (
    Address,
    ExtendedSigningKey,
    NativeScript,
    PaymentSigningKey,
    ScriptHash,
    Transaction,
    UTxO,
    VerificationKeyHash,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.constants.status import ProcessStatus
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

    async def update_oracle(
        self,
        oracle_policy: str,
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
