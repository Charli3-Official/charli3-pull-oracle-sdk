"""Orchestrates the oracle deployment process including reference scripts and start transaction."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pycardano import (
    Address,
    ExtendedSigningKey,
    NativeScript,
    PaymentSigningKey,
    UTxO,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.nodes import NodesConfig
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import (
    Asset,
    FeeConfig,
    NoDatum,
    OracleConfiguration,
)
from charli3_offchain_core.oracle.config import (
    OracleDeploymentConfig,
    OracleScriptConfig,
)
from charli3_offchain_core.oracle.deployment.oracle_start_builder import (
    OracleStartBuilder,
    StartTransactionResult,
)
from charli3_offchain_core.oracle.deployment.reference_script_builder import (
    ReferenceScriptBuilder,
    ReferenceScriptResult,
)

from ...constants.status import ProcessStatus

logger = logging.getLogger(__name__)


@dataclass
class DeploymentResult:
    """Result of oracle deployment"""

    status: ProcessStatus
    error: Exception | None = None
    reference_scripts: ReferenceScriptResult | None = None
    start_result: StartTransactionResult | None = None


class OracleDeploymentOrchestrator:
    """Coordinates the oracle deployment process."""

    def __init__(
        self,
        chain_query: ChainQuery,
        contracts: OracleContracts,
        tx_manager: TransactionManager,
        status_callback: Callable[[ProcessStatus, str], None] | None = None,
    ) -> None:
        """Initialize the deployment orchestrator.

        Args:
            chain_query: Chain query interface
            contracts: Oracle contract loader
            tx_manager: Transaction manager
            status_callback: Optional callback for status updates
        """
        self.chain_query = chain_query
        self.contracts = contracts
        self.tx_manager = tx_manager
        self.status_callback = status_callback

        # Initialize builders
        self.reference_builder = ReferenceScriptBuilder(
            chain_query, contracts, tx_manager
        )
        self.start_builder = OracleStartBuilder(chain_query, contracts, tx_manager)

        # Track deployment state
        self.current_status = ProcessStatus.NOT_STARTED

    def _update_status(self, status: ProcessStatus, message: str = "") -> None:
        """Update deployment status and notify callback."""
        self.current_status = status
        if self.status_callback:
            self.status_callback(status, message)
        # logger.info("Deployment status: %s - %s", status, message)

    async def build_tx(
        self,
        # Network, platform and admin configuration
        platform_auth_policy_id: bytes,
        fee_token: Asset | NoDatum,
        platform_script: NativeScript,
        admin_address: Address,
        script_address: Address,
        # Timing configuration
        closing_period_length: int,
        reward_dismissing_period_length: int,
        aggregation_liveness_period: int,
        time_absolute_uncertainty: int,
        iqr_fence_multiplier: int,
        # Deployment configuration
        deployment_config: OracleDeploymentConfig,
        nodes_config: NodesConfig,
        fee_config: FeeConfig,
        # Transaction signing
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        platform_utxo: UTxO,
    ) -> DeploymentResult:
        """Deploy new oracle with reference scripts and start transaction.

        Args:
            network: Target network
            platform_auth_policy_id: Platform authorization NFT policy ID
            fee_token: Token used for fees
            script_config: Reference script configuration
            admin_address: Address for reference scripts
            script_address: Address for oracle script
            closing_period_length: Time allowed for closing period
            reward_dismissing_period_length: Time allowed for reward dismissal
            aggregation_liveness_period: Time window for aggregation
            time_absolute_uncertainty: Allowed time uncertainty
            iqr_fence_multiplier: IQR multiplier for outlier detection
            deployment_config: Deployment parameters
            nodes_config: Configuration for oracle nodes
            fee_config: Fee configuration
            signing_key: Key for signing transactions
            platform_utxo: UTxO containing platform auth NFT

        Returns:
            DeploymentResult with status and outputs

        Raises:
            Exception: If deployment fails
        """
        try:
            # Create oracle configuration
            config = OracleConfiguration(
                platform_auth_nft=platform_auth_policy_id,
                closing_period_length=closing_period_length,
                reward_dismissing_period_length=reward_dismissing_period_length,
                fee_token=fee_token,
            )

            # Handle start transaction
            start_result = await self._handle_start_transaction(
                config=config,
                deployment_config=deployment_config,
                nodes_config=nodes_config,
                script_address=script_address,
                platform_utxo=platform_utxo,
                platform_script=platform_script,
                admin_address=admin_address,
                signing_key=signing_key,
                fee_config=fee_config,
                aggregation_liveness_period=aggregation_liveness_period,
                time_absolute_uncertainty=time_absolute_uncertainty,
                iqr_fence_multiplier=iqr_fence_multiplier,
            )

            self._update_status(
                ProcessStatus.TRANSACTION_BUILT,
                "deployment transaction has been built...",
            )
            return DeploymentResult(
                status=ProcessStatus.TRANSACTION_BUILT,
                start_result=start_result,
            )

        except Exception as e:
            logger.error("Deployment failed: %s", str(e))
            self._update_status(ProcessStatus.FAILED, str(e))
            raise

    async def handle_reference_scripts(
        self,
        script_config: OracleScriptConfig,
        script_address: Address,
        admin_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
    ) -> tuple[ReferenceScriptResult, bool]:
        """Checks and optionally contructs the reference script creation tx if needed."""

        self._update_status(
            ProcessStatus.CHECKING_REFERENCE_SCRIPTS,
            "Checking for existing reference scripts...",
        )

        result = await self.reference_builder.prepare_reference_script(
            script_config=script_config,
            script_address=script_address,
            admin_address=admin_address,
            signing_key=signing_key,
        )
        return result, result.manager_tx is not None

    async def submit_reference_script_tx(
        self,
        result: ReferenceScriptResult,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
    ) -> None:
        """Submit prepared reference script transaction."""
        self._update_status(
            ProcessStatus.CREATING_SCRIPT,
            "Creating manager reference script...",
        )
        await self.reference_builder.submit_reference_script(result, signing_key)
        return result

    async def _handle_start_transaction(
        self,
        config: OracleConfiguration,
        deployment_config: OracleDeploymentConfig,
        nodes_config: NodesConfig,
        script_address: Address,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        admin_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        fee_config: FeeConfig,
        aggregation_liveness_period: int,
        time_absolute_uncertainty: int,
        iqr_fence_multiplier: int,
    ) -> StartTransactionResult:
        """Build and submit oracle start transaction."""
        self._update_status(
            ProcessStatus.BUILDING_TRANSACTION, "Building oracle start transaction..."
        )

        return await self.start_builder.build_start_transaction(
            config=config,
            deployment_config=deployment_config,
            nodes_config=nodes_config,
            script_address=script_address,
            platform_utxo=platform_utxo,
            platform_script=platform_script,
            change_address=admin_address,
            signing_key=signing_key,
            fee_config=fee_config,
            aggregation_liveness_period=aggregation_liveness_period,
            time_absolute_uncertainty=time_absolute_uncertainty,
            iqr_fence_multiplier=iqr_fence_multiplier,
        )
