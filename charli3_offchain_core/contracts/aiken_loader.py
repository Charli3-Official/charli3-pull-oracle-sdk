"""Aiken contract loader for the Charli3 Oracle"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pycardano import (
    PlutusV3Script,
    ScriptHash,
    TransactionOutput,
    UTxO,
)

from charli3_offchain_core.contracts.plutus_v3_contract import PlutusV3Contract, Purpose
from charli3_offchain_core.models.oracle_datums import (
    OracleConfiguration,
    OracleDatum,
    OutputReference,
)
from charli3_offchain_core.models.oracle_redeemers import (
    MintingRedeemer,
    OracleRedeemer,
)


@dataclass
class OracleContracts:
    """Container for Oracle spend validator and mint policy"""

    spend: PlutusV3Contract
    mint: PlutusV3Contract

    @classmethod
    def from_blueprint(cls, blueprint_path: str | Path) -> "OracleContracts":
        """Load Oracle contracts from plutus.json blueprint"""
        blueprint_path = Path(blueprint_path)
        if not blueprint_path.exists():
            raise FileNotFoundError(f"Blueprint file not found: {blueprint_path}")

        try:
            with blueprint_path.open(encoding="utf-8") as f:
                blueprint = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid blueprint JSON: {e}") from e

        if blueprint["preamble"].get("plutusVersion") != "v3":
            raise ValueError("Only Plutus V3 contracts supported")

        validators = blueprint["validators"]
        spend_validator = None
        mint_validator = None

        for validator in validators:
            title = validator["title"]
            if title == "oracle.oracle_manager.spend":
                spend_validator = cls._create_spend_contract(validator)
            elif title == "oracle.oracle_nfts.mint":
                mint_validator = cls._create_mint_contract(validator)

        if not spend_validator or not mint_validator:
            raise ValueError("Missing required validators in blueprint")

        return cls(spend=spend_validator, mint=mint_validator)

    @staticmethod
    def _create_spend_contract(validator: dict[str, Any]) -> PlutusV3Contract:
        """Create spend validator contract"""
        contract = PlutusV3Script(bytes.fromhex(validator["compiledCode"]))

        # Uses predefined OracleDatum and OracleRedeemer types
        return PlutusV3Contract(
            contract=contract,
            datum_type=("own_datum", OracleDatum),
            redeemer_type=("redeemer", OracleRedeemer),
            parameter_types=[("config", OracleConfiguration)],
            purpose=[Purpose.spending],
            version="1.0.0",
            title=validator["title"],
        )

    @staticmethod
    def _create_mint_contract(validator: dict[str, Any]) -> PlutusV3Contract:
        """Create minting policy contract"""
        contract = PlutusV3Script(bytes.fromhex(validator["compiledCode"]))

        # Uses predefined MintingRedeemer type
        return PlutusV3Contract(
            contract=contract,
            redeemer_type=("redeemer", MintingRedeemer),
            parameter_types=[
                ("utxo_ref", TransactionOutput),
                ("config", OracleConfiguration),
                ("oracle_script_hash", ScriptHash),
            ],
            purpose=[Purpose.minting],
            version="1.0.0",
            title=validator["title"],
        )

    def apply_spend_params(self, config: OracleConfiguration) -> PlutusV3Contract:
        """Apply parameters to spend validator"""
        return self.spend.apply_parameter(config)

    def apply_mint_params(
        self,
        utxo_ref: UTxO,
        config: OracleConfiguration,
        oracle_script_hash: ScriptHash,
    ) -> PlutusV3Contract:
        """Apply parameters to mint policy"""
        tx_utxo_ref = OutputReference(
            utxo_ref.input.transaction_id.payload, utxo_ref.input.index
        )
        return self.mint.apply_parameter(tx_utxo_ref, config, oracle_script_hash)
