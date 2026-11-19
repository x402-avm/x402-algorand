# Copyright 2024 Coinbase; 2026 x402 Foundation; GoPlausible (x402-avm). Licensed under the Apache License 2.0.
# Modified in 2026 by the AI Economy Team for x402-algorand.
# Changes are listed in the NOTICE file.
"""V1 backward compatibility wrappers for AVM exact payment scheme.

These wrappers provide backward compatibility for V1 protocol clients
by mapping V1 network names to V2 CAIP-2 identifiers.

Note: This does NOT add code to the deprecated python/legacy/ directory.
These are V1-compatible wrappers within the V2 SDK architecture.
"""

from x402_algorand.exact.v1.client import ExactAvmSchemeV1 as ExactAvmSchemeV1Client
from x402_algorand.exact.v1.facilitator import ExactAvmSchemeV1 as ExactAvmSchemeV1Facilitator

# For convenience, expose both
ExactAvmSchemeV1 = ExactAvmSchemeV1Client

__all__ = [
    "ExactAvmSchemeV1",
    "ExactAvmSchemeV1Client",
    "ExactAvmSchemeV1Facilitator",
]
