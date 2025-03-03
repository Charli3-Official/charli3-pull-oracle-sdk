"""Utilities for validating and managing oracle state transitions."""

import logging
from collections.abc import Sequence

from pycardano import ScriptHash, UTxO

from charli3_offchain_core.models.oracle_datums import (
    AggStateVariant,
    NoDatum,
    NoRewards,
    OracleDatum,
    OracleSettingsDatum,
    OracleSettingsVariant,
    RewardAccountDatum,
    RewardAccountVariant,
    RewardConsensusPending,
    RewardTransportVariant,
)
from charli3_offchain_core.oracle.exceptions import StateValidationError
from charli3_offchain_core.oracle.utils import asset_checks

logger = logging.getLogger(__name__)


def convert_cbor_to_transports(transport_utxos: Sequence[UTxO]) -> list[UTxO]:
    """
    Convert CBOR encoded NodeDatum objects to their corresponding Python objects.

    Parameters:
    - transport_utxos (List[UTxO]): A list of UTxO objects that contain RewardTransportDatum objects
      in CBOR encoding.

    Returns:
    - A list of UTxO objects that contain  RewardTransport Datum objects in their
      original Python format.
    """
    result: list[UTxO] = []
    for utxo in transport_utxos:
        if utxo.output.datum and not isinstance(
            utxo.output.datum, RewardTransportVariant
        ):
            if utxo.output.datum.cbor:
                utxo.output.datum = RewardTransportVariant.from_cbor(
                    utxo.output.datum.cbor
                )
                result.append(utxo)
        elif utxo.output.datum and isinstance(
            utxo.output.datum, RewardTransportVariant
        ):
            result.append(utxo)
    return result


def convert_cbor_to_agg_states(agg_state_utxos: Sequence[UTxO]) -> list[UTxO]:
    """
    Convert CBOR encoded NodeDatum objects to their corresponding Python objects.

    Parameters:
    - agg_state_utxos (List[UTxO]): A list of UTxO objects that contain AggStateDatum objects
      in CBOR encoding.

    Returns:
    - A list of UTxO objects that contain  AggState Datum objects in their
      original Python format.
    """
    result: list[UTxO] = []
    for utxo in agg_state_utxos:
        if utxo.output.datum and not isinstance(utxo.output.datum, AggStateVariant):
            if utxo.output.datum.cbor:
                utxo.output.datum = AggStateVariant.from_cbor(utxo.output.datum.cbor)
                result.append(utxo)
        elif utxo.output.datum and isinstance(utxo.output.datum, AggStateVariant):
            result.append(utxo)
    return result


def filter_empty_transports(utxos: Sequence[UTxO]) -> list[UTxO]:
    """Filter UTxOs for empty reward transport states.

    Args:
        utxos: List of UTxOs to filter

    Returns:
        List of UTxOs with empty reward transport states
    """

    utxos_with_datum = convert_cbor_to_transports(utxos)

    return [
        utxo
        for utxo in utxos_with_datum
        if utxo.output.datum
        and isinstance(utxo.output.datum, RewardTransportVariant)
        and isinstance(utxo.output.datum.datum, NoRewards)
    ]


def filter_pending_transports(utxos: Sequence[UTxO]) -> list[UTxO]:
    """Filter UTxOs for pending reward consensus states.

    Args:
        utxos: List of UTxOs to filter

    Returns:
        List of UTxOs with pending consensus states
    """

    utxos_with_datum = convert_cbor_to_transports(utxos)

    return [
        utxo
        for utxo in utxos_with_datum
        if utxo.output.datum
        and isinstance(utxo.output.datum, RewardTransportVariant)
        and isinstance(utxo.output.datum.datum, RewardConsensusPending)
    ]


def filter_empty_agg_states(utxos: Sequence[UTxO]) -> list[UTxO]:
    """Filter UTxOs for empty aggregation states.

    Args:
        utxos: List of UTxOs to filter

    Returns:
        List of UTxOs with empty aggregation states
    """

    utxos_with_datum = convert_cbor_to_agg_states(utxos)

    return [
        utxo
        for utxo in utxos_with_datum
        if utxo.output.datum
        and isinstance(utxo.output.datum, AggStateVariant)
        and isinstance(utxo.output.datum.datum, NoDatum)
    ]


