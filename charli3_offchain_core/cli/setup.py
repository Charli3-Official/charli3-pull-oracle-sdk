import json
from pathlib import Path

from pycardano import (
    Address,
    PaymentSigningKey,
    PaymentVerificationKey,
    StakeVerificationKey,
)

from charli3_offchain_core.cli.config.formatting import format_status_update

from ..blockchain.chain_query import ChainQuery
from ..blockchain.transactions import TransactionManager
from ..platform.auth.orchestrator import (
    PlatformAuthOrchestrator,
    ProcessStatus,
)
from .base import create_chain_context
from .config.keys import KeyManager
from .config.platform import PlatformAuthConfig


def setup_platform_from_config(config: Path, metadata: Path | None) -> tuple[
    PlatformAuthConfig,
    PaymentSigningKey,
    PaymentVerificationKey,
    StakeVerificationKey,
    Address,
    ChainQuery,
    TransactionManager,
    PlatformAuthOrchestrator,
]:
    """Set up all required modules that are common across platform functions from config file."""
    auth_config = PlatformAuthConfig.from_yaml(config)
    payment_sk, payment_vk, stake_vk, default_addr = KeyManager.load_from_config(
        auth_config.network.wallet
    )

    chain_context = create_chain_context(auth_config)
    chain_query = ChainQuery(chain_context)

    tx_manager = TransactionManager(chain_query)

    def status_callback(status: ProcessStatus, message: str) -> None:
        format_status_update(status.name, message)

    orchestrator = PlatformAuthOrchestrator(
        chain_query=chain_query,
        tx_manager=tx_manager,
        status_callback=status_callback,
    )
    meta_data = None
    if metadata:
        with metadata.open() as f:
            meta_data = json.load(f)

    return (
        auth_config,
        payment_sk,
        payment_vk,
        stake_vk,
        default_addr,
        chain_query,
        tx_manager,
        orchestrator,
        meta_data,
    )
