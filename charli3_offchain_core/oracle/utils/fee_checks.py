"""Utilities for fee calculation and validation in oracle transactions."""

from pycardano import ScriptHash, UTxO

from charli3_offchain_core.models.oracle_datums import Asset, FeeConfig
from charli3_offchain_core.oracle.exceptions import FeeCalculationError


def calculate_required_fees(
    node_count: int, fee_config: FeeConfig, platform_percentage: int = 20
) -> tuple[int, int]:
    """Calculate required fees for oracle transaction.

    Args:
        node_count: Number of participating nodes
        fee_config: Fee configuration
        platform_percentage: Platform fee percentage

    Returns:
        Tuple of (node_fees, platform_fees)

    Raises:
        FeeCalculationError: If calculation fails
    """
    if node_count <= 0:
        raise FeeCalculationError("Node count must be positive")

    if platform_percentage < 0 or platform_percentage > 100:
        raise FeeCalculationError("Platform percentage must be between 0 and 100")

    try:
        # Calculate base fees
        total_node_fee = fee_config.reward_prices.node_fee * node_count
        platform_fee = fee_config.reward_prices.platform_fee

        # Apply platform percentage
        platform_share = (total_node_fee * platform_percentage) // 100
        platform_total = platform_fee + platform_share

        return total_node_fee, platform_total

    except Exception as e:
        raise FeeCalculationError(f"Fee calculation failed: {e}") from e


def validate_fee_payment(utxo: UTxO, fee_token: Asset, required_amount: int) -> bool:
    """Validate that UTxO contains sufficient fee payment.

    Args:
        utxo: UTxO to validate
        fee_token: Token used for fee payment
        required_amount: Required fee amount

    Returns:
        bool: True if payment is sufficient

    Raises:
        FeeCalculationError: If validation fails
    """
    if required_amount <= 0:
        raise FeeCalculationError("Required amount must be positive")

    try:
        if not utxo.output.amount.multi_asset:
            return False

        policy_id = ScriptHash(fee_token.policy_id)
        if policy_id not in utxo.output.amount.multi_asset:
            return False

        policy_tokens = utxo.output.amount.multi_asset[policy_id]
        token_name = fee_token.name
        if token_name not in policy_tokens:
            return False

        return policy_tokens[token_name] >= required_amount

    except Exception as e:
        raise FeeCalculationError(f"Fee validation failed: {e}") from e


def calculate_node_reward(
    total_fees: int, valid_node_count: int, fee_config: FeeConfig
) -> int:
    """Calculate reward amount per valid node.

    Args:
        total_fees: Total fees collected
        valid_node_count: Number of valid nodes
        fee_config: Fee configuration

    Returns:
        int: Reward amount per node

    Raises:
        FeeCalculationError: If calculation fails
    """
    if total_fees <= 0:
        raise FeeCalculationError("Total fees must be positive")

    if valid_node_count <= 0:
        raise FeeCalculationError("Valid node count must be positive")

    try:
        # Remove platform fee
        distributable_fees = total_fees - fee_config.reward_prices.platform_fee
        if distributable_fees <= 0:
            raise FeeCalculationError("Insufficient fees after platform fee")

        # Calculate per-node reward
        return distributable_fees // valid_node_count

    except Exception as e:
        raise FeeCalculationError(f"Node reward calculation failed: {e}") from e


def calculate_reward_shares(
    total_amount: int, node_count: int, platform_fee: int
) -> tuple[int, int]:
    """Calculate reward distribution between nodes and platform.

    Args:
        total_amount: Total amount to distribute
        node_count: Number of participating nodes
        platform_fee: Platform fee amount

    Returns:
        Tuple of (node_share, platform_share)

    Raises:
        FeeCalculationError: If calculation fails
    """
    if total_amount <= 0:
        raise FeeCalculationError("Total amount must be positive")

    if node_count <= 0:
        raise FeeCalculationError("Node count must be positive")

    if platform_fee < 0:
        raise FeeCalculationError("Platform fee cannot be negative")

    try:
        # Ensure total amount covers platform fee
        if total_amount <= platform_fee:
            raise FeeCalculationError("Total amount must exceed platform fee")

        # Calculate shares
        remaining = total_amount - platform_fee
        node_share = remaining // node_count
        platform_share = platform_fee + (remaining - (node_share * node_count))

        return node_share, platform_share

    except Exception as e:
        raise FeeCalculationError(f"Reward share calculation failed: {e}") from e
