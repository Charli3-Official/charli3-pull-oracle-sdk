""" Module for PlutusV3Contract class, an extension of PlutusContract for Plutus V3 scripts """

import copy
import json
import typing

import uplc.ast
from opshin.builder import PlutusContract, Purpose
from opshin.util import datum_to_cbor
from pycardano import Datum, PlutusV3Script
from uplc import flatten

EMPTY_PARAMETER_TYPES: list[tuple[str, type[Datum]]] = []


class PlutusV3Contract(PlutusContract):
    """
    Extension of PlutusContract that handles PlutusV3Script instead of PlutusV2Script.
    Inherits all functionality from PlutusContract while modifying only version-specific methods.
    """

    contract: PlutusV3Script  # Type hint for better IDE support

    def __init__(
        self,
        contract: PlutusV3Script,
        datum_type: tuple[str, type[Datum]] | None = None,
        redeemer_type: tuple[str, type[Datum]] | None = None,
        parameter_types: list[tuple[str, type[Datum]]] | None = None,
        purpose: typing.Iterable[Purpose] = (Purpose.any,),
        version: str | None = "1.0.0",
        title: str = "validator",
        description: str | None = None,
        license: str | None = None,
    ) -> None:
        if parameter_types is None:
            parameter_types = EMPTY_PARAMETER_TYPES
        # Call parent's __init__ with provided arguments
        super().__init__(
            contract=contract,
            datum_type=datum_type,
            redeemer_type=redeemer_type,
            parameter_types=parameter_types,
            purpose=purpose,
            version=version,
            title=title,
            description=description or "aiken '1.0.0' Smart Contract (V3)",
            license=license,
        )

    @property
    def plutus_json(self) -> str:
        """Override to specify PlutusV3Script type"""
        return json.dumps(
            {
                "type": "PlutusScriptV3",
                "description": self.description,
                "cborHex": self.cbor_hex,
            },
            indent=2,
        )

    @property
    def blueprint(self) -> dict:
        """Override to specify V3 in the preamble"""
        blueprint_data = super().blueprint
        blueprint_data["preamble"]["plutusVersion"] = "v3"
        return blueprint_data

    def apply_parameter(self, *args: Datum) -> "PlutusV3Contract":
        """
        Override to return PlutusV3Contract instead of PlutusContract
        """
        if len(self.parameter_types) < len(args):
            raise ValueError(
                f"Applying too many parameters to contract, allowed amount: {self.parameter_types}, but got {len(args)}"
            )
        new_parameter_types = copy.copy(self.parameter_types)
        for _ in args:
            new_parameter_types.pop(0)
        new_contract_contract = apply_parameters(self.contract, *args)
        new_contract = PlutusV3Contract(
            new_contract_contract,
            self.datum_type,
            self.redeemer_type,
            new_parameter_types,
            self.purpose,
            self.version,
            self.title,
            self.description,
        )
        return new_contract


# Helper functions specific to V3 Script handling
def apply_parameters(script: PlutusV3Script, *args: Datum) -> PlutusV3Script:
    """Helper function to apply parameters to a PlutusV3Script"""
    return _build(_apply_parameters(uplc.unflatten(script), *args))


def _apply_parameters(script: uplc.ast.Program, *args: Datum) -> uplc.ast.Program:
    """
    Expects a UPLC program and returns the build artifacts from applying parameters to it
    """
    # apply parameters from the command line to the contract (instantiates parameterized contract!)
    code = script.term
    # UPLC lambdas may only take one argument at a time, so we evaluate by repeatedly applying
    for d in args:
        code = uplc.ast.Apply(
            code,
            (
                uplc.ast.data_from_cbor(datum_to_cbor(d))
                if not isinstance(d, uplc.ast.Constant)
                else d
            ),
        )
    code = uplc.ast.Program((1, 0, 0), code)
    return code


def _build(contract: uplc.ast.Program) -> PlutusV3Script:
    """Helper function to build a PlutusV3Script from a UPLC program"""
    cbor = flatten(contract)
    return PlutusV3Script(cbor)
