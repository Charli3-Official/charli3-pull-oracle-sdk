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
from charli3_offchain_core.models.oracle_datums import OracleConfiguration
from charli3_offchain_core.oracle.exceptions import ScalingError, StateValidationError
from charli3_offchain_core.oracle.governance.scale_builder import OracleScaleBuilder
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
    """Orchestrator for oracle governance operations"""

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
        oracle_config: OracleConfiguration,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> GovernanceResult:
        """Update oracle settings"""
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

    async def scale_up_oracle(
        self,
        oracle_policy: str,
        scale_amount: int,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> GovernanceResult:
        """Scale up oracle ODV capacity."""
        try:
            utxos = await get_script_utxos(self.script_address, self.tx_manager)
            policy_hash = ScriptHash(bytes.fromhex(oracle_policy))

            builder = OracleScaleBuilder(
                tx_manager=self.tx_manager,
                script_address=self.script_address,
                policy_id=policy_hash,
            )

            try:
                result = await builder.build_scale_up_tx(
                    platform_utxo=platform_utxo,
                    platform_script=platform_script,
                    utxos=utxos,
                    change_address=change_address,
                    signing_key=signing_key,
                    scale_amount=scale_amount,
                    required_signers=required_signers,
                )
            except (ScalingError, StateValidationError) as e:
                logger.info("Scaling error %s", str(e))
                return GovernanceResult(status=ProcessStatus.FAILED)

            if result.transaction is None:
                return GovernanceResult(ProcessStatus.CANCELLED_BY_USER)

            return GovernanceResult(
                status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
            )

        except Exception as e:
            logger.error("Scale up oracle failed: %s", str(e))
            return GovernanceResult(status=ProcessStatus.FAILED, error=e)

    async def scale_down_oracle(
        self,
        oracle_policy: str,
        scale_amount: int,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        required_signers: list[VerificationKeyHash] | None = None,
    ) -> GovernanceResult:
        """Scale down oracle ODV capacity."""
        try:
            utxos = await get_script_utxos(self.script_address, self.tx_manager)
            policy_hash = ScriptHash(bytes.fromhex(oracle_policy))

            builder = OracleScaleBuilder(
                tx_manager=self.tx_manager,
                script_address=self.script_address,
                policy_id=policy_hash,
            )

            try:
                result = await builder.build_scale_down_tx(
                    platform_utxo=platform_utxo,
                    platform_script=platform_script,
                    utxos=utxos,
                    change_address=change_address,
                    signing_key=signing_key,
                    scale_amount=scale_amount,
                    required_signers=required_signers,
                )

            except (ScalingError, StateValidationError):
                return GovernanceResult(status=ProcessStatus.FAILED)

            if result.transaction is None:
                return GovernanceResult(ProcessStatus.CANCELLED_BY_USER)

            return GovernanceResult(
                status=ProcessStatus.TRANSACTION_BUILT, transaction=result.transaction
            )

        except Exception as e:
            logger.error("Scale down oracle failed: %s", str(e))
            return GovernanceResult(status=ProcessStatus.FAILED, error=e)
