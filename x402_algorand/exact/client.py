# Copyright 2024 Coinbase; 2026 x402 Foundation; GoPlausible (x402-avm). Licensed under the Apache License 2.0.
# Modified in 2026 by the AI Economy Team for x402-algorand: native ALGO payments (asset 0); algod token.
# Changes are listed in the NOTICE file.
"""AVM client implementation for the Exact payment scheme (V2).

Creates atomic transaction groups for ASA payments, optionally with
fee abstraction (gasless transactions).
"""

from __future__ import annotations

import base64
import time
from typing import TYPE_CHECKING, Any

try:
    from algosdk import encoding, transaction
    from algosdk.v2client import algod
except ImportError as e:
    raise ImportError(
        "AVM mechanism requires py-algorand-sdk. Install with: pip install x402-avm[avm]"
    ) from e

from x402.schemas import PaymentRequirements

from x402_algorand.constants import DEFAULT_ASSETS, NETWORK_CONFIGS, SCHEME_EXACT
from x402_algorand.signer import ClientAvmSigner
from x402_algorand.types import ExactAvmPayload
from x402_algorand.utils import caip2_from_genesis_hash, normalize_network

if TYPE_CHECKING:
    pass


class ExactAvmScheme:
    """AVM client implementation for the Exact payment scheme (V2).

    Implements SchemeNetworkClient protocol. Returns the inner payload dict,
    which x402Client wraps into a full PaymentPayload.

    Creates atomic transaction groups for ASA payments:
    - Without fee abstraction: Single ASA transfer transaction
    - With fee abstraction: [Fee payer txn (unsigned), ASA transfer (signed)]

    Attributes:
        scheme: The scheme identifier ("exact").
    """

    scheme = SCHEME_EXACT

    def __init__(
        self, signer: ClientAvmSigner, algod_url: str | None = None, algod_token: str | None = None
    ):
        """Create ExactAvmScheme.

        Args:
            signer: AVM signer for payment authorizations.
            algod_url: Optional custom Algod URL.
            algod_token: Optional custom Algod token.
        """
        self._signer = signer
        self._custom_algod_url = algod_url
        self._custom_algod_token = algod_token
        self._clients: dict[str, algod.AlgodClient] = {}

    def _get_client(self, network: str) -> algod.AlgodClient:
        """Get or create Algod client for network."""
        caip2_network = normalize_network(network)

        if caip2_network in self._clients:
            return self._clients[caip2_network]

        if self._custom_algod_url:
            algod_url = self._custom_algod_url
        else:
            config = NETWORK_CONFIGS.get(caip2_network)
            if not config:
                raise ValueError(f"Unsupported network: {network}")
            algod_url = config["algod_url"]

        algod_token = self._custom_algod_token if self._custom_algod_token is not None else ""
        client = algod.AlgodClient(algod_token, algod_url)
        self._clients[caip2_network] = client
        return client

    def create_payment_payload(
        self,
        requirements: PaymentRequirements,
    ) -> dict[str, Any]:
        """Create atomic transaction group for payment.

        If feePayer in requirements.extra:
          - Creates 2-txn group: [fee_payer_txn (unsigned), asa_transfer (signed)]
          - Fee payer covers all fees (pooled: minFee * 2)
          - Client signs only ASA transfer

        Else:
          - Creates single ASA transfer with normal fee
          - Client signs the transaction

        Args:
            requirements: Payment requirements from server.

        Returns:
            Inner payload dict (paymentGroup, paymentIndex).
            x402Client wraps this with x402_version, accepted, resource, extensions.

        Raises:
            ValueError: If network is unsupported.
        """
        network = str(requirements.network)
        client = self._get_client(network)

        # Get suggested params
        sp = client.suggested_params()
        if caip2_from_genesis_hash(sp.gh) != normalize_network(network):
            raise ValueError(
                f"algod is on {caip2_from_genesis_hash(sp.gh)} but the payment is for {network}"
            )

        # Check for fee abstraction
        extra = requirements.extra or {}
        fee_payer = extra.get("feePayer")

        transactions: list[transaction.Transaction] = []
        payment_index: int

        if fee_payer:
            # === Fee Abstraction Mode ===
            # Fee payer transaction: self-payment with pooled fees
            total_txn_count = 2
            min_fee = sp.min_fee or 1000
            pooled_fee = min_fee * total_txn_count

            # Create suggested params for fee payer (with pooled fee)
            fee_payer_sp = transaction.SuggestedParams(
                fee=pooled_fee,
                flat_fee=True,  # CRITICAL: Prevent fee recalculation
                first=sp.first,
                last=sp.last,
                gh=sp.gh,
                gen=sp.gen,
                min_fee=sp.min_fee,
            )

            fee_payer_txn = transaction.PaymentTxn(
                sender=fee_payer,
                sp=fee_payer_sp,
                receiver=fee_payer,  # Self-payment
                amt=0,
                note=f"x402-fee-payer-{time.time_ns()}".encode(),
            )
            transactions.append(fee_payer_txn)

            # ASA transfer with zero fee (fee payer covers)
            asset_sp = transaction.SuggestedParams(
                fee=0,
                flat_fee=True,  # CRITICAL: Prevent fee recalculation
                first=sp.first,
                last=sp.last,
                gh=sp.gh,
                gen=sp.gen,
                min_fee=sp.min_fee,
            )

            # Payment index is the ASA transfer (index 1 in group)
            payment_index = 1
        else:
            # === Normal Mode ===
            asset_sp = sp
            # Payment index is 0 (single transaction)
            payment_index = 0

        asset_id = int(requirements.asset)
        if asset_id == 0:
            transfer = transaction.PaymentTxn(
                sender=self._signer.address,
                sp=asset_sp,
                receiver=requirements.pay_to,
                amt=int(requirements.amount),
                note=f"x402-payment-{time.time_ns()}".encode(),
            )
        else:
            transfer = transaction.AssetTransferTxn(
                sender=self._signer.address,
                sp=asset_sp,
                receiver=requirements.pay_to,
                amt=int(requirements.amount),
                index=asset_id,
                note=f"x402-payment-{time.time_ns()}".encode(),
            )
        transactions.append(transfer)

        # Assign group ID if multiple transactions
        if len(transactions) > 1:
            transactions = transaction.assign_group_id(transactions)

        # Determine which transactions client should sign
        # (all transactions where sender is client's address)
        # Note: txn.sender is already a string address in py-algorand-sdk
        client_indexes = [
            i for i, txn in enumerate(transactions) if txn.sender == self._signer.address
        ]

        # Get unsigned transaction bytes
        # Note: encoding.msgpack_encode returns base64 string, convert to actual bytes
        # IMPORTANT: Encode Transaction objects directly, not dictionaries!
        unsigned_bytes_list: list[bytes] = []
        for txn in transactions:
            # Encode the Transaction object directly (not txn.dictify())
            b64_encoded = encoding.msgpack_encode(txn)
            unsigned_bytes_list.append(base64.b64decode(b64_encoded))

        # Sign client's transactions
        signed_results = self._signer.sign_transactions(unsigned_bytes_list, client_indexes)

        # Build payment group: signed where applicable, unsigned for fee payer
        payment_group: list[str] = []
        for i, txn_bytes in enumerate(unsigned_bytes_list):
            signed = signed_results[i]
            if signed:
                # Use signed transaction (already bytes from signer)
                payment_group.append(base64.b64encode(signed).decode("utf-8"))
            else:
                # Use unsigned transaction (fee payer will sign)
                payment_group.append(base64.b64encode(txn_bytes).decode("utf-8"))

        payload = ExactAvmPayload(
            payment_group=payment_group,
            payment_index=payment_index,
        )

        return payload.to_dict()

    def find_default_asset(self, asset: str, network: str) -> dict[str, Any] | None:
        """Find default asset info for spend controls.

        Returns the shape of official x402 ExactDefaultAssetInfo:
        {asset, name, version, decimals, symbol}.

        - asset "0" on ANY Algorand network -> Algo (decimals 6)
        - USDC (31566704 on MainNet / 10458941 on TestNet) -> USD Coin (decimals 6)
        - anything else -> None

        Args:
            asset: Asset identifier ("0" for ALGO or ASA ID).
            network: CAIP-2 or legacy V1 network identifier.

        Returns:
            Matching default asset dict or None.
        """
        return find_default_asset(asset, network)


def find_default_asset(asset: str, network: str) -> dict[str, Any] | None:
    """Find default asset info for Algorand spend controls.

    Returns the shape of official x402 ExactDefaultAssetInfo:
    {asset, name, version, decimals, symbol}.

    - asset "0" on ANY Algorand network -> Algo (decimals 6)
    - USDC (31566704 on MainNet / 10458941 on TestNet) -> USD Coin (decimals 6)
    - anything else -> None

    Args:
        asset: Asset identifier ("0" for ALGO or ASA ID).
        network: CAIP-2 or legacy V1 network identifier.

    Returns:
        Matching default asset dict or None.
    """
    try:
        norm_net = normalize_network(network)
    except Exception:
        return None

    asset_str = str(asset)
    if asset_str == "0":
        return {
            "asset": "0",
            "name": "Algo",
            "version": "1",
            "decimals": 6,
            "symbol": "ALGO",
        }

    for entry in DEFAULT_ASSETS.get(norm_net, []):
        if entry["asset"] == asset_str:
            return dict(entry)

    return None
