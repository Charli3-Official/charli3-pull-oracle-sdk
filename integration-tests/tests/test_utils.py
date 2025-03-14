"""Shared utilities for Charli3 ODV integration tests."""

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
from pycardano import Address, UTxO

from charli3_offchain_core.platform.auth.token_finder import PlatformAuthFinder

# Configure shared logger for all test modules
logger = logging.getLogger("odv_tests")


def update_config_file(config_path: Path, updates: dict[str, Any]) -> None:
    """Update configuration YAML file with new values.

    Args:
        config_path: Path to the configuration file
        updates: Dictionary of updates in the format {section.key: value}
                 For nested updates use dot notation: "tokens.platform_auth_policy"
    """
    try:
        # Load existing configuration
        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        # Apply updates
        for key_path, value in updates.items():
            parts = key_path.split(".")

            # Navigate to the nested dictionary
            current = config_data
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            # Set the value
            current[parts[-1]] = value

        # Write updated configuration back to file
        with open(config_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False)

        logger.info(f"Configuration file updated: {config_path}")

    except Exception as e:
        logger.error(f"Failed to update configuration file: {e}")
        raise


async def find_platform_auth_nft(
    auth_finder: PlatformAuthFinder,
    policy_id: str,
    addresses: list[str | Address],
) -> UTxO | None:
    """Find platform auth NFT across multiple addresses.

    Args:
        auth_finder: Platform auth finder instance
        policy_id: Policy ID to search for
        addresses: List of addresses to check

    Returns:
        UTxO containing the auth NFT if found, None otherwise
    """
    for address in addresses:
        logger.info(f"Looking for platform auth NFT at address: {address}")
        platform_utxo = await auth_finder.find_auth_utxo(
            policy_id=policy_id,
            platform_address=str(address),
        )

        if platform_utxo:
            logger.info(
                f"Found platform auth NFT in UTxO: "
                f"{platform_utxo.input.transaction_id}#{platform_utxo.input.index}"
            )
            return platform_utxo

    logger.warning("Platform auth NFT not found at any of the provided addresses")
    return None


async def wait_for_indexing(seconds: int = 5) -> None:
    """Wait for blockchain indexers to process recent transactions.

    Args:
        seconds: Number of seconds to wait
    """
    logger.info(f"Waiting {seconds} seconds for UTxOs to be indexed...")
    await asyncio.sleep(seconds)
