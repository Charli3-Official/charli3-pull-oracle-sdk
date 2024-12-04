"""Utilities for validating and managing oracle state transitions."""

import logging
from collections.abc import Sequence

from pycardano import UTxO

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


def filter_empty_transports(utxos: Sequence[UTxO]) -> list[UTxO]:
    """Filter UTxOs for empty reward transport states.

    Args:
        utxos: List of UTxOs to filter

    Returns:
        List of UTxOs with empty reward transport states
    """
    return [
        utxo
        for utxo in utxos
        if utxo.output.datum
        and isinstance(utxo.output.datum.variant, RewardTransportVariant)
        and isinstance(utxo.output.datum.variant.datum, NoRewards)
    ]


def filter_pending_transports(utxos: Sequence[UTxO]) -> list[UTxO]:
    """Filter UTxOs for pending reward consensus states.

    Args:
        utxos: List of UTxOs to filter

    Returns:
        List of UTxOs with pending consensus states
    """
    return [
        utxo
        for utxo in utxos
        if utxo.output.datum
        and isinstance(utxo.output.datum.variant, RewardTransportVariant)
        and isinstance(utxo.output.datum.variant.datum, RewardConsensusPending)
    ]


def filter_empty_agg_states(utxos: Sequence[UTxO]) -> list[UTxO]:
    """Filter UTxOs for empty aggregation states.

    Args:
        utxos: List of UTxOs to filter

    Returns:
        List of UTxOs with empty aggregation states
    """
    return [
        utxo
        for utxo in utxos
        if utxo.output.datum
        and isinstance(utxo.output.datum.variant, AggStateVariant)
        and isinstance(utxo.output.datum.variant.datum, NoDatum)
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
            and isinstance(utxo.output.datum.variant, RewardAccountVariant)
            and isinstance(utxo.output.datum.variant.datum, RewardAccountDatum)
        )
    ]


def filter_oracle_settings(utxos: Sequence[UTxO]) -> list[UTxO]:
    """Filter UTxOs for oracle settings.

    Args:
        utxos: List of UTxOs to filter

    Returns:
        List of UTxOs with oracle settings datums
    """
    return [
        utxo
        for utxo in utxos
        if utxo.output.datum
        and isinstance(utxo.output.datum.variant, OracleSettingsVariant)
        and isinstance(utxo.output.datum.variant.datum, OracleSettingsDatum)
    ]


def find_transport_pair(utxos: Sequence[UTxO], policy_id: bytes) -> tuple[UTxO, UTxO]:
    """Find matching empty transport and agg state pair.

    Args:
        utxos: List of UTxOs to search
        policy_id: Policy ID for filtering tokens

    Returns:
        Tuple of (transport UTxO, agg state UTxO)

    Raises:
        StateValidationError: If no valid pair is found
    """
    try:
        # Find empty transports
        transports = filter_empty_transports(
            asset_checks.filter_utxos_by_token_name(utxos, policy_id, "transport")
        )
        if not transports:
            raise StateValidationError("No empty transport UTxO found")

        # Find empty agg states
        agg_states = filter_empty_agg_states(
            asset_checks.filter_utxos_by_token_name(utxos, policy_id, "aggstate")
        )
        if not agg_states:
            raise StateValidationError("No empty agg state UTxO found")

        # Find matching pair
        for transport in transports:
            for agg_state in agg_states:
                if validate_matching_pair(transport, agg_state):
                    return transport, agg_state

        raise StateValidationError("No matching transport/agg state pair found")

    except Exception as e:
        raise StateValidationError(f"Failed to find UTxO pair: {e}") from e


def is_oracle_closing(settings: OracleSettingsDatum) -> bool:
    """Check if oracle is in closing period.

    Args:
        settings: Oracle settings datum

    Returns:
        bool: True if oracle is in closing period
    """
    return not isinstance(settings.closing_period_started_at, NoDatum)


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
            transport.output.datum.variant, RewardTransportVariant
        ) or not isinstance(
            transport.output.datum.variant.datum, RewardConsensusPending
        ):
            return False

        pending_data = transport.output.datum.variant.datum
        message_time = pending_data.message.timestamp

        return current_time >= message_time + liveness_period

    except Exception as e:
        raise StateValidationError(f"Failed to validate reward processing: {e}") from e


def validate_transport_sequence(transport: UTxO, agg_state: UTxO) -> bool:
    """Validate sequence numbers match between transport and agg state.

    Args:
        transport: Transport UTxO
        agg_state: Aggregation state UTxO

    Returns:
        bool: True if sequence numbers match

    Raises:
        StateValidationError: If validation fails
    """
    try:
        # Extract token names which contain sequence numbers
        transport_tokens = _get_nft_token_names(transport)
        agg_state_tokens = _get_nft_token_names(agg_state)

        if not transport_tokens or not agg_state_tokens:
            return False

        # Compare sequence parts of token names
        transport_seq = transport_tokens[0].split("_")[-1]
        agg_state_seq = agg_state_tokens[0].split("_")[-1]

        return transport_seq == agg_state_seq

    except Exception as e:
        raise StateValidationError(f"Failed to validate sequence: {e}") from e


def _get_nft_token_names(utxo: UTxO) -> list[str]:
    """Extract NFT token names from UTxO."""
    if not utxo.output.amount.multi_asset:
        return []

    token_names = []
    for policy_tokens in utxo.output.amount.multi_asset.values():
        for token_name, quantity in policy_tokens.items():
            if quantity == 1:
                try:
                    token_names.append(token_name.decode())
                except UnicodeDecodeError:
                    continue
    return token_names


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
        current_type = type(current_datum.variant.datum).__name__
        next_type = type(next_datum.variant.datum).__name__

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
        # Check sequence numbers match
        if not validate_transport_sequence(transport, agg_state):
            return False

        # Validate state combinations
        transport_variant = transport.output.datum.variant
        agg_state_variant = agg_state.output.datum.variant

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