def filter_reward_accounts(utxos: Sequence[UTxO]) -> list[UTxO]:
    """Filter reward account UTxOs.

    Args:
        utxos: UTxOs to filter

    Returns:
        List of reward account UTxOs
    """
    return [
        utxo
        for utxo in utxos
        if (
            utxo.output.datum
            and isinstance(utxo.output.datum, RewardAccountVariant)
            and isinstance(utxo.output.datum.datum, RewardAccountDatum)
        )
    ]


def filter_oracle_settings_utxo(utxos: Sequence[UTxO], policy_id: ScriptHash) -> UTxO:
    """Filter UTxOs for oracle settings.

    Args:
        utxos: List of UTxOs to filter

    Returns:
        Oracle settings UTxO
    """
    oracle_settings_utxos = asset_checks.filter_utxos_by_token_name(
        utxos, policy_id, "CoreSettings"
    )
    return oracle_settings_utxos[0]


def filter_reward_account_utxo(utxos: Sequence[UTxO], policy_id: ScriptHash) -> UTxO:
    """Filter UTxOs for reward account.

    Args:
        utxos: List of UTxOs to filter

    Returns:
        Reward account UTxO
    """
    reward_account_utxos = asset_checks.filter_utxos_by_token_name(
        utxos, policy_id, "RewardAccount"
    )
    return reward_account_utxos[0]


def get_oracle_settings_by_policy_id(
    utxos: Sequence[UTxO], policy_id: ScriptHash
) -> tuple[OracleSettingsDatum, UTxO]:
    """Get oracle settings datum by policy ID.

    Args:
        utxos: List of UTxOs to search
        policy_id: Policy ID

    Returns:
        OracleSettingsDatum: Oracle settings datum
        UTxO: Oracle settings UTxO

    Raises:
        StateValidationError: If no oracle settings datum is found
    """
    try:
        settings_utxo = filter_oracle_settings_utxo(utxos, policy_id)
        settings_utxo_datum = None

        if settings_utxo.output.datum and not isinstance(
            settings_utxo.output.datum, OracleSettingsVariant
        ):
            settings_utxo.output.datum = OracleSettingsVariant.from_cbor(
                settings_utxo.output.datum.cbor
            )
        settings_utxo_datum = settings_utxo.output.datum

        return settings_utxo_datum.datum, settings_utxo

    except Exception as e:
        raise StateValidationError(f"Failed to get oracle settings: {e}") from e


def get_reward_account_by_policy_id(
    utxos: Sequence[UTxO], policy_id: ScriptHash
) -> tuple[RewardAccountDatum, UTxO]:
    """Get reward account datum by policy ID.

    Args:
        utxos: List of UTxOs to search
        policy_id: Policy ID

    Returns:
        RewardAccountDatum: Reward account datum
        UTxO: Reward account UTxO

    Raises:
        StateValidationError: If no reward account datum is found
    """
    try:
        reward_account_utxo = filter_reward_account_utxo(utxos, policy_id)
        reward_account_datum = None

        if reward_account_utxo.output.datum and not isinstance(
            reward_account_utxo.output.datum, RewardAccountVariant
        ):
            reward_account_utxo.output.datum = RewardAccountVariant.from_cbor(
                reward_account_utxo.output.datum.cbor
            )
        reward_account_datum = reward_account_utxo.output.datum

        return reward_account_datum.datum, reward_account_utxo

    except Exception as e:
        raise StateValidationError(f"Failed to get reward account: {e}") from e


def filter_valid_agg_states(utxos: Sequence[UTxO], current_time: int) -> list[UTxO]:
    """Filter UTxOs for empty or expired aggregation states.

    Args:
        utxos: List of UTxOs to filter
        current_time: Current time for checking expiry

    Returns:
        List of UTxOs with empty or expired aggregation states
    """
    utxos_with_datum = convert_cbor_to_agg_states(utxos)

    return [
        utxo
        for utxo in utxos_with_datum
        if utxo.output.datum
        and isinstance(utxo.output.datum, AggStateVariant)
        and (
            isinstance(utxo.output.datum.datum, NoDatum)  # Empty state
            or (
                not isinstance(utxo.output.datum.datum, NoDatum)
                and utxo.output.datum.datum.aggstate.expiry_timestamp
                < current_time  # Expired state
            )
        )
    ]


