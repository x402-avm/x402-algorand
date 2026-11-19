"""Offline unit tests for x402 Algorand AVM fork changes."""

from unittest.mock import MagicMock

from algosdk import account, transaction
from conftest import DefaultAvmSigner
from x402.schemas import PaymentPayload, PaymentRequirements

from x402_algorand.constants import (
    ALGORAND_TESTNET_CAIP2,
    ERR_AMOUNT_INSUFFICIENT,
    ERR_INVALID_ASSET_ID,
    ERR_RECIPIENT_MISMATCH,
    TXN_TYPE_ASSET_TRANSFER,
    TXN_TYPE_PAYMENT,
)
from x402_algorand.exact.client import ExactAvmScheme as ClientScheme
from x402_algorand.exact.facilitator import ExactAvmScheme as FacilitatorScheme
from x402_algorand.exact.register import register_exact_avm_client
from x402_algorand.utils import decode_base64_transaction

GENESIS_HASH = "SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI="
NETWORK = ALGORAND_TESTNET_CAIP2


def create_mock_algod(genesis_hash: str = GENESIS_HASH) -> MagicMock:
    """Create a mock Algod client returning standard suggested params."""
    mock = MagicMock()
    sp = transaction.SuggestedParams(
        fee=1000,
        first=1,
        last=1000,
        gh=genesis_hash,
        gen="dockernet-v1",
        flat_fee=True,
    )
    mock.suggested_params.return_value = sp
    return mock


def test_client_native_algo_payment_scheme():
    """a) client scheme with asset '0' builds a PaymentTxn (type 'pay') to pay_to with exact amount."""
    client_sk, client_addr = account.generate_account()
    signer = DefaultAvmSigner(client_sk)
    scheme = ClientScheme(signer, algod_url="http://mock:4001")
    scheme._clients[NETWORK] = create_mock_algod()

    _, pay_to = account.generate_account()
    req = PaymentRequirements(
        scheme="exact",
        network=NETWORK,
        asset="0",
        amount="5000",
        pay_to=pay_to,
        max_timeout_seconds=300,
    )

    payload = scheme.create_payment_payload(req)
    assert "paymentGroup" in payload
    assert len(payload["paymentGroup"]) == 1

    dec = decode_base64_transaction(payload["paymentGroup"][0])
    assert dec.type == TXN_TYPE_PAYMENT
    assert dec.sender == client_addr
    assert dec.receiver == pay_to
    assert dec.amount == 5000


def test_client_asa_payment_scheme():
    """b) client scheme with asset '1003' builds an AssetTransferTxn with index 1003."""
    client_sk, client_addr = account.generate_account()
    signer = DefaultAvmSigner(client_sk)
    scheme = ClientScheme(signer, algod_url="http://mock:4001")
    scheme._clients[NETWORK] = create_mock_algod()

    _, pay_to = account.generate_account()
    req = PaymentRequirements(
        scheme="exact",
        network=NETWORK,
        asset="1003",
        amount="750",
        pay_to=pay_to,
        max_timeout_seconds=300,
    )

    payload = scheme.create_payment_payload(req)
    assert "paymentGroup" in payload
    assert len(payload["paymentGroup"]) == 1

    dec = decode_base64_transaction(payload["paymentGroup"][0])
    assert dec.type == TXN_TYPE_ASSET_TRANSFER
    assert dec.sender == client_addr
    assert dec.asset_receiver == pay_to
    assert dec.asset_index == 1003
    assert dec.asset_amount == 750


def test_facilitator_verify_algo_and_asa():
    """
    c) facilitator verify():
       - ALGO payment with correct amount/receiver -> valid
       - wrong receiver -> invalid with recipient mismatch reason
       - amount too low -> invalid with amount insufficient reason
       - an axfer when asset '0' is required -> invalid with asset ID mismatch reason
    """
    server_sk, server_addr = account.generate_account()
    client_sk, client_addr = account.generate_account()

    client_signer = DefaultAvmSigner(client_sk)
    client_scheme = ClientScheme(client_signer, algod_url="http://mock:4001")
    client_scheme._clients[NETWORK] = create_mock_algod()

    mock_fac_signer = MagicMock()
    mock_fac_signer.get_addresses.return_value = [server_addr]
    mock_fac_signer.simulate_group.return_value = None
    facilitator = FacilitatorScheme(mock_fac_signer)

    req = PaymentRequirements(
        scheme="exact",
        network=NETWORK,
        asset="0",
        amount="5000",
        pay_to=server_addr,
        max_timeout_seconds=300,
    )

    # 1. Valid ALGO payment
    inner_payload = client_scheme.create_payment_payload(req)
    valid_payload = PaymentPayload(
        x402_version=2,
        payload=inner_payload,
        accepted=req,
    )
    resp_valid = facilitator.verify(valid_payload, req)
    assert resp_valid.is_valid is True
    assert resp_valid.payer == client_addr

    # 2. Wrong receiver -> ERR_RECIPIENT_MISMATCH
    _, other_addr = account.generate_account()
    wrong_rcv_req = PaymentRequirements(
        scheme="exact",
        network=NETWORK,
        asset="0",
        amount="5000",
        pay_to=other_addr,
        max_timeout_seconds=300,
    )
    resp_wrong_rcv = facilitator.verify(valid_payload, wrong_rcv_req)
    assert resp_wrong_rcv.is_valid is False
    assert resp_wrong_rcv.invalid_reason == ERR_RECIPIENT_MISMATCH

    # 3. Amount too low -> ERR_AMOUNT_INSUFFICIENT
    higher_amt_req = PaymentRequirements(
        scheme="exact",
        network=NETWORK,
        asset="0",
        amount="10000",
        pay_to=server_addr,
        max_timeout_seconds=300,
    )
    resp_low_amt = facilitator.verify(valid_payload, higher_amt_req)
    assert resp_low_amt.is_valid is False
    assert resp_low_amt.invalid_reason == ERR_AMOUNT_INSUFFICIENT

    # 4. An axfer when asset '0' is required -> ERR_INVALID_ASSET_ID
    asa_req = PaymentRequirements(
        scheme="exact",
        network=NETWORK,
        asset="1003",
        amount="5000",
        pay_to=server_addr,
        max_timeout_seconds=300,
    )
    asa_inner = client_scheme.create_payment_payload(asa_req)
    asa_payload = PaymentPayload(
        x402_version=2,
        payload=asa_inner,
        accepted=req,
    )
    resp_axfer_mismatch = facilitator.verify(asa_payload, req)
    assert resp_axfer_mismatch.is_valid is False
    assert resp_axfer_mismatch.invalid_reason == ERR_INVALID_ASSET_ID


def test_register_exact_avm_client_token():
    """d) register_exact_avm_client passes algod_token to the scheme."""
    mock_client = MagicMock()
    mock_signer = MagicMock()
    custom_url = "http://custom-algod:4001"
    custom_token = "my-secret-algod-token-123"

    register_exact_avm_client(
        mock_client,
        mock_signer,
        algod_url=custom_url,
        algod_token=custom_token,
    )

    assert mock_client.register.called
    pattern, registered_scheme = mock_client.register.call_args[0]
    assert pattern == "algorand:*"
    assert registered_scheme._custom_algod_url == custom_url
    assert registered_scheme._custom_algod_token == custom_token
