"""Platform authorization NFT transaction builder."""

import logging
from dataclasses import dataclass

from pycardano import (
    Address,
    MultiAsset,
    PaymentSigningKey,
    Transaction,
    TransactionBuilder,
    TransactionOutput,
    Value,
)

from charli3_offchain_core.blockchain.chain_query import ChainQuery
from charli3_offchain_core.blockchain.transactions import TransactionManager
from charli3_offchain_core.platform.auth.token_script_builder import PlatformAuthScript

logger = logging.getLogger(__name__)


@dataclass
class AuthBuildResult:
    """Result of authorization NFT build process"""

    transaction: Transaction
    policy_id: bytes
    platform_address: Address


class PlatformAuthBuilder:
    """Builds transactions for platform authorization NFT"""

    TOKEN_NAME = b"AuthPNFTC3"
    MIN_UTXO_VALUE = 2_000_000
    REFERENCE_ADA_AMOUNT = 5_000_000

    def __init__(
        self,
        chain_query: ChainQuery,
        tx_manager: TransactionManager,
        script_builder: PlatformAuthScript,
    ) -> None:
        self.chain_query = chain_query
        self.tx_manager = tx_manager
        self.script_builder = script_builder

    async def build_auth_transaction(
        self,
        sender_address: Address,
        signing_key: PaymentSigningKey,
        metadata: dict | None = None,
    ) -> AuthBuildResult:
        """Build transaction to mint platform authorization NFT."""
        # Build scripts
        validity_slot, minting_script = self.script_builder.build_minting_script()
        spending_script = self.script_builder.build_spending_script()
        platform_address = self.script_builder.script_address()

        # Create token parameters
        script_hash = minting_script.hash()
        token_value = Value(self.MIN_UTXO_VALUE)
        token_value.multi_asset = MultiAsset.from_primitive(
            {bytes(script_hash): {self.TOKEN_NAME: 1}}
        )

        builder = TransactionBuilder(
            self.chain_query.context,
            auxiliary_data=metadata if metadata else None,
        )

        builder.ttl = validity_slot
        builder.mint = token_value.multi_asset
        builder.add_minting_script(minting_script)

        builder.add_output(
            TransactionOutput(address=platform_address, amount=token_value)
        )

        builder.native_scripts = [spending_script]

        # builder.add_output(
        #     TransactionOutput(
        #         address=platform_address, amount=self.REFERENCE_ADA_AMOUNT, script=spending_script
        #     )
        # )

        # Build and return result
        tx = await self.tx_manager.build_tx(
            builder=builder,
            change_address=sender_address,
            signing_key=signing_key,
        )

        return AuthBuildResult(
            transaction=tx,
            policy_id=script_hash.payload.hex(),
            platform_address=platform_address,
        )
