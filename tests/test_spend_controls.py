"""Integration tests for official x402 spend controls with ExactAvmScheme."""

import pytest
from conftest import (
    LOCALNET_ALGOD_TOKEN,
    LOCALNET_ALGOD_URL,
    DefaultAvmSigner,
    get_localnet_algod,
    get_localnet_network,
    new_funded_account,
)
from x402 import x402Client
from x402.schemas import PaymentRequired, PaymentRequirements
from x402.schemas.errors import NoMatchingRequirementsError

from x402_algorand.exact.facilitator import ExactAvmScheme as FacilitatorScheme
from x402_algorand.exact.register import register_exact_avm_client


@pytest.fixture
def localnet_context():
    """Create fresh funded accounts and client setup on LocalNet."""
    algod_client = get_localnet_algod()
    network = get_localnet_network(algod_client)
    algod_url = LOCALNET_ALGOD_URL
    algod_token = LOCALNET_ALGOD_TOKEN

    server_sk, server_addr = new_funded_account(algos=10.0, algod_client=algod_client)
    server_signer = DefaultAvmSigner(server_sk, algod_client=algod_client)
    facilitator = FacilitatorScheme(server_signer)

    client2_sk, client2_addr = new_funded_account(algos=10.0, algod_client=algod_client)
    client2_signer = DefaultAvmSigner(client2_sk, algod_client=algod_client)

    return {
        "network": network,
        "algod_url": algod_url,
        "algod_token": algod_token,
        "algod_client": algod_client,
        "server_addr": server_addr,
        "server_signer": server_signer,
        "facilitator": facilitator,
        "client2_addr": client2_addr,
        "client2_signer": client2_signer,
    }


@pytest.mark.localnet
@pytest.mark.asyncio
async def test_spend_controls_algo_paid_default(localnet_context):
    """(a) ALGO requirement of 10,000 microALGO is within the default $1 cap and is paid."""
    ctx = localnet_context
    client = x402Client()
    register_exact_avm_client(
        client,
        ctx["client2_signer"],
        algod_url=ctx["algod_url"],
        algod_token=ctx["algod_token"],
    )

    req = PaymentRequirements(
        scheme="exact",
        network=ctx["network"],
        asset="0",
        amount="10000",
        pay_to=ctx["server_addr"],
        max_timeout_seconds=300,
    )
    pr = PaymentRequired(accepts=[req])

    payload = await client.create_payment_payload(pr)
    assert payload.accepted.amount == "10000"
    assert payload.accepted.asset == "0"

    # Verify and settle on LocalNet
    verify_res = ctx["facilitator"].verify(payload, req)
    assert verify_res.is_valid is True, f"Verify failed: {verify_res.invalid_message}"
    settle_res = ctx["facilitator"].settle(payload, req)
    assert settle_res.success is True, f"Settle failed: {settle_res.error_message}"


@pytest.mark.localnet
@pytest.mark.asyncio
async def test_spend_controls_algo_above_cap_refused(localnet_context):
    """(b) ALGO requirement of 2,000,000 microALGO exceeds default $1 cap (1,000,000) and is refused."""
    ctx = localnet_context
    client = x402Client()
    register_exact_avm_client(
        client,
        ctx["client2_signer"],
        algod_url=ctx["algod_url"],
        algod_token=ctx["algod_token"],
    )

    req = PaymentRequirements(
        scheme="exact",
        network=ctx["network"],
        asset="0",
        amount="2000000",
        pay_to=ctx["server_addr"],
        max_timeout_seconds=300,
    )
    pr = PaymentRequired(accepts=[req])

    with pytest.raises(NoMatchingRequirementsError) as exc_info:
        await client.create_payment_payload(pr)

    assert "spend_controls.max_amount_per_payment" in str(exc_info.value)
    assert "ALGO" in str(exc_info.value)


@pytest.mark.localnet
@pytest.mark.asyncio
async def test_spend_controls_unknown_asa_refused_default_and_accepted_when_allowed(
    localnet_context,
):
    """(c) Unknown ASA is refused by default and accepted with spend_controls allowed_assets."""
    ctx = localnet_context
    client = x402Client()
    register_exact_avm_client(
        client,
        ctx["client2_signer"],
        algod_url=ctx["algod_url"],
        algod_token=ctx["algod_token"],
    )

    unknown_asa = "999999"
    req = PaymentRequirements(
        scheme="exact",
        network=ctx["network"],
        asset=unknown_asa,
        amount="50000",
        pay_to=ctx["server_addr"],
        max_timeout_seconds=300,
    )
    pr = PaymentRequired(accepts=[req])

    # 1. Refused by default
    with pytest.raises(NoMatchingRequirementsError) as exc_info:
        await client.create_payment_payload(pr)
    assert "spend_controls" in str(exc_info.value)

    # 2. Accepted when allowed via spend_controls
    client.set_spend_controls(
        {
            "allowed_assets": [
                {
                    "network": ctx["network"],
                    "asset": unknown_asa,
                    "max_amount_per_payment": "1000000",
                }
            ]
        }
    )

    payload = await client.create_payment_payload(pr)
    assert payload.accepted.amount == "50000"
    assert payload.accepted.asset == unknown_asa
