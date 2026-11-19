# Copyright 2024 Coinbase; 2026 x402 Foundation; GoPlausible (x402-avm). Licensed under the Apache License 2.0.
# Modified in 2026 by x402-avm contributors for x402-algorand.
# Changes are listed in the NOTICE file.
"""Exact payment scheme for AVM (Algorand).

Provides client, server, and facilitator implementations
for the exact payment scheme on Algorand networks.

Usage:
    ```python
    from x402 import x402Client, x402Facilitator

    from x402_algorand import ALGORAND_TESTNET_CAIP2, PayerAvmSigner, ServerAvmSigner
    from x402_algorand.exact import register_exact_avm_client, register_exact_avm_facilitator

    client = x402Client()
    register_exact_avm_client(client, PayerAvmSigner.from_mnemonic(payer_words))

    facilitator = x402Facilitator()
    register_exact_avm_facilitator(
        facilitator, ServerAvmSigner.from_mnemonic(server_words), ALGORAND_TESTNET_CAIP2
    )
    ```
"""

# Client scheme
# V1 compatibility
from x402_algorand.exact import v1
from x402_algorand.exact.client import ExactAvmScheme as ExactAvmClientScheme

# Facilitator scheme
from x402_algorand.exact.facilitator import ExactAvmScheme as ExactAvmFacilitatorScheme

# Registration helpers
from x402_algorand.exact.register import (
    register_exact_avm_client,
    register_exact_avm_facilitator,
    register_exact_avm_server,
)

# Server scheme
from x402_algorand.exact.server import ExactAvmScheme as ExactAvmServerScheme

# For convenience, export the main scheme class
# (use the appropriate import for client/server/facilitator)
ExactAvmScheme = ExactAvmClientScheme

__all__ = [
    # Schemes
    "ExactAvmScheme",
    "ExactAvmClientScheme",
    "ExactAvmServerScheme",
    "ExactAvmFacilitatorScheme",
    # Registration helpers
    "register_exact_avm_client",
    "register_exact_avm_server",
    "register_exact_avm_facilitator",
    # V1 compatibility
    "v1",
]
