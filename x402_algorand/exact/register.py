# Copyright 2024 Coinbase; 2026 x402 Foundation; GoPlausible (x402-avm). Licensed under the Apache License 2.0.
# Modified in 2026 by the AI Economy Team for x402-algorand: algod token parameter.
# Changes are listed in the NOTICE file.
"""Registration helpers for AVM exact payment schemes."""

from typing import TYPE_CHECKING, TypeVar

from x402_algorand.constants import V1_NETWORKS

if TYPE_CHECKING:
    from x402 import (
        x402Client,
        x402ClientSync,
        x402Facilitator,
        x402FacilitatorSync,
        x402ResourceServer,
        x402ResourceServerSync,
    )

    from x402_algorand.signer import ClientAvmSigner, FacilitatorAvmSigner

# Type vars for accepting both async and sync variants
ClientT = TypeVar("ClientT", "x402Client", "x402ClientSync")
ServerT = TypeVar("ServerT", "x402ResourceServer", "x402ResourceServerSync")
FacilitatorT = TypeVar("FacilitatorT", "x402Facilitator", "x402FacilitatorSync")


def register_exact_avm_client(
    client: ClientT,
    signer: "ClientAvmSigner",
    networks: str | list[str] | None = None,
    policies: list | None = None,
    algod_url: str | None = None,
    algod_token: str | None = None,
) -> ClientT:
    """Register AVM exact payment schemes to x402Client.

    Registers:
    - V2: algorand:* wildcard (or specific networks if provided)
    - V1: All supported AVM networks

    Args:
        client: x402Client instance.
        signer: AVM signer for payment authorizations.
        networks: Optional specific network(s) (default: wildcard).
        policies: Optional payment policies.
        algod_url: Optional custom Algod URL.
        algod_token: Optional custom Algod token.

    Returns:
        Client for chaining.
    """
    from x402_algorand.exact.client import ExactAvmScheme as ExactAvmClientScheme
    from x402_algorand.exact.v1.client import ExactAvmSchemeV1 as ExactAvmClientSchemeV1

    scheme = ExactAvmClientScheme(signer, algod_url, algod_token)

    if networks:
        if isinstance(networks, str):
            networks = [networks]
        for network in networks:
            client.register(network, scheme)
    else:
        client.register("algorand:*", scheme)

    # Register V1 for all legacy networks
    v1_scheme = ExactAvmClientSchemeV1(signer, algod_url, algod_token)
    for network in V1_NETWORKS:
        client.register_v1(network, v1_scheme)

    if policies:
        for policy in policies:
            client.register_policy(policy)

    return client


def register_exact_avm_server(
    server: ServerT,
    networks: str | list[str] | None = None,
) -> ServerT:
    """Register AVM exact payment schemes to x402ResourceServer.

    V2 only (no server-side for V1).

    Args:
        server: x402ResourceServer instance.
        networks: Optional specific network(s) (default: wildcard).

    Returns:
        Server for chaining.
    """
    from x402_algorand.exact.server import ExactAvmScheme as ExactAvmServerScheme

    scheme = ExactAvmServerScheme()

    if networks:
        if isinstance(networks, str):
            networks = [networks]
        for network in networks:
            server.register(network, scheme)
    else:
        server.register("algorand:*", scheme)

    return server


def register_exact_avm_facilitator(
    facilitator: FacilitatorT,
    signer: "FacilitatorAvmSigner",
    networks: str | list[str],
) -> FacilitatorT:
    """Register AVM exact payment schemes to x402Facilitator.

    Registers:
    - V2: Specified networks
    - V1: All supported AVM networks

    Args:
        facilitator: x402Facilitator instance.
        signer: AVM signer for verification/settlement.
        networks: Network(s) to register.

    Returns:
        Facilitator for chaining.
    """
    from x402_algorand.exact.facilitator import ExactAvmScheme as ExactAvmFacilitatorScheme
    from x402_algorand.exact.v1.facilitator import ExactAvmSchemeV1 as ExactAvmFacilitatorSchemeV1

    scheme = ExactAvmFacilitatorScheme(signer)

    if isinstance(networks, str):
        networks = [networks]
    facilitator.register(networks, scheme)

    # Register V1
    v1_scheme = ExactAvmFacilitatorSchemeV1(signer)
    facilitator.register_v1(V1_NETWORKS, v1_scheme)

    return facilitator
