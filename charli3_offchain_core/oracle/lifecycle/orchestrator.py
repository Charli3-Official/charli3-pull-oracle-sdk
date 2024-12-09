"""Oracle lifecycle orchestrator with proper datum handling."""

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
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.constants.status import ProcessStatus
from charli3_offchain_core.oracle.exceptions import StateValidationError
from charli3_offchain_core.oracle.utils.asset_checks import validate_token_quantities
from charli3_offchain_core.oracle.utils.state_checks import (
    filter_empty_agg_states,
    filter_empty_transports,
    filter_oracle_settings_utxo,
    filter_reward_accounts,
)

from ..utils.common import get_script_utxos
from .close_builder import CloseBuilder

logger = logging.getLogger(__name__)


@dataclass
class LifecycleResult:
    """Result of lifecycle operation"""

    status: ProcessStatus
    transaction: Transaction | None = None
    error: Exception | None = None


class LifecycleOrchestrator:
    """Orchestrates oracle lifecycle operations with proper datum handling"""

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

    async def _get_oracle_utxos(
        self, oracle_policy: str
    ) -> tuple[UTxO, UTxO | None, list[UTxO], list[UTxO]]:
        """Get oracle UTxOs and filter them based on policy hash."""
        utxos = await self.chain_query.get_utxos(self.script_address)
        logger.info("Found UTxOs count: %d", len(utxos))

        policy_hash = ScriptHash(bytes.fromhex(oracle_policy))
        logger.info("Looking for policy hash: %s", policy_hash)

        settings_utxo = filter_oracle_settings_utxo(utxos, policy_hash)
        if not settings_utxo:
            raise StateValidationError(f"Oracle {oracle_policy} not found")

        if not validate_token_quantities(settings_utxo, {"CoreSettings": 1}):
            raise StateValidationError("Invalid settings token quantities")

        reward_accounts = filter_reward_accounts(utxos)
        reward_transports = filter_empty_transports(utxos)
        agg_states = filter_empty_agg_states(utxos)

        logger.info(
            "Found reward accounts: %d, transports: %d, agg states: %d",
            len(reward_accounts),
            len(reward_transports or []),
            len(agg_states or []),
        )

        return (
            settings_utxo,
            next(iter(reward_accounts), None),
            reward_transports or [],
            agg_states or [],
        )

    async def close_oracle(
        self,
        oracle_policy: str,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
    ) -> LifecycleResult:
        try:
            utxos = await get_script_utxos(self.script_address, self.tx_manager)
            policy_hash = ScriptHash(bytes.fromhex(oracle_policy))

            builder = CloseBuilder(self.chain_query, self.tx_manager)
            result = await builder.build_tx(
                platform_utxo=platform_utxo,
                platform_script=platform_script,
                policy_hash=policy_hash,
                utxos=utxos,
                change_address=change_address,
                signing_key=signing_key,
            )

            return LifecycleResult(
                status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
            )

        except Exception as e:
            logger.error("Close oracle failed: %s", str(e))
            return LifecycleResult(status=ProcessStatus.FAILED, error=e)
