# Copyright 2024 Coinbase; 2026 x402 Foundation; GoPlausible (x402-avm). Licensed under the Apache License 2.0.
# Modified in 2026 by x402-avm contributors for x402-algorand: accept any algorand:<genesis hash> network (LocalNet, private networks).
# Changes are listed in the NOTICE file.
"""AVM mechanism utility functions.

Provides encoding, decoding, validation, and network utilities
for working with Algorand transactions.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from decimal import Decimal
from typing import Any

from x402_algorand.constants import (
    ALGORAND_MAINNET_CAIP2,
    ALGORAND_TESTNET_CAIP2,
    AVM_ADDRESS_REGEX,
    BLOCKED_TXN_TYPES,
    DEFAULT_DECIMALS,
    GENESIS_HASH_TO_NETWORK,
    NETWORK_CONFIGS,
    SUPPORTED_NETWORKS,
    TXN_TYPE_ASSET_TRANSFER,
    TXN_TYPE_PAYMENT,
    USDC_MAINNET_ASA_ID,
    USDC_TESTNET_ASA_ID,
    V1_TO_V2_NETWORK_MAP,
)
from x402_algorand.errors import NetworkError, TransactionDecodeError
from x402_algorand.types import DecodedTransactionInfo, TransactionGroupInfo

try:
    from algosdk import encoding, transaction
    from algosdk import error as algosdk_error
except ImportError as e:  # pragma: no cover - py-algorand-sdk is a hard dependency
    raise ImportError(
        "x402-algorand requires py-algorand-sdk. Install with: pip install x402-algorand"
    ) from e

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

logger = logging.getLogger("x402_algorand")


def is_valid_address(address: str) -> bool:
    """Validate an Algorand address format.

    Args:
        address: String to validate.

    Returns:
        True if valid Algorand address format.
    """
    if not address or not isinstance(address, str):
        return False

    if not re.match(AVM_ADDRESS_REGEX, address):
        return False

    try:
        encoding.decode_address(address)
        return True
    except (
        algosdk_error.WrongChecksumError,
        algosdk_error.WrongKeyLengthError,
        binascii.Error,
        ValueError,
    ):
        return False


def caip2_from_genesis_hash(genesis_hash: str | bytes) -> str:
    """Derive CAIP-2 network identifier from an Algorand genesis hash.

    Following the Algorand CAIP-2 profile, the reference is the first 32
    characters of the URL-safe base64 encoding of the raw 32-byte genesis hash.

    Args:
        genesis_hash: 32-byte genesis hash (raw bytes or base64-encoded string).

    Returns:
        CAIP-2 network identifier (e.g. "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k").

    Raises:
        TypeError: If ``genesis_hash`` is neither ``str`` nor ``bytes``.
        NetworkError: If ``genesis_hash`` is not valid base64.
    """
    try:
        if isinstance(genesis_hash, str):
            raw = base64.b64decode(genesis_hash.replace("-", "+").replace("_", "/"))
        elif isinstance(genesis_hash, (bytes, bytearray)):
            if len(genesis_hash) == 32:
                raw = bytes(genesis_hash)
            else:
                raw = base64.b64decode(genesis_hash)
        else:
            raise TypeError(f"Expected str or bytes, got {type(genesis_hash)}")
    except binascii.Error as e:
        raise NetworkError(f"Invalid genesis hash: {e}") from e
    return "algorand:" + base64.urlsafe_b64encode(raw).decode()[:32]


def register_network(
    genesis_hash: str | bytes,
    genesis_id: str = "",
    algod_url: str | None = None,
    indexer_url: str | None = None,
) -> str:
    """Register a custom Algorand network (e.g. LocalNet or private network).

    Computes the CAIP-2 identifier, updates NETWORK_CONFIGS, GENESIS_HASH_TO_NETWORK,
    and SUPPORTED_NETWORKS.

    Args:
        genesis_hash: 32-byte genesis hash (base64 string or raw bytes).
        genesis_id: Genesis ID string (e.g. "dockernet-v1").
        algod_url: Algod endpoint URL (defaults to "http://localhost:4001").
        indexer_url: Indexer endpoint URL (defaults to "http://localhost:8980").

    Returns:
        The registered CAIP-2 network identifier.
    """
    if isinstance(genesis_hash, (bytes, bytearray)):
        gh_b64 = base64.b64encode(genesis_hash).decode()
    else:
        gh_b64 = str(genesis_hash)

    net_id = caip2_from_genesis_hash(genesis_hash)

    if net_id not in NETWORK_CONFIGS:
        NETWORK_CONFIGS[net_id] = {
            "algod_url": algod_url or "http://localhost:4001",
            "indexer_url": indexer_url or "http://localhost:8980",
            "genesis_hash": gh_b64,
            "genesis_id": genesis_id,
            "default_asset": {"asa_id": 0, "name": "ALGO", "decimals": 6},
        }

    GENESIS_HASH_TO_NETWORK[gh_b64] = net_id

    if net_id not in SUPPORTED_NETWORKS:
        SUPPORTED_NETWORKS.append(net_id)

    return net_id


def normalize_network(network: str) -> str:
    """Normalize network identifier to CAIP-2 format.

    Args:
        network: Network identifier (V1 name, legacy long CAIP-2, or short CAIP-2).

    Returns:
        CAIP-2 network identifier.

    Raises:
        NetworkError: If network is not supported or invalid format
            (subclass of ``ValueError``).
    """
    if not isinstance(network, str):
        raise NetworkError(f"Invalid network type: {type(network)}")

    # V1 name mapping
    if network in V1_TO_V2_NETWORK_MAP:
        return V1_TO_V2_NETWORK_MAP[network]

    # Legacy long id: algorand:<44 chars ending "=">
    if network.startswith("algorand:") and len(network) == 53 and network.endswith("="):
        gh = network[9:]
        register_network(gh)
        return caip2_from_genesis_hash(gh)

    # Valid short id: ^algorand:[-_A-Za-z0-9]{1,32}$
    if re.match(r"^algorand:[-_A-Za-z0-9]{1,32}$", network):
        return network

    raise NetworkError(f"Unsupported network: {network}")


def is_valid_network(network: str) -> bool:
    """Check if a network identifier is valid.

    Args:
        network: Network identifier.

    Returns:
        True if network is supported.
    """
    try:
        normalize_network(network)
        return True
    except NetworkError:
        return False


def get_network_config(network: str) -> dict[str, Any]:
    """Get configuration for a network.

    Args:
        network: Network identifier (V1 name or CAIP-2).

    Returns:
        NetworkConfig dictionary.

    Raises:
        NetworkError: If network is not supported (subclass of ``ValueError``).
    """
    caip2 = normalize_network(network)
    config = NETWORK_CONFIGS.get(caip2)
    if not config:
        raise NetworkError(f"Unsupported network: {network}")
    return dict(config)


def get_usdc_asa_id(network: str) -> int:
    """Get the USDC ASA ID for a network.

    Args:
        network: Network identifier.

    Returns:
        USDC ASA ID.

    Raises:
        NetworkError: If network is not supported (subclass of ``ValueError``).
    """
    caip2 = normalize_network(network)
    config = NETWORK_CONFIGS.get(caip2)
    if not config:
        raise NetworkError(f"Unsupported network: {network}")
    return config["default_asset"]["asa_id"]


def get_genesis_hash(network: str) -> str:
    """Get the full base64 genesis hash for a network.

    Args:
        network: Network identifier (legacy long ID, short CAIP-2 ID, or V1 name).

    Returns:
        Base64-encoded 32-byte genesis hash.

    Raises:
        NetworkError: If network is unknown or unregistered (subclass of ``ValueError``).
    """
    if (
        isinstance(network, str)
        and network.startswith("algorand:")
        and len(network) == 53
        and network.endswith("=")
    ):
        return network[9:]

    norm = normalize_network(network)
    config = NETWORK_CONFIGS.get(norm)
    if not config or "genesis_hash" not in config:
        raise NetworkError(f"unknown network {norm}: call register_network(genesis_hash) first")
    return config["genesis_hash"]


def network_from_genesis_hash(genesis_hash: str) -> str | None:
    """Determine CAIP-2 network from genesis hash.

    Args:
        genesis_hash: Base64-encoded genesis hash.

    Returns:
        CAIP-2 network identifier or None if unknown.
    """
    return GENESIS_HASH_TO_NETWORK.get(genesis_hash)


def parse_money_to_decimal(money: str | float | int) -> float:
    """Parse money value to decimal.

    Args:
        money: Money value (string, float, or int).

    Returns:
        Decimal amount.
    """
    if isinstance(money, str):
        # Remove currency symbols and whitespace
        cleaned = money.strip().lstrip("$").replace(",", "")
        return float(Decimal(cleaned))
    return float(money)


def to_atomic_amount(amount: float, decimals: int = DEFAULT_DECIMALS) -> int:
    """Convert decimal amount to atomic units.

    Args:
        amount: Decimal amount.
        decimals: Number of decimal places.

    Returns:
        Amount in atomic units (smallest unit).
    """
    return int(Decimal(str(amount)) * Decimal(10**decimals))


def from_atomic_amount(amount: int, decimals: int = DEFAULT_DECIMALS) -> float:
    """Convert atomic units to decimal amount.

    Args:
        amount: Amount in atomic units.
        decimals: Number of decimal places.

    Returns:
        Decimal amount.
    """
    return float(Decimal(amount) / Decimal(10**decimals))


def decode_transaction_bytes(txn_bytes: bytes) -> DecodedTransactionInfo:
    """Decode transaction bytes to DecodedTransactionInfo.

    Handles both signed and unsigned transactions.

    Args:
        txn_bytes: Msgpack-encoded transaction bytes.

    Returns:
        DecodedTransactionInfo with extracted data.

    Raises:
        TransactionDecodeError: If decoding fails (subclass of ``ValueError``).
    """
    try:
        # Note: msgpack_decode expects a base64 string, so encode the raw bytes
        b64_encoded = base64.b64encode(txn_bytes).decode("utf-8")
        decoded = encoding.msgpack_decode(b64_encoded)
    except Exception as e:  # untrusted input: msgpack/algosdk raise many types
        raise TransactionDecodeError(f"Failed to decode transaction: {e}") from e

    # Determine if signed or unsigned
    is_signed = False
    txn_dict: dict[str, Any]

    if isinstance(decoded, transaction.SignedTransaction):
        is_signed = decoded.signature is not None
        txn_dict = decoded.transaction.dictify()
    elif isinstance(decoded, (transaction.MultisigTransaction, transaction.LogicSigTransaction)):
        # k-of-n multisig and logic signatures are valid authorizations per the spec.
        is_signed = True
        txn_dict = decoded.transaction.dictify()
    elif isinstance(decoded, transaction.Transaction):
        txn_dict = decoded.dictify()
    else:
        raise TransactionDecodeError(f"Unknown transaction format: {type(decoded)}")

    # Extract common fields
    txn_type = txn_dict.get("type", "unknown")
    sender_bytes = txn_dict.get("snd", b"")
    sender = encoding.encode_address(sender_bytes) if sender_bytes else ""
    fee = txn_dict.get("fee", 0)
    first_valid = txn_dict.get("fv", 0)
    last_valid = txn_dict.get("lv", 0)

    # Genesis hash
    gh_bytes = txn_dict.get("gh", b"")
    genesis_hash = base64.b64encode(gh_bytes).decode("utf-8") if gh_bytes else ""

    genesis_id = txn_dict.get("gen")

    # Group ID
    group_bytes = txn_dict.get("grp")
    group = base64.b64encode(group_bytes).decode("utf-8") if group_bytes else None

    # Note
    note = txn_dict.get("note")

    # Lease
    lease = txn_dict.get("lx")

    # Rekey-to (SECURITY: should be None)
    rekey_bytes = txn_dict.get("rekey")
    rekey_to = encoding.encode_address(rekey_bytes) if rekey_bytes else None

    # Build base info
    info = DecodedTransactionInfo(
        type=txn_type,
        sender=sender,
        fee=fee,
        first_valid=first_valid,
        last_valid=last_valid,
        genesis_hash=genesis_hash,
        genesis_id=genesis_id,
        group=group,
        is_signed=is_signed,
        note=note,
        lease=lease,
        rekey_to=rekey_to,
    )

    # Extract type-specific fields
    if txn_type == TXN_TYPE_PAYMENT:
        rcv_bytes = txn_dict.get("rcv", b"")
        info.receiver = encoding.encode_address(rcv_bytes) if rcv_bytes else None
        info.amount = txn_dict.get("amt", 0)
        close_bytes = txn_dict.get("close")
        info.close_remainder_to = encoding.encode_address(close_bytes) if close_bytes else None

    elif txn_type == TXN_TYPE_ASSET_TRANSFER:
        info.asset_index = txn_dict.get("xaid", 0)
        arcv_bytes = txn_dict.get("arcv", b"")
        info.asset_receiver = encoding.encode_address(arcv_bytes) if arcv_bytes else None
        info.asset_amount = txn_dict.get("aamt", 0)
        aclose_bytes = txn_dict.get("aclose")
        info.asset_close_to = encoding.encode_address(aclose_bytes) if aclose_bytes else None

    return info


def decode_base64_transaction(b64_txn: str) -> DecodedTransactionInfo:
    """Decode a base64-encoded transaction.

    Args:
        b64_txn: Base64-encoded msgpack transaction.

    Returns:
        DecodedTransactionInfo with extracted data.

    Raises:
        TransactionDecodeError: If decoding fails (subclass of ``ValueError``).
    """
    try:
        txn_bytes = base64.b64decode(b64_txn)
    except (binascii.Error, TypeError, ValueError) as e:
        raise TransactionDecodeError(f"Invalid base64 encoding: {e}") from e

    return decode_transaction_bytes(txn_bytes)


def decode_payment_group(
    payment_group: list[str],
    payment_index: int,
) -> TransactionGroupInfo:
    """Decode a payment group from base64 strings.

    Args:
        payment_group: List of base64-encoded transactions.
        payment_index: Index of the payment transaction.

    Returns:
        TransactionGroupInfo with all decoded transactions.

    Raises:
        TransactionDecodeError: If decoding fails (subclass of ``ValueError``).
    """
    transactions: list[DecodedTransactionInfo] = []
    total_fee = 0
    group_id: str | None = None
    has_fee_payer = False
    fee_payer_index: int | None = None

    for i, b64_txn in enumerate(payment_group):
        txn_info = decode_base64_transaction(b64_txn)
        transactions.append(txn_info)
        total_fee += txn_info.fee

        # Capture group ID from first transaction
        if i == 0 and txn_info.group:
            group_id = txn_info.group

        # Detect fee payer transaction (self-payment with no amount)
        if (
            txn_info.type == TXN_TYPE_PAYMENT
            and txn_info.receiver == txn_info.sender
            and (txn_info.amount == 0 or txn_info.amount is None)
        ):
            has_fee_payer = True
            fee_payer_index = i

    return TransactionGroupInfo(
        transactions=transactions,
        group_id=group_id,
        total_fee=total_fee,
        has_fee_payer=has_fee_payer,
        fee_payer_index=fee_payer_index,
        payment_index=payment_index,
    )


def is_blocked_transaction_type(txn_type: str) -> bool:
    """Check if a transaction type is blocked for security.

    Args:
        txn_type: Transaction type string.

    Returns:
        True if the transaction type is blocked.
    """
    return txn_type in BLOCKED_TXN_TYPES


def validate_no_security_risks(txn_info: DecodedTransactionInfo) -> str | None:
    """Validate that a transaction has no security risks (per-transaction checks).

    Checks for:
    - Close-to operations (draining accounts)
    - Blocked transaction types (keyreg)

    Note: Rekey operations are validated at group level by validate_rekey_operations()
    which allows balanced sandwich patterns (rekey A->B then rekey back to A).

    Args:
        txn_info: Decoded transaction info.

    Returns:
        Error code string if security risk found, None otherwise.
    """
    from x402_algorand.constants import (
        ERR_BLOCKED_TXN_TYPE,
        ERR_CLOSE_TO_DETECTED,
    )

    # Check for close-to
    if txn_info.type == TXN_TYPE_PAYMENT and txn_info.close_remainder_to:
        return ERR_CLOSE_TO_DETECTED

    if txn_info.type == TXN_TYPE_ASSET_TRANSFER and txn_info.asset_close_to:
        return ERR_CLOSE_TO_DETECTED

    # Check for blocked types
    if is_blocked_transaction_type(txn_info.type):
        return ERR_BLOCKED_TXN_TYPE

    return None


def validate_rekey_operations(txns: list[DecodedTransactionInfo]) -> str | None:
    """Validate rekey operations in a transaction group.

    Only allows balanced sandwich patterns: rekey A->B followed by rekey B->A
    (same sender rekeys back to self). Unbalanced or unpaired rekeys are rejected.

    Args:
        txns: List of decoded transaction info for the entire group.

    Returns:
        Error code string if invalid rekey detected, None otherwise.
    """
    from x402_algorand.constants import ERR_REKEY_DETECTED

    # Collect all rekey operations
    rekey_ops: list[dict[str, Any]] = []
    for i, txn in enumerate(txns):
        if txn.rekey_to:
            rekey_ops.append({"index": i, "from": txn.sender, "to": txn.rekey_to})

    if not rekey_ops:
        return None

    # Must have an even number of rekey operations for balanced sandwiches
    if len(rekey_ops) % 2 != 0:
        return ERR_REKEY_DETECTED

    # Group rekey operations by sender and verify each pair forms a sandwich
    rekeys_by_sender: dict[str, list[dict[str, Any]]] = {}
    for op in rekey_ops:
        rekeys_by_sender.setdefault(op["from"], []).append(op)

    for sender, ops in rekeys_by_sender.items():
        if len(ops) != 2:
            return ERR_REKEY_DETECTED

        _first, second = ops
        # The second rekey must return authority to the sender itself.
        if second["to"] != sender:
            return ERR_REKEY_DETECTED

    return None


def _bytes_to_sign(txn: transaction.Transaction) -> bytes:
    """Return ``b"TX" + canonical msgpack`` for a transaction (what ed25519 signs)."""
    return b"TX" + base64.b64decode(encoding.msgpack_encode(txn))


def verify_transaction_signature(b64_txn: str) -> tuple[bool, str]:
    """Verify that a signed transaction is authorized by its sender (or auth address).

    Algorand signs ``b"TX" + canonical_msgpack(transaction)``. Supported authorizations
    (as allowed by the exact scheme spec):

    - single ed25519 signature, by the sender or by its ``sgnr`` auth address (rekeyed account);
    - k-of-n multisig: at least ``threshold`` valid subsignatures;
    - logic signature: delegated signature checked, or program hash equal to the
      authorizing address. The program itself is evaluated by ``simulate``.

    Args:
        b64_txn: Base64-encoded signed transaction.

    Returns:
        Tuple of (is_valid, error_message). Returns (True, "") on success.
    """
    try:
        decoded = encoding.msgpack_decode(b64_txn)
    except Exception:  # untrusted input: msgpack/algosdk raise many types
        logger.debug("could not decode transaction for signature check", exc_info=True)
        return False, "Failed to decode transaction"

    try:
        return _check_authorization(decoded)
    except _SIGNATURE_CHECK_ERRORS:
        logger.debug("signature check failed", exc_info=True)
        return False, "Signature does not match sender"


_SIGNATURE_CHECK_ERRORS = (
    BadSignatureError,
    ValueError,
    TypeError,
    algosdk_error.WrongChecksumError,
    algosdk_error.WrongKeyLengthError,
)


def _check_authorization(decoded: Any) -> tuple[bool, str]:
    if isinstance(decoded, transaction.SignedTransaction):
        if not decoded.signature:
            return False, "Transaction has no signature"
        signer_address = decoded.authorizing_address or decoded.transaction.sender
        sig_bytes = base64.b64decode(decoded.signature)
        signer_pk = encoding.decode_address(signer_address)
        VerifyKey(signer_pk).verify(_bytes_to_sign(decoded.transaction), sig_bytes)
        return True, ""

    if isinstance(decoded, transaction.MultisigTransaction):
        if decoded.multisig.verify(_bytes_to_sign(decoded.transaction)):
            return True, ""
        return False, "Multisig signature is invalid or below threshold"

    if isinstance(decoded, transaction.LogicSigTransaction):
        if decoded.verify():
            return True, ""
        return False, "Logic signature is invalid"

    return False, "Transaction has no signature"


def validate_fee_payer_transaction(
    txn_info: DecodedTransactionInfo,
    expected_fee_payer: str,
) -> str | None:
    """Validate a fee payer transaction.

    Per spec, fee payer transaction must be:
    - Type "pay" (payment)
    - Sender is the fee payer
    - Receiver is the fee payer (self-payment)
    - Amount is 0 (no value transfer)
    - No close-to field
    - No rekey field
    - Fee is reasonable (covers pooled fees)

    Args:
        txn_info: Decoded transaction info.
        expected_fee_payer: Expected fee payer address.

    Returns:
        Error code string if invalid, None otherwise.
    """
    from x402_algorand.constants import (
        ERR_FEE_PAYER_HAS_AMOUNT,
        ERR_FEE_PAYER_HAS_CLOSE,
        ERR_FEE_PAYER_HAS_REKEY,
        ERR_FEE_PAYER_INVALID_TXN,
    )

    # Must be payment type
    if txn_info.type != TXN_TYPE_PAYMENT:
        return ERR_FEE_PAYER_INVALID_TXN

    # Sender must be fee payer
    if txn_info.sender != expected_fee_payer:
        return ERR_FEE_PAYER_INVALID_TXN

    # Receiver must be fee payer (self-payment)
    if txn_info.receiver != expected_fee_payer:
        return ERR_FEE_PAYER_INVALID_TXN

    # Amount must be 0
    if txn_info.amount and txn_info.amount > 0:
        return ERR_FEE_PAYER_HAS_AMOUNT

    # No close-to
    if txn_info.close_remainder_to:
        return ERR_FEE_PAYER_HAS_CLOSE

    # No rekey
    if txn_info.rekey_to:
        return ERR_FEE_PAYER_HAS_REKEY

    # Fee must be reasonable (prevents fee extraction attacks)
    from x402_algorand.constants import MAX_REASONABLE_FEE

    if txn_info.fee > MAX_REASONABLE_FEE:
        return ERR_FEE_PAYER_INVALID_TXN

    return None


def encode_transaction_group(
    txn_bytes_list: list[bytes],
) -> list[str]:
    """Encode a list of transaction bytes to base64 strings.

    Args:
        txn_bytes_list: List of msgpack-encoded transaction bytes.

    Returns:
        List of base64-encoded strings.
    """
    return [base64.b64encode(txn_bytes).decode("utf-8") for txn_bytes in txn_bytes_list]


def get_default_usdc_info(network: str) -> dict[str, Any]:
    """Get default USDC asset info for a network.

    Args:
        network: Network identifier.

    Returns:
        Asset info dictionary with asa_id, name, decimals.
    """
    caip2 = normalize_network(network)

    if caip2 == ALGORAND_MAINNET_CAIP2:
        return {
            "asa_id": USDC_MAINNET_ASA_ID,
            "name": "USDC",
            "decimals": DEFAULT_DECIMALS,
        }
    elif caip2 == ALGORAND_TESTNET_CAIP2:
        return {
            "asa_id": USDC_TESTNET_ASA_ID,
            "name": "USDC",
            "decimals": DEFAULT_DECIMALS,
        }
    else:
        raise NetworkError(f"Unknown network: {network}")
