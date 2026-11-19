# Copyright 2024 Coinbase; 2026 x402 Foundation; GoPlausible (x402-avm). Licensed under the Apache License 2.0.
# Modified in 2026 by x402-avm contributors for x402-algorand.
# Changes are listed in the NOTICE file.
"""V1 facilitator implementation for AVM exact payment scheme.

Provides backward compatibility for V1 protocol by wrapping the V2 implementation.
Maps V1 network names (algorand-mainnet, algorand-testnet) to V2 CAIP-2 identifiers.

``verify`` and ``settle`` accept either the official SDK's V1 models
(``PaymentPayloadV1`` / ``PaymentRequirementsV1``, as passed by ``x402Facilitator``),
returning ``VerifyResponse`` / ``SettleResponse``, or plain camelCase dicts, returning
the V1 camelCase response dicts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from x402.schemas import (
    PaymentPayload,
    PaymentRequirements,
    SettleResponse,
)

from x402_algorand.constants import V1_TO_V2_NETWORK_MAP, V2_TO_V1_NETWORK_MAP

if TYPE_CHECKING:
    from x402_algorand.signer import FacilitatorAvmSigner


class ExactAvmSchemeV1:
    """V1 facilitator implementation for AVM exact payment scheme.

    Wraps V2 ExactAvmScheme with V1 network name support and
    field name mapping.

    This implements SchemeNetworkFacilitatorV1 protocol.

    Attributes:
        scheme: The scheme identifier ("exact").
        caip_family: The CAIP-2 family for Algorand networks.
    """

    scheme = "exact"
    caip_family = "algorand"

    def __init__(self, signer: FacilitatorAvmSigner):
        """Create ExactAvmSchemeV1.

        Args:
            signer: AVM signer for verification/settlement.
        """
        # Import here to avoid circular imports
        from x402_algorand.exact.facilitator import ExactAvmScheme

        self._v2_scheme = ExactAvmScheme(signer)

    def get_signers(self, network: str) -> list[str]:
        """Get facilitator wallet addresses.

        Args:
            network: V1 network name.

        Returns:
            List of facilitator fee payer addresses.
        """
        v2_network = V1_TO_V2_NETWORK_MAP.get(network, network)
        return self._v2_scheme.get_signers(v2_network)

    def get_extra(self, network: str) -> dict[str, Any] | None:
        """Get extra configuration for a network.

        Args:
            network: V1 network name.

        Returns:
            Extra configuration dict, or None.
        """
        v2_network = V1_TO_V2_NETWORK_MAP.get(network, network)
        return self._v2_scheme.get_extra(v2_network)

    def verify(
        self,
        payload: Any,
        payment_requirements: Any,
        context: Any = None,
    ) -> Any:
        """Verify payment payload for V1 protocol.

        Args:
            payload: ``PaymentPayloadV1`` or V1 payload dict.
            payment_requirements: ``PaymentRequirementsV1`` or V1 requirements dict.
            context: Facilitator context (unused).

        Returns:
            ``VerifyResponse`` for model input; V1 verify response dict for dict input.
        """
        _ = context
        v2_payload, v2_requirements = _to_v2(payload, payment_requirements)
        result = self._v2_scheme.verify(v2_payload, v2_requirements)
        if not isinstance(payload, dict):
            return result
        return {
            "isValid": result.is_valid,
            "invalidReason": result.invalid_reason,
            "payer": result.payer,
        }

    def settle(
        self,
        payload: Any,
        payment_requirements: Any,
        context: Any = None,
    ) -> Any:
        """Settle payment for V1 protocol.

        Args:
            payload: ``PaymentPayloadV1`` or V1 payload dict.
            payment_requirements: ``PaymentRequirementsV1`` or V1 requirements dict.
            context: Facilitator context (unused).

        Returns:
            ``SettleResponse`` for model input; V1 settle response dict for dict input.
            The network is reported with its V1 name.
        """
        _ = context
        v2_payload, v2_requirements = _to_v2(payload, payment_requirements)
        result = self._v2_scheme.settle(v2_payload, v2_requirements)
        response_network = V2_TO_V1_NETWORK_MAP.get(str(result.network), str(result.network))
        if not isinstance(payload, dict):
            return SettleResponse(
                success=result.success,
                error_reason=result.error_reason,
                error_message=result.error_message,
                transaction=result.transaction,
                network=response_network,
                payer=result.payer,
            )
        return {
            "success": result.success,
            "errorReason": result.error_reason,
            "transaction": result.transaction,
            "network": response_network,
            "payer": result.payer,
        }


def _as_dict(obj: Any) -> dict[str, Any]:
    """V1 model or dict -> camelCase dict."""
    if isinstance(obj, dict):
        return obj
    return obj.model_dump(by_alias=True)


def _to_v2(payload: Any, payment_requirements: Any) -> tuple[PaymentPayload, PaymentRequirements]:
    """Convert V1 payload/requirements (models or dicts) to V2 models."""
    p = _as_dict(payload)
    r = _as_dict(payment_requirements)

    def v2_net(name: str) -> str:
        return V1_TO_V2_NETWORK_MAP.get(name, name)

    common = {
        "amount": str(r.get("maxAmountRequired", "0")),
        "pay_to": r.get("payTo", ""),
        "asset": r.get("asset", ""),
        "max_timeout_seconds": r.get("maxTimeoutSeconds") or 0,
        "extra": r.get("extra") or {},
    }
    v2_requirements = PaymentRequirements(
        scheme=r.get("scheme", "exact"), network=v2_net(r.get("network", "")), **common
    )
    # V1 payloads carry scheme/network at the top level; they become "accepted".
    v2_accepted = PaymentRequirements(
        scheme=p.get("scheme", "exact"), network=v2_net(p.get("network", "")), **common
    )
    v2_payload = PaymentPayload(
        x402_version=1,
        payload=p.get("payload", {}),
        accepted=v2_accepted,
    )
    return v2_payload, v2_requirements
