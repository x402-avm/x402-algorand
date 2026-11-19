# Copyright 2024 Coinbase; 2026 x402 Foundation; GoPlausible (x402-avm). Licensed under the Apache License 2.0.
# Modified in 2026 by x402-avm contributors for x402-algorand.
# Changes are listed in the NOTICE file.
"""AVM (Algorand Virtual Machine) mechanism for x402 Python SDK.

This module provides Algorand blockchain integration for the x402 payment protocol.
It supports both V2 (CAIP-2 network identifiers) and V1 (legacy network names)
through backward compatibility wrappers.

Features:
- Atomic transaction groups (up to 16 transactions)
- ASA (Algorand Standard Assets) transfers
- Optional fee abstraction (gasless transactions)
- Instant finality (no consensus forks)
- Ed25519 signature verification
- Configurable Algod/Indexer URLs via environment variables

Environment Variables:
    ALGOD_MAINNET_URL: Custom Algod URL for mainnet (default: AlgoNode)
    ALGOD_TESTNET_URL: Custom Algod URL for testnet (default: AlgoNode)
    INDEXER_MAINNET_URL: Custom Indexer URL for mainnet (default: AlgoNode)
    INDEXER_TESTNET_URL: Custom Indexer URL for testnet (default: AlgoNode)

Usage:
    ```python
    import os

    from x402 import x402Client
    from x402_algorand import PayerAvmSigner
    from x402_algorand.exact import register_exact_avm_client

    signer = PayerAvmSigner.from_mnemonic(os.environ["PAYER_MNEMONIC"])
    client = x402Client()
    register_exact_avm_client(client, signer)
    ```
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

# Submodule exports
from x402_algorand import exact
from x402_algorand.constants import (
    ALGORAND_MAINNET_CAIP2,
    ALGORAND_TESTNET_CAIP2,
    DEFAULT_ASSETS,
    DEFAULT_DECIMALS,
    MAX_GROUP_SIZE,
    MIN_TXN_FEE,
    NETWORK_CONFIGS,
    SCHEME_EXACT,
    SUPPORTED_NETWORKS,
    USDC_MAINNET_ASA_ID,
    USDC_TESTNET_ASA_ID,
    V1_NETWORKS,
    V1_TO_V2_NETWORK_MAP,
)

# Exceptions
from x402_algorand.errors import (
    NetworkError,
    NetworkMismatchError,
    SigningError,
    SimulationError,
    TransactionDecodeError,
    X402AlgorandError,
)

# Signer protocols and ready-made implementations
from x402_algorand.signer import (
    ClientAvmSigner,
    FacilitatorAvmSigner,
    PayerAvmSigner,
    ServerAvmSigner,
)

# Types
from x402_algorand.types import (
    DecodedTransactionInfo,
    ExactAvmPayload,
    ExactAvmPayloadV1,
    ExactAvmPayloadV2,
    TransactionGroupInfo,
)

# Utilities
from x402_algorand.utils import (
    caip2_from_genesis_hash,
    decode_base64_transaction,
    decode_payment_group,
    decode_transaction_bytes,
    encode_transaction_group,
    from_atomic_amount,
    get_genesis_hash,
    get_network_config,
    get_usdc_asa_id,
    is_valid_address,
    is_valid_network,
    network_from_genesis_hash,
    normalize_network,
    parse_money_to_decimal,
    register_network,
    to_atomic_amount,
    validate_fee_payer_transaction,
    validate_no_security_risks,
)

try:
    __version__ = _version("x402-algorand")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"

__all__ = [
    "__version__",
    # Exceptions
    "X402AlgorandError",
    "NetworkError",
    "NetworkMismatchError",
    "SigningError",
    "SimulationError",
    "TransactionDecodeError",
    # Constants
    "ALGORAND_MAINNET_CAIP2",
    "ALGORAND_TESTNET_CAIP2",
    "DEFAULT_ASSETS",
    "DEFAULT_DECIMALS",
    "MAX_GROUP_SIZE",
    "MIN_TXN_FEE",
    "NETWORK_CONFIGS",
    "SCHEME_EXACT",
    "SUPPORTED_NETWORKS",
    "USDC_MAINNET_ASA_ID",
    "USDC_TESTNET_ASA_ID",
    "V1_NETWORKS",
    "V1_TO_V2_NETWORK_MAP",
    # Types
    "DecodedTransactionInfo",
    "ExactAvmPayload",
    "ExactAvmPayloadV1",
    "ExactAvmPayloadV2",
    "TransactionGroupInfo",
    # Signers
    "ClientAvmSigner",
    "FacilitatorAvmSigner",
    "PayerAvmSigner",
    "ServerAvmSigner",
    # Utilities
    "caip2_from_genesis_hash",
    "decode_base64_transaction",
    "decode_payment_group",
    "decode_transaction_bytes",
    "encode_transaction_group",
    "from_atomic_amount",
    "get_genesis_hash",
    "get_network_config",
    "get_usdc_asa_id",
    "is_valid_address",
    "is_valid_network",
    "network_from_genesis_hash",
    "normalize_network",
    "parse_money_to_decimal",
    "register_network",
    "to_atomic_amount",
    "validate_fee_payer_transaction",
    "validate_no_security_risks",
    # Submodules
    "exact",
]