def find_transport_pair(
    utxos: Sequence[UTxO], policy_id: ScriptHash, current_time: int
) -> tuple[UTxO, UTxO]:
    """Find empty transport and agg state pair (empty or expired).

    Args:
        utxos: List of UTxOs to search
        policy_id: Policy ID for filtering tokens
        current_time: Current time for checking expiry

    Returns:
        Tuple of (transport UTxO, agg state UTxO)

    Raises:
        StateValidationError: If no valid pair is found
    """
    try:
        # Find empty transports
        transports = filter_empty_transports(
            asset_checks.filter_utxos_by_token_name(utxos, policy_id, "RewardTransport")
        )
        if not transports:
            raise StateValidationError("No empty transport UTxO found")

        # Find empty or expired agg states
        agg_states = filter_valid_agg_states(
            asset_checks.filter_utxos_by_token_name(
                utxos, policy_id, "AggregationState"
            ),
            current_time,
        )
        if not agg_states:
            raise StateValidationError("No valid agg state UTxO found")

        # Return first pair found
        return transports[0], agg_states[0]

    except Exception as e:
        raise StateValidationError(f"Failed to find UTxO pair: {e}") from e


def is_oracle_paused(settings: OracleSettingsDatum) -> bool:
    """Check if oracle is in pause period.

    Args:
        settings: Oracle settings datum

    Returns:
        bool: True if oracle is in pause period
    """
    return not isinstance(settings.pause_period_started_at, NoDatum)


def can_process_rewards(
    transport: UTxO, current_time: int, liveness_period: int
) -> bool:
    """Check if rewards can be processed for transport UTxO.

    Args:
        transport: Transport UTxO to check
        current_time: Current time in milliseconds
        liveness_period: Liveness period duration

    Returns:
        bool: True if rewards can be processed

    Raises:
        StateValidationError: If validation fails
    """
    try:
        if not isinstance(
            transport.output.datum, RewardTransportVariant
        ) or not isinstance(transport.output.datum.datum, RewardConsensusPending):
            return False

        pending_data = transport.output.datum.datum
        message_time = pending_data.message.timestamp

        return current_time >= message_time + liveness_period

    except Exception as e:
        raise StateValidationError(f"Failed to validate reward processing: {e}") from e


def validate_datum_transition(
    current_datum: OracleDatum,
    next_datum: OracleDatum,
    valid_transitions: dict,
) -> bool:
    """Validate datum state transition.

    Args:
        current_datum: Current datum state
        next_datum: Next datum state
        valid_transitions: Map of valid state transitions

    Returns:
        bool: True if transition is valid

    Raises:
        StateValidationError: If validation fails
    """
    try:
        current_type = type(current_datum.datum).__name__
        next_type = type(next_datum.datum).__name__

        if current_type not in valid_transitions:
            return False

        return next_type in valid_transitions[current_type]

    except Exception as e:
        raise StateValidationError(f"Failed to validate datum transition: {e}") from e


def validate_matching_pair(transport: UTxO, agg_state: UTxO) -> bool:
    """Validate transport and agg state form a valid pair.

    Args:
        transport: Transport UTxO
        agg_state: Aggregation state UTxO

    Returns:
        bool: True if UTxOs form valid pair

    Raises:
        StateValidationError: If validation fails
    """
    try:

        # Validate state combinations
        transport_variant = transport.output.datum
        agg_state_variant = agg_state.output.datum

        if not isinstance(transport_variant, RewardTransportVariant):
            return False
        if not isinstance(agg_state_variant, AggStateVariant):
            return False

        # Check valid state combinations
        transport_empty = isinstance(transport_variant.datum, NoRewards)
        agg_state_empty = isinstance(agg_state_variant.datum, NoDatum)

        transport_pending = isinstance(transport_variant.datum, RewardConsensusPending)
        agg_state_active = not isinstance(agg_state_variant.datum, NoDatum)

        return (transport_empty and agg_state_empty) or (
            transport_pending and agg_state_active
        )

    except Exception as e:
        raise StateValidationError(f"Failed to validate UTxO pair: {e}") from e
