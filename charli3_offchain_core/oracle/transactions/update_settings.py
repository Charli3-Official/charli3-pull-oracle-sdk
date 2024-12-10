"""Update Settings."""

import logging

from pycardano import Asset, AssetName, MultiAsset, Redeemer, ScriptHash, UTxO

from charli3_offchain_core.cli.config.multisig import MultisigConfig
from charli3_offchain_core.models.oracle_datums import (
    Asset as DatumAsset,
)
from charli3_offchain_core.models.oracle_datums import (
    FeeConfig,
    Nodes,
    OracleSettingsDatum,
    OracleSettingsVariant,
    RewardPrices,
)
from charli3_offchain_core.models.oracle_redeemers import UpdateSettings
from charli3_offchain_core.oracle.transactions.base import (
    BaseTransaction,
)
from charli3_offchain_core.oracle.transactions.exceptions import (
    UTxONotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)


class UpdateCoreSettings(BaseTransaction):
    """Update Core Setting Transaction Logic"""

    REDEEMER = Redeemer(UpdateSettings())

    @property
    async def get_core_settings_utxo(self) -> UTxO:
        if not hasattr(self, "core_settings_asset"):
            self.core_settings_asset = self.get_core_settings_asset

        try:
            utxo = await self.retrieve_utxo_by_asset(
                self.core_settings_asset, self.tx_config.contract_address
            )

            if utxo is None:
                raise UTxONotFoundError(
                    f"Core settings UTxO not found for asset: {self.core_settings_asset}"
                )

            utxo.output.datum = self.parse_settings_datum(utxo)
            return utxo

        except ValidationError as e:
            raise ValidationError(f"Invalid UTxO data for core settings: {e!s}") from e

        except Exception as e:
            raise UTxONotFoundError(
                f"Error retrieving core settings UTxO: {e!s}"
            ) from e

    @property
    async def get_deployed_core_settings_datum(self) -> OracleSettingsVariant:
        if not hasattr(self, "core_settings_asset"):
            self.core_settings_asset = self.get_core_settings_asset

        return self.parse_settings_datum(await self.get_core_settings_utxo)

    @property
    def get_core_settings_asset(self) -> MultiAsset:
        name = self.tx_config.token_names.core_settings
        asset_name = AssetName(name.encode())

        minting_policy = ScriptHash.from_primitive(self.tx_config.contract_token_hash)
        asset = Asset({asset_name: 1})

        return MultiAsset({minting_policy: asset})

    def parse_settings_datum(self, utxo: UTxO | None) -> OracleSettingsVariant:

        if utxo is None or utxo.output.datum is None:
            raise ValueError("Invalid core settings UTxO")

        if isinstance(utxo.output.datum, OracleSettingsVariant):
            return utxo.output.datum
        try:
            if hasattr(utxo.output.datum, "cbor"):
                return OracleSettingsVariant.from_cbor(utxo.output.datum.cbor)
            raise ValueError("Datum missing CBOR")
        except Exception as e:
            logger.error("Error %s", e)

    @property
    def get_loaded_core_settings_datum(self) -> OracleSettingsVariant:
        multi_sig = self.tx_config.multi_sig or MultisigConfig(
            threshold=1, parties=[""]
        )
        return OracleSettingsVariant(
            OracleSettingsDatum(
                nodes=Nodes.empty(),
                required_node_signatures_count=multi_sig.threshold,
                fee_info=FeeConfig(
                    DatumAsset(
                        policy_id=bytes.fromhex(self.tx_config.tokens.fee_token_policy),
                        name=AssetName((self.tx_config.tokens.fee_token_name).encode()),
                    ),
                    RewardPrices(
                        self.tx_config.fees.node_fee, self.tx_config.fees.platform_fee
                    ),
                ),
                aggregation_liveness_period=self.tx_config.timing.aggregation_liveness,
                time_absolute_uncertainty=self.tx_config.timing.time_uncertainty,
                iqr_fence_multiplier=self.tx_config.timing.iqr_multiplier,
                closing_period_started_at=self.tx_config.timing.closing_period,
            )
        )

    @property
    async def modified_core_utxo(self) -> UTxO:
        core_utxo = await self.get_core_settings_utxo
        core_utxo.output.datum = await self.allowed_datum_changes
        return core_utxo

    @property
    async def allowed_datum_changes(self) -> OracleSettingsVariant:
        """
        Validates and creates a new OracleSettingsVariant with updated settings.

        Returns:
            OracleSettingsVariant: Updated oracle settings with validated parameters

        Raises:
            ValueError: If any of the multisignature or timing parameters are invalid
        """
        deployed_core_settings = await self.get_deployed_core_settings_datum

        # Extract configuration values for better readability
        threshold = self.tx_config.multi_sig.threshold
        parties = deployed_core_settings.datum.nodes
        timing_config = self.tx_config.timing

        # Validate timing parameters
        if not timing_config.time_uncertainty > 0:
            raise ValueError("Time uncertainty must be positive")

        if not timing_config.aggregation_liveness > timing_config.time_uncertainty:
            raise ValueError(
                "Aggregation liveness must be greater than time uncertainty"
            )

        if not timing_config.iqr_multiplier > 100:
            raise ValueError("IQR multiplier must be greater than 100")

        # Validate multisignature parameters
        if not threshold > 0:
            raise ValueError("Threshold must be positive")

        if not threshold <= parties.length:
            raise ValueError(
                "Threshold cannot be greater than number of deployed parties"
            )

        # Create new settings with validated parameters
        return OracleSettingsVariant(
            OracleSettingsDatum(
                nodes=deployed_core_settings.datum.nodes,
                required_node_signatures_count=threshold,
                fee_info=deployed_core_settings.datum.fee_info,
                aggregation_liveness_period=timing_config.aggregation_liveness,
                time_absolute_uncertainty=timing_config.time_uncertainty,
                iqr_fence_multiplier=timing_config.iqr_multiplier,
                closing_period_started_at=deployed_core_settings.datum.closing_period_started_at,
            )
        )
