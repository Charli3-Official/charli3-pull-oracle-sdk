"""Oracle start transaction builder for initial oracle deployment."""

import logging
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
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.contracts.aiken_loader import OracleContracts
from charli3_offchain_core.models.oracle_datums import (
    AggStateVariant,
    FeeConfig,
    NoDatum,
    Nodes,
    NoRewards,
    OracleConfiguration,
    OracleSettingsDatum,
    OracleSettingsVariant,
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

    async def build_start_transaction(
        self,
        config: OracleConfiguration,
        deployment_config: OracleDeploymentConfig,
        script_address: Address,
        platform_utxo: UTxO,
        platform_script: NativeScript,
        change_address: Address,
        signing_key: PaymentSigningKey | ExtendedSigningKey,
        fee_config: FeeConfig,
        aggregation_liveness_period: int,
        time_absolute_uncertainty: int,
        iqr_fence_multiplier: int,
    ) -> StartTransactionResult:
        """
        Build oracle start transaction that mints NFTs and creates initial UTxOs.

        Args:
            config: Oracle configuration parameters
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
        minting_utxo = await self._get_minting_utxo(change_address, platform_utxo)
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

        # Create core UTxOs
        settings_utxo = self._create_utxo_with_nft(
            script_address,
            deployment_config.token_names.core_settings,
            mint_policy.policy_id,
            self._create_settings_datum(
                fee_config,
                aggregation_liveness_period,
                time_absolute_uncertainty,
                iqr_fence_multiplier,
            ),
        )

        reward_account_utxo = self._create_utxo_with_nft(
            script_address,
            deployment_config.token_names.reward_account,
            mint_policy.policy_id,
            RewardAccountVariant(datum=RewardAccountDatum(nodes_to_rewards=[])),
        )

        # Create reward transport and agg state UTxOs
        transport_pairs = [
            (
                self._create_utxo_with_nft(
                    script_address,
                    deployment_config.token_names.reward_transport,
                    mint_policy.policy_id,
                    RewardTransportVariant(datum=NoRewards()),
                ),
                self._create_utxo_with_nft(
                    script_address,
                    deployment_config.token_names.aggstate,
                    mint_policy.policy_id,
                    AggStateVariant(datum=NoDatum()),
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

    async def _get_minting_utxo(
        self, address: Address, platform_utxo: UTxO
    ) -> UTxO | None:
        """Find suitable UTxO for minting policy parameterization."""
        utxos = await self.chain_query.get_utxos(address)
        return next(
            (
                utxo
                for utxo in utxos
                if not utxo.output.amount.multi_asset
                and utxo.output.amount.coin >= self.MIN_UTXO_VALUE
                and utxo.input != platform_utxo.input
            ),
            None,
        )

    def _create_settings_datum(
        self,
        fee_config: FeeConfig,
        aggregation_liveness_period: int,
        time_absolute_uncertainty: int,
        iqr_fence_multiplier: int,
    ) -> OracleSettingsVariant:
        """Create settings datum with initial configuration."""
        return OracleSettingsVariant(
            datum=OracleSettingsDatum(
                nodes=Nodes.from_string_list(
                    [
                        "e06f55db4069f5fb1d2662078d025d909acc55b795a67b1db0d66070",
                        "ac7add7f734aa0074c2813eff8472a54263dd8f350ed0dc680934256",
                    ]
                ),
                required_node_signatures_count=1,
                fee_info=fee_config,
                aggregation_liveness_period=aggregation_liveness_period,
                time_absolute_uncertainty=time_absolute_uncertainty,
                iqr_fence_multiplier=iqr_fence_multiplier,
                closing_period_started_at=NoDatum(),
            )
        )

    def _create_utxo_with_nft(
        self,
        address: Address,
        token_name: str,
        policy_id: ScriptHash,
        datum: Any,
    ) -> TransactionOutput:
        """Create UTxO with NFT and datum."""
        value = Value(self.MIN_UTXO_VALUE)
        value.multi_asset = MultiAsset.from_primitive(
            {policy_id: {token_name.encode(): 1}}
        )

        return TransactionOutput(
            address=address,
            amount=value,
            datum=datum,
        )

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
