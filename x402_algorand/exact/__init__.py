# Copyright 2024 Coinbase; 2026 x402 Foundation; GoPlausible (x402-avm). Licensed under the Apache License 2.0.
# Modified in 2026 by the AI Economy Team for x402-algorand.
# Changes are listed in the NOTICE file.
"""Exact payment scheme for AVM (Algorand).

Provides client, server, and facilitator implementations
for the exact payment scheme on Algorand networks.

Usage:
    ```python
    from x402_algorand.exact import (
        ExactAvmScheme,
        register_exact_avm_client,
        register_exact_avm_facilitator,
    )

    # Client-side: implement ClientAvmSigner protocol with algosdk
    import base64, algosdk
    secret_key = base64.b64decode(os.environ["AVM_PRIVATE_KEY"])
    address = algosdk.encoding.encode_address(secret_key[32:])
    # ... implement sign_transactions method (see examples)
    client = x402Client()
    register_exact_avm_client(client, signer)

    # Facilitator-side: implement FacilitatorAvmSigner protocol with algosdk
    # ... implement get_addresses, sign_transaction, simulate_group, etc. (see examples)
    facilitator = x402Facilitator()
    register_exact_avm_facilitator(facilitator, fac_signer, networks)
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
