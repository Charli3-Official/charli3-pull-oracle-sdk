"""Orchestrates the platform authorization NFT creation process."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from pycardano import Address, PaymentSigningKey, Transaction, VerificationKeyHash

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager

from .token_builder import PlatformAuthBuilder
from .token_script_builder import PlatformAuthScript, ScriptConfig

logger = logging.getLogger(__name__)


class AuthStatus(str, Enum):
    """Status of platform authorization process"""

    NOT_STARTED = "not_started"
    CREATING_SCRIPT = "creating_script"
    BUILDING_TRANSACTION = "building_transaction"
    SUBMITTING_TRANSACTION = "submitting_transaction"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AuthResult:
    """Result of platform authorization process"""

    status: AuthStatus
    transaction: Transaction | None = None
    policy_id: bytes | None = None
    platform_address: Address | None = None
    error: Exception | None = None


class PlatformAuthOrchestrator:
    """Coordinates the platform authorization NFT creation process."""

    def __init__(
        self,
        chain_query: ChainQuery,
        tx_manager: TransactionManager,
        status_callback: Callable[[AuthStatus, str], None] | None = None,
    ) -> None:
        self.chain_query = chain_query
        self.tx_manager = tx_manager
        self.status_callback = status_callback
        self.current_status = AuthStatus.NOT_STARTED

    def _update_status(self, status: AuthStatus, message: str = "") -> None:
        """Update process status and notify callback."""
        self.current_status = status
        if self.status_callback:
            self.status_callback(status, message)
        logger.info("Auth status: %s - %s", status, message)

    async def create_platform_auth(
        self,
        sender_address: Address,
        signing_key: PaymentSigningKey,
        multisig_threshold: int,
        multisig_parties: list[str],
        metadata: dict | None = None,
        network: str | None = None,
        is_mock: bool = False,
    ) -> AuthResult:
        """Create platform authorization NFT."""
        try:
            # Create script config
            script_config = ScriptConfig(
                signers=[
                    VerificationKeyHash.from_primitive(pkh) for pkh in multisig_parties
                ],
                threshold=multisig_threshold,
                network=network,
            )

            self._update_status(AuthStatus.CREATING_SCRIPT)
            script_builder = PlatformAuthScript(
                chain_query=self.chain_query, config=script_config, is_mock=is_mock
            )

            self._update_status(AuthStatus.BUILDING_TRANSACTION)
            token_builder = PlatformAuthBuilder(
                self.chain_query, self.tx_manager, script_builder
            )

            result = await token_builder.build_auth_transaction(
                sender_address=sender_address,
                signing_key=signing_key,
                metadata=metadata,
            )

            self._update_status(AuthStatus.SUBMITTING_TRANSACTION)
            await self.tx_manager.sign_and_submit(result.transaction, [signing_key])

            self._update_status(AuthStatus.COMPLETED)
            return AuthResult(
                status=AuthStatus.COMPLETED,
                transaction=result.transaction,
                policy_id=result.policy_id,
                platform_address=result.platform_address,
            )

        except Exception as e:
            logger.error("Platform auth creation failed: %s", str(e))
            self._update_status(AuthStatus.FAILED, str(e))
            return AuthResult(status=AuthStatus.FAILED, error=e)
