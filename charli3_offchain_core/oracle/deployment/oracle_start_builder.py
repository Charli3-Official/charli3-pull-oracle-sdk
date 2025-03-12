"""Oracle start transaction builder for initial oracle deployment."""

import logging
import math
from dataclasses import dataclass
from typing import Any

from pycardano import (
    Address,
    ExtendedSigningKey,
    MultiAsset,
    NativeScript,
    PaymentSigningKey,
    Redeemer,
    ScriptHash,
    Transaction,
    TransactionBuilder,
    TransactionOutput,
    UTxO,
    Value,
    min_lovelace_post_alonzo,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.cli.config.nodes import NodesConfig
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import (
    MINIMUM_ADA_AMOUNT_HELD_AT_MAXIMUM_EXPECTED_ORACLE_UTXO_SIZE,
    AggState,
    FeeConfig,
    NoDatum,
    Nodes,
    NoRewards,
    OracleConfiguration,
    OracleSettingsDatum,
    OracleSettingsVariant,
    PriceData,
    RewardAccountDatum,
    RewardAccountVariant,
    RewardTransportVariant,
)
from charli3_offchain_core.models.oracle_redeemers import Mint as MintRedeemer
from charli3_offchain_core.oracle.config import OracleDeploymentConfig, OracleTokenNames

logger = logging.getLogger(__name__)


@dataclass
class StartTransactionResult:
    """Result of oracle start transaction"""

    transaction: Transaction
    settings_utxo: TransactionOutput
    reward_account_utxo: TransactionOutput
    reward_transport_utxos: list[TransactionOutput]
    agg_state_utxos: list[TransactionOutput]


class OracleStartBuilder:
    """Builds oracle start transaction for initial deployment"""

    # Constants for clarity and reuse
    MIN_UTXO_VALUE = 2_000_000
    FEE_BUFFER = 10_000

    def __init__(
        self,
        chain_query: ChainQuery,
        contracts: OracleContracts,
        tx_manager: TransactionManager,
    ) -> None:
        self.chain_query = chain_query
        self.contracts = contracts
        self.tx_manager = tx_manager
        self._standard_min_ada = self.MIN_UTXO_VALUE

    async def build_start_transaction(
        self,
        config: OracleConfiguration,
        nodes_config: NodesConfig,
        deployment_config: OracleDeploymentConfig,
        script_address: Address,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        rate_config: FeeConfig,
        aggregation_liveness_period: int,
        time_uncertainty_aggregation: int,
        time_uncertainty_platform: int,
        iqr_fence_multiplier: int,
        utxo_size_safety_buffer: int | None = None,
    ) -> StartTransactionResult:
        """
        Build oracle start transaction that mints NFTs and creates initial UTxOs.

        Args:
            config: Oracle configuration parameters
            nodes_config: Nodes configuration with node keys
            deployment_config: Deployment configuration with token names
            script_address: Address for oracle script UTxOs
            platform_utxo: UTxO containing platform auth NFT
            change_address: Address for change output
            signing_key: Signing key for transaction

        Returns:
            StartTransactionResult containing transaction and created UTxOs

        Raises:
            ValueError: If platform auth NFT is invalid
        """
        # Verify platform auth NFT
        if not self._verify_platform_auth(platform_utxo, config.platform_auth_nft):
            raise ValueError("Invalid platform auth NFT")

        # Get minting UTxO
        minting_utxo = await self._get_minting_utxo(change_address)
        if not minting_utxo:
            raise ValueError(
                "No suitable UTxO found for minting policy parameterization"
            )

        logger.info(
            "Using minting UTxO: %s#%d (%d lovelace)",
            minting_utxo.input.transaction_id,
            minting_utxo.input.index,
            minting_utxo.output.amount.coin,
        )

        # Initialize transaction builder
        builder = TransactionBuilder(
            self.chain_query.context, fee_buffer=self.FEE_BUFFER
        )

        # Add inputs and preserve platform auth
        builder.add_input(platform_utxo)
        builder.native_scripts = [platform_script]
        if minting_utxo.input != platform_utxo.input:
            builder.add_input(minting_utxo)

        builder.add_output(
            TransactionOutput(
                address=platform_utxo.output.address,
                amount=platform_utxo.output.amount,
            )
        )

        # Create minting policy
        mint_policy = self.contracts.apply_mint_params(
            minting_utxo,
            config,
            self.contracts.spend.script_hash,
        )
        logger.info("Created minting policy with ID: %s", mint_policy.policy_id)

        # Create core UTxOs - Calculate CoreSettings first to set standard min ADA
        settings_utxo = self._create_utxo_with_nft(
            script_address,
            deployment_config.token_names.core_settings,
            mint_policy.policy_id,
            self._create_settings_datum(
                config,
                rate_config,
                nodes_config,
                aggregation_liveness_period,
                time_uncertainty_aggregation,
                time_uncertainty_platform,
                iqr_fence_multiplier,
            ),
            "core_settings",
            utxo_size_safety_buffer,
        )

        reward_account_utxo = self._create_utxo_with_nft(
            script_address,
            deployment_config.token_names.reward_account,
            mint_policy.policy_id,
            RewardAccountVariant(
                datum=RewardAccountDatum(nodes_to_rewards=[0] * len(nodes_config.nodes))
            ),
            "other",
        )

        # Create reward transport and agg state UTxOs
        transport_pairs = [
            (
                self._create_utxo_with_nft(
                    script_address,
                    deployment_config.token_names.reward_transport,
                    mint_policy.policy_id,
                    RewardTransportVariant(datum=NoRewards()),
                    "other",
                ),
                self._create_utxo_with_nft(
                    script_address,
                    deployment_config.token_names.aggstate,
                    mint_policy.policy_id,
                    AggState(price_data=PriceData.empty()),
                    "agg_state",
                ),
            )
            for _ in range(deployment_config.reward_transport_count)
        ]
        reward_transport_utxos, agg_state_utxos = zip(*transport_pairs)

        # Add all outputs to builder
        builder.add_output(settings_utxo)
        builder.add_output(reward_account_utxo)
        for utxo in [*reward_transport_utxos, *agg_state_utxos]:
            builder.add_output(utxo)

        # Add minting
        builder.mint = self._create_nft_mint(
            mint_policy.policy_id,
            deployment_config.token_names,
            deployment_config.reward_transport_count,
        )
        builder.add_minting_script(
            script=mint_policy.contract,
            redeemer=Redeemer(MintRedeemer()),
        )

        # Build and return result
        tx = await self.tx_manager.build_tx(
            builder=builder,
            change_address=change_address,
            signing_key=signing_key,
        )

        return StartTransactionResult(
            transaction=tx,
            settings_utxo=settings_utxo,
            reward_account_utxo=reward_account_utxo,
            reward_transport_utxos=list(reward_transport_utxos),
            agg_state_utxos=list(agg_state_utxos),
        )

    def _verify_platform_auth(self, utxo: UTxO, policy_id: bytes) -> bool:
        """Verify UTxO contains an asset with the platform policy ID

        Args:
            utxo: UTxO to verify
            policy_id: Policy ID to check as bytes

        Returns:
            bool: True if UTxO contains any asset under the policy ID
        """
        return (
            utxo.output.amount.multi_asset is not None
            and ScriptHash(policy_id) in utxo.output.amount.multi_asset
        )

    async def _get_minting_utxo(self, address: Address) -> UTxO | None:
        """Find suitable UTxO for minting policy parameterization."""
        utxos = await self.chain_query.get_utxos(address)
        return next(
            (utxo for utxo in utxos),
            None,
        )

    def _create_settings_datum(
        self,
        config: OracleConfiguration,
        rate_config: FeeConfig,
        nodes_config: NodesConfig,
        aggregation_liveness_period: int,
        time_uncertainty_aggregation: int,
        time_uncertainty_platform: int,
        iqr_fence_multiplier: int,
    ) -> OracleSettingsVariant:
        """Create settings datum with initial configuration."""
        node_map = {node.feed_vkh: node.payment_vkh for node in nodes_config.nodes}

        oracle_settings = OracleSettingsDatum(
            nodes=Nodes(node_map=node_map),
            required_node_signatures_count=nodes_config.required_signatures,
            fee_info=rate_config,
            aggregation_liveness_period=aggregation_liveness_period,
            time_uncertainty_aggregation=time_uncertainty_aggregation,
            time_uncertainty_platform=time_uncertainty_platform,
            iqr_fence_multiplier=iqr_fence_multiplier,
            utxo_size_safety_buffer=MINIMUM_ADA_AMOUNT_HELD_AT_MAXIMUM_EXPECTED_ORACLE_UTXO_SIZE,
            pause_period_started_at=NoDatum(),
        )
        oracle_settings.validate_based_on_config(config)

        return OracleSettingsVariant(datum=oracle_settings)

    def _create_utxo_with_nft(
        self,
        address: Address,
        token_name: str,
        policy_id: ScriptHash,
        datum: Any,
        utxo_type: str,
        utxo_size_safety_buffer: int | None = None,
    ) -> TransactionOutput:
        """
        Create UTxO with NFT and datum, with specific ADA amounts based on UTxO type.

        Args:
            address: Script address for the UTxO
            token_name: Name of the NFT token
            policy_id: Policy ID for the NFT
            datum: Datum to attach to the UTxO
            utxo_type: Type of UTxO ('core_settings', 'agg_state', or 'other')

        Returns:
            TransactionOutput: Properly configured output with appropriate ADA amount
        """
        # Create initial value with just the NFT
        value = Value()
        value.multi_asset = MultiAsset.from_primitive(
            {policy_id: {token_name.encode(): 1}}
        )

        # Create initial output without ADA
        output = TransactionOutput(
            address=address,
            amount=value,
            datum=datum,
        )

        if utxo_type == "agg_state":
            # Fixed 2 ADA for AggregationState
            output.amount.coin = self.MIN_UTXO_VALUE
        elif utxo_type == "core_settings":
            # Calculate exact minimum and store rounded up value for other UTxOs
            if utxo_size_safety_buffer is None:
                min_ada = min_lovelace_post_alonzo(output, self.chain_query.context)
                self._standard_min_ada = math.ceil(min_ada / 1_000_000) * 1_000_000
            else:
                self._standard_min_ada = utxo_size_safety_buffer
            # Round up to nearest ADA (lovelace to ADA, ceiling, back to lovelace)
            output.amount.coin = self._standard_min_ada
            output.datum.datum.utxo_size_safety_buffer = self._standard_min_ada
        else:
            # Use the rounded up value from CoreSettings for all other UTxOs
            output.amount.coin = self._standard_min_ada

        return output

    def _create_nft_mint(
        self,
        policy_id: ScriptHash,
        token_names: OracleTokenNames,
        transport_count: int,
    ) -> MultiAsset:
        """Create MultiAsset for minting oracle NFTs."""
        mint_map = {
            token_names.core_settings.encode(): 1,
            token_names.reward_account.encode(): 1,
            token_names.reward_transport.encode(): transport_count,
            token_names.aggstate.encode(): transport_count,
        }

        return MultiAsset.from_primitive({policy_id: mint_map})
