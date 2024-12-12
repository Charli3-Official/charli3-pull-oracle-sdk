"""CLI utility functions and decorators."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

import yaml


def setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def async_command(f) -> callable:
    """Decorator to run async click commands."""

    @wraps(f)
    def wrapper(*args, **kwargs) -> None:

        return asyncio.run(f(*args, **kwargs))

    return wrapper


T = TypeVar("T", bound="ConfigFromDict")


@dataclass
class ConfigFromDict:
    """Base class for configurations that can be created from dictionaries."""

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        """Create configuration from dictionary."""
        field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}
        processed_data = {}

        for key, value in data.items():
            if key in field_types:
                field_type = field_types[key]
                if hasattr(field_type, "from_dict") and isinstance(value, dict):
                    processed_data[key] = field_type.from_dict(value)
                else:
                    processed_data[key] = value

        return cls(**processed_data)


def resolve_env_vars(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve environment variables in configuration."""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, dict):
            resolved[key] = resolve_env_vars(value)
        elif isinstance(value, str) and value.startswith("$"):
            env_var = value[1:]  # Remove $ prefix
            resolved[key] = os.environ.get(env_var, value)
        else:
            resolved[key] = value
    return resolved


def load_yaml_config(path: Path | str) -> dict[str, Any]:
    """Load and process YAML configuration file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return resolve_env_vars(data)


def parse_nodes_file(feeds_file: Path) -> tuple[int, list[list[str]]]:
    """
    Parse the feeds JSON file to extract signature_required count and PKH pairs.

    Args:
        feeds_file (Path): Path to the JSON file containing node feeds data

    Returns:
        Tuple[int, List[List[str]]]: A tuple containing:
            - count: The signature_required value
            - nodes: List of [feed_pkh, payment_pkh] pairs for nodes with status 'deploy'
    """
    with open(feeds_file) as f:
        data = json.load(f)

    # Get the signature_required count
    count = data["signature_required"]

    # Process nodes
    nodes = []
    for _, node_data in data["nodes"].items():
        # Skip nodes that don't have 'deploy' status
        if node_data.get("status") != "deploy":
            continue

        # Handle case where there's a single public_key_hash
        if "public_key_hash" in node_data:
            pkh = node_data["public_key_hash"]
            nodes.append([pkh, pkh])  # Use the same PKH for both feed and payment
            continue

        # Handle case with separate feed and payment PKHs
        feed_pkh = node_data.get("feed_public_key_hash")
        payment_pkh = node_data.get("payment_public_key_hash")
        if feed_pkh and payment_pkh:
            nodes.append([feed_pkh, payment_pkh])

    if count > len(nodes):
        raise ValueError(
            f"signature_required ({count}) cannot be greater than the number of nodes with 'deploy' status ({len(nodes)})"
        )
    return count, nodes
