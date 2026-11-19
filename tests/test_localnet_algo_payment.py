"""LocalNet integration test for native ALGO payment verification and settlement."""

import pytest
from conftest import (
    LOCALNET_ALGOD_TOKEN,
    LOCALNET_ALGOD_URL,
    DefaultAvmSigner,
    get_localnet_algod,
    get_localnet_network,
    new_funded_account,
)
from x402.schemas import PaymentPayload, PaymentRequirements

from x402_algorand.exact.client import ExactAvmScheme as ClientScheme
from x402_algorand.exact.facilitator import ExactAvmScheme as FacilitatorScheme


@pytest.mark.localnet
def test_localnet_algo_payment_verify_and_settle():
    """Build, verify, and settle a 5000 microAlgos payment on LocalNet."""
    algod_client = get_localnet_algod()
    network = get_localnet_network(algod_client)
    algod_url = LOCALNET_ALGOD_URL
    algod_token = LOCALNET_ALGOD_TOKEN

    # Server account (vendor) & facilitator signer
    server_sk, server_addr = new_funded_account(algos=10.0, algod_client=algod_client)
    server_signer = DefaultAvmSigner(server_sk, algod_client=algod_client)
    facilitator = FacilitatorScheme(server_signer)

    # Client account (buyer) & client signer
    client_sk, client_addr = new_funded_account(algos=10.0, algod_client=algod_client)
    client_signer = DefaultAvmSigner(client_sk, algod_client=algod_client)
    client_scheme = ClientScheme(client_signer, algod_url=algod_url, algod_token=algod_token)

    # Check server initial balance
    bal_before = algod_client.account_info(server_addr)["amount"]

    # Payment requirements: 5000 microAlgos (native ALGO, asset="0")
    amount_microalgos = 5000
    req = PaymentRequirements(
        scheme="exact",
        network=network,
        asset="0",
        amount=str(amount_microalgos),
        pay_to=server_addr,
        max_timeout_seconds=300,
    )

    # Build payment payload from client
    inner_payload = client_scheme.create_payment_payload(req)
    payload = PaymentPayload(
        x402_version=2,
        payload=inner_payload,
        accepted=req,
    )

    # Verify payment with facilitator
    verify_res = facilitator.verify(payload, req)
    assert verify_res.is_valid is True, (
        f"Verification failed: {verify_res.invalid_reason} ({verify_res.invalid_message})"
    )
    assert verify_res.payer == client_addr

    # Settle payment on-chain
    settle_res = facilitator.settle(payload, req)
    assert settle_res.success is True, (
        f"Settlement failed: {settle_res.error_reason} ({settle_res.error_message})"
    )
    assert settle_res.transaction != ""

    # Verify server balance increase (with 10000 fee slack)
    bal_after = algod_client.account_info(server_addr)["amount"]
    diff = bal_after - bal_before
    assert abs(diff - amount_microalgos) <= 10000, (
        f"Expected increase of ~{amount_microalgos}, got {diff}"
    )


@pytest.mark.localnet
def test_localnet_ready_made_signers_with_fee_payer():
    """PayerAvmSigner + ServerAvmSigner, facilitator pays the fees, payer pays the exact amount."""
    from x402_algorand import PayerAvmSigner, ServerAvmSigner

    algod_client = get_localnet_algod()
    network = get_localnet_network(algod_client)

    server_sk, server_addr = new_funded_account(algos=10.0, algod_client=algod_client)
    payer_sk, payer_addr = new_funded_account(algos=10.0, algod_client=algod_client)

    server_signer = ServerAvmSigner.from_private_key(
        server_sk, algod_url=LOCALNET_ALGOD_URL, algod_token=LOCALNET_ALGOD_TOKEN
    )
    facilitator = FacilitatorScheme(server_signer)
    client_scheme = ClientScheme(
        PayerAvmSigner.from_private_key(payer_sk),
        algod_url=LOCALNET_ALGOD_URL,
        algod_token=LOCALNET_ALGOD_TOKEN,
    )

    amount = 10_000
    req = PaymentRequirements(
        scheme="exact",
        network=network,
        asset="0",
        amount=str(amount),
        pay_to=server_addr,
        max_timeout_seconds=300,
        extra={"feePayer": server_signer.address},
    )
    payload = PaymentPayload(
        x402_version=2, payload=client_scheme.create_payment_payload(req), accepted=req
    )
    payer_before = algod_client.account_info(payer_addr)["amount"]

    verify_res = facilitator.verify(payload, req)
    assert verify_res.is_valid, verify_res.invalid_message

    settle_res = facilitator.settle(payload, req)
    assert settle_res.success, settle_res.error_message

    # The reported transaction is the payment (paymentGroup[1]) and it is confirmed.
    info = algod_client.pending_transaction_info(settle_res.transaction)
    assert info.get("confirmed-round", 0) > 0
    assert info["txn"]["txn"]["type"] == "pay"
    assert info["txn"]["txn"]["snd"] == payer_addr
    # The payer paid exactly the amount; the facilitator covered the fees.
    assert payer_before - algod_client.account_info(payer_addr)["amount"] == amount
