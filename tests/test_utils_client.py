"""Offline tests for utilities, the client scheme, exceptions, and package metadata."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest
from algosdk import transaction
from avm_builders import ASA, GH, NETWORK, OTHER_GH, acct, b64, pay, raw, req, sign, sp

import x402_algorand
from x402_algorand import (
    NetworkError,
    NetworkMismatchError,
    PayerAvmSigner,
    SigningError,
    SimulationError,
    TransactionDecodeError,
    X402AlgorandError,
)
from x402_algorand.constants import (
    ALGORAND_MAINNET_CAIP2,
    ERR_REKEY_DETECTED,
    TXN_TYPE_ASSET_TRANSFER,
    TXN_TYPE_PAYMENT,
    USDC_MAINNET_ASA_ID,
    USDC_TESTNET_ASA_ID,
)
from x402_algorand.exact.client import ExactAvmScheme as ClientScheme
from x402_algorand.exact.client import find_default_asset
from x402_algorand.types import DecodedTransactionInfo, ExactAvmPayload
from x402_algorand.utils import (
    caip2_from_genesis_hash,
    decode_base64_transaction,
    decode_payment_group,
    decode_transaction_bytes,
    encode_transaction_group,
    from_atomic_amount,
    get_default_usdc_info,
    get_network_config,
    get_usdc_asa_id,
    is_blocked_transaction_type,
    is_valid_address,
    is_valid_network,
    network_from_genesis_hash,
    parse_money_to_decimal,
    to_atomic_amount,
    validate_rekey_operations,
    verify_transaction_signature,
)

UNREGISTERED = "algorand:zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"


# ---------------------------------------------------------------------------
# package metadata and exceptions
# ---------------------------------------------------------------------------


def test_version_matches_distribution():
    from importlib.metadata import version

    assert x402_algorand.__version__ == version("x402-algorand")


@pytest.mark.parametrize(
    ("exc", "builtin"),
    [
        (NetworkError, ValueError),
        (NetworkMismatchError, ValueError),
        (TransactionDecodeError, ValueError),
        (SigningError, ValueError),
        (SimulationError, RuntimeError),
    ],
)
def test_exceptions_keep_builtin_bases(exc, builtin):
    assert issubclass(exc, X402AlgorandError)
    assert issubclass(exc, builtin)


# ---------------------------------------------------------------------------
# utils
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        (None, False),
        ("", False),
        ("lowercase", False),
        ("A" * 58, False),  # right shape, bad checksum
    ],
)
def test_is_valid_address(value, ok):
    assert is_valid_address(value) is ok


def test_is_valid_address_real():
    assert is_valid_address(acct().addr) is True


def test_caip2_errors():
    with pytest.raises(TypeError):
        caip2_from_genesis_hash(123)  # type: ignore[arg-type]
    with pytest.raises(NetworkError):
        caip2_from_genesis_hash("abc")  # bad padding
    assert caip2_from_genesis_hash(base64.b64decode(GH)) == NETWORK
    assert caip2_from_genesis_hash(GH.encode()) == NETWORK


@pytest.mark.parametrize("bad", [123, "eip155:1", UNREGISTERED + "x"])
def test_network_lookups_raise_network_error(bad):
    assert is_valid_network(bad) is False
    with pytest.raises(NetworkError):
        get_network_config(bad)
    with pytest.raises(ValueError):  # backward compatible
        get_usdc_asa_id(bad)


def test_network_helpers():
    assert get_usdc_asa_id("algorand-mainnet") == USDC_MAINNET_ASA_ID
    assert get_network_config(NETWORK)["genesis_hash"] == GH
    with pytest.raises(NetworkError):
        get_network_config(UNREGISTERED)
    assert network_from_genesis_hash(OTHER_GH) == ALGORAND_MAINNET_CAIP2
    assert network_from_genesis_hash("nope") is None
    assert get_default_usdc_info(ALGORAND_MAINNET_CAIP2)["asa_id"] == USDC_MAINNET_ASA_ID
    assert get_default_usdc_info(NETWORK)["asa_id"] == USDC_TESTNET_ASA_ID
    with pytest.raises(NetworkError):
        get_default_usdc_info(UNREGISTERED)


def test_money_helpers():
    assert parse_money_to_decimal(" $1,234.5 ") == 1234.5
    assert parse_money_to_decimal(3) == 3.0
    assert to_atomic_amount(0.000001) == 1
    assert from_atomic_amount(1_500_000) == 1.5
    assert is_blocked_transaction_type("keyreg") is True
    assert is_blocked_transaction_type("pay") is False


def test_decode_errors():
    with pytest.raises(TransactionDecodeError):
        decode_base64_transaction("***")
    with pytest.raises(TransactionDecodeError):
        decode_transaction_bytes(b"\xc1")
    with pytest.raises(TransactionDecodeError, match="Unknown transaction format"):
        decode_transaction_bytes(base64.b64decode("gaF4AQ=="))  # msgpack {"x": 1}
    with pytest.raises(ValueError):  # backward compatible
        decode_base64_transaction("***")


def test_decode_payment_group_and_encode():
    payer, fp, server = acct(), acct(), acct()
    t_fee = pay(fp.addr, fp.addr, 0, fee=2000)
    t_pay = transaction.AssetTransferTxn(payer.addr, sp(0), server.addr, 9, ASA)
    t_fee, t_pay = transaction.assign_group_id([t_fee, t_pay])
    group = [b64(t_fee), b64(sign(t_pay, payer.sk))]
    info = decode_payment_group(group, 1)
    assert info.has_fee_payer and info.fee_payer_index == 0
    assert info.total_fee == 2000
    assert info.group_id == info.transactions[1].group
    assert info.transactions[1].type == TXN_TYPE_ASSET_TRANSFER
    assert info.transactions[1].is_signed and not info.transactions[0].is_signed
    assert encode_transaction_group([raw(t_fee)]) == [group[0]]


@pytest.mark.parametrize(
    ("ops", "reason"),
    [
        ([], None),
        ([("A", "B")], ERR_REKEY_DETECTED),
        ([("A", "B"), ("A", "A")], None),  # balanced sandwich
        ([("A", "B"), ("A", "B")], ERR_REKEY_DETECTED),  # never returned to A
        ([("A", "B"), ("C", "C")], ERR_REKEY_DETECTED),
        ([("A", "B"), ("A", "A"), ("A", "B"), ("A", "A")], ERR_REKEY_DETECTED),
    ],
)
def test_validate_rekey_operations(ops, reason):
    txns = [
        DecodedTransactionInfo(
            type="pay", sender=s, fee=0, first_valid=1, last_valid=2, genesis_hash="", rekey_to=t
        )
        for s, t in ops
    ]
    assert validate_rekey_operations(txns) == reason


def test_verify_transaction_signature_edge_cases():
    a, b = acct(), acct()
    assert verify_transaction_signature("***")[0] is False
    assert verify_transaction_signature(b64(pay(a.addr, b.addr, 1))) == (
        False,
        "Transaction has no signature",
    )
    empty = transaction.SignedTransaction(pay(a.addr, b.addr, 1), "")
    assert verify_transaction_signature(b64(empty))[0] is False
    short_sig = transaction.SignedTransaction(pay(a.addr, b.addr, 1), "AAAA")
    assert verify_transaction_signature(b64(short_sig))[0] is False


def test_payload_dataclass_round_trip():
    data = {"paymentGroup": ["x"], "paymentIndex": 0}
    assert ExactAvmPayload.from_dict(data).to_dict() == data


# ---------------------------------------------------------------------------
# client scheme
# ---------------------------------------------------------------------------


def _client(signer, gh=GH, **kw):
    scheme = ClientScheme(signer, algod_url="http://mock:4001", **kw)
    algod = MagicMock()
    algod.suggested_params.return_value = sp(gh=gh)
    scheme._clients[NETWORK] = algod
    return scheme


@pytest.mark.parametrize("asset", ["0", str(ASA)])
def test_client_fee_payer_mode_builds_two_txn_group(asset):
    payer, fp, server = acct(), acct(), acct()
    scheme = _client(PayerAvmSigner(payer.sk))
    out = scheme.create_payment_payload(
        req(server.addr, amount="7", asset=asset, extra={"feePayer": fp.addr})
    )
    assert out["paymentIndex"] == 1
    fee_txn, payment = (decode_base64_transaction(t) for t in out["paymentGroup"])
    assert fee_txn.type == TXN_TYPE_PAYMENT
    assert (fee_txn.sender, fee_txn.receiver, fee_txn.amount) == (fp.addr, fp.addr, 0)
    assert fee_txn.fee == 2000 and not fee_txn.is_signed
    assert payment.fee == 0 and payment.is_signed
    assert fee_txn.group == payment.group is not None


def test_client_network_errors():
    payer, server = acct(), acct()
    wrong = _client(PayerAvmSigner(payer.sk), gh=OTHER_GH)
    with pytest.raises(NetworkMismatchError):
        wrong.create_payment_payload(req(server.addr))

    no_url = ClientScheme(PayerAvmSigner(payer.sk))
    with pytest.raises(NetworkError, match="algod_url"):
        no_url.create_payment_payload(req(server.addr, network=UNREGISTERED))
    # MainNet/TestNet use the configured public algod by default (no request made here)
    assert "mainnet" in no_url._get_client(ALGORAND_MAINNET_CAIP2).algod_address
    assert no_url._get_client(ALGORAND_MAINNET_CAIP2) is no_url._get_client("algorand-mainnet")


def test_client_custom_algod_token():
    scheme = ClientScheme(PayerAvmSigner(acct().sk), algod_url="http://x:1", algod_token="tok")
    assert scheme._get_client(NETWORK).algod_token == "tok"


def test_find_default_asset():
    assert find_default_asset("0", UNREGISTERED)["symbol"] == "ALGO"
    assert find_default_asset("0", "not-a-network") is None
    assert find_default_asset(str(USDC_MAINNET_ASA_ID), ALGORAND_MAINNET_CAIP2)["decimals"] == 6
    assert find_default_asset("999", ALGORAND_MAINNET_CAIP2) is None
