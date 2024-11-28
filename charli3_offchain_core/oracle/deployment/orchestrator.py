"""Orchestrates the oracle deployment process including reference scripts and start transaction."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from pycardano import Address, ExtendedSigningKey, NativeScript, PaymentSigningKey, UTxO

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.deployment import NodesConfig
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import (
    Asset,
    FeeConfig,
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

logger = logging.getLogger(__name__)


class DeploymentStatus(str, Enum):
    """Status of oracle deployment process"""

    NOT_STARTED = "not_started"
    CHECKING_REFERENCE_SCRIPTS = "checking_reference_scripts"
    CREATING_MANAGER_REFERENCE = "creating_manager_reference"
    BUILDING_START_TX = "building_start_tx"
    SUBMITTING_START_TX = "submitting_start_tx"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DeploymentResult:
    """Result of oracle deployment"""

    status: DeploymentStatus
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
        status_callback: Callable[[DeploymentStatus, str], None] | None = None,
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
        self.current_status = DeploymentStatus.NOT_STARTED

    def _update_status(self, status: DeploymentStatus, message: str = "") -> None:
        """Update deployment status and notify callback."""
        self.current_status = status
        if self.status_callback:
            self.status_callback(status, message)
        logger.info("Deployment status: %s - %s", status, message)

    async def deploy_oracle(
        self,
        # Network configuration
        platform_auth_policy_id: bytes,
        fee_token: Asset,
        platform_script: NativeScript,
        # Script configuration
        script_config: OracleScriptConfig,
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

            # Handle reference scripts
            self._update_status(
                DeploymentStatus.CHECKING_REFERENCE_SCRIPTS,
                "Checking for existing reference scripts...",
            )

            reference_result = await self._handle_reference_scripts(
                script_config=script_config,
                script_address=script_address,
                admin_address=admin_address,
                signing_key=signing_key,
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

            self._update_status(DeploymentStatus.COMPLETED, "Deployment completed")
            return DeploymentResult(
                status=DeploymentStatus.COMPLETED,
                reference_scripts=reference_result,
                start_result=start_result,
            )

        except Exception as e:
            logger.error("Deployment failed: %s", str(e))
            self._update_status(DeploymentStatus.FAILED, str(e))
            raise

    async def _handle_reference_scripts(
        self,
        script_config: OracleScriptConfig,
        script_address: Address,
        admin_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
    ) -> ReferenceScriptResult:
        """Handle reference script creation if needed."""
        # Prepare reference scripts
        result = await self.reference_builder.prepare_reference_script(
            script_config=script_config,
            script_address=script_address,
            admin_address=admin_address,
            signing_key=signing_key,
        )

        # Submit manager reference script if needed
        if result.manager_tx:
            self._update_status(
                DeploymentStatus.CREATING_MANAGER_REFERENCE,
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
            DeploymentStatus.BUILDING_START_TX, "Building oracle start transaction..."
        )

        start_result = await self.start_builder.build_start_transaction(
            config=config,
            nodes_config=nodes_config,
            deployment_config=deployment_config,
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

        # Submit transaction
        self._update_status(
            DeploymentStatus.SUBMITTING_START_TX, "Submitting start transaction..."
        )

        self._update_status(
            DeploymentStatus.WAITING_CONFIRMATION,
            "Waiting for transaction confirmation...",
        )

        await self.tx_manager.sign_and_submit(start_result.transaction, [signing_key])

        return start_result
