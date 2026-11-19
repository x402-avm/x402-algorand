"""Offline tests for the ready-made signers PayerAvmSigner and ServerAvmSigner."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest
from algosdk import mnemonic, transaction
from avm_builders import GH, NETWORK, OTHER_GH, acct, b64, pay, raw, sign, sp

from x402_algorand import (
    ClientAvmSigner,
    FacilitatorAvmSigner,
    NetworkError,
    NetworkMismatchError,
    PayerAvmSigner,
    ServerAvmSigner,
    SigningError,
    SimulationError,
    X402AlgorandError,
)
from x402_algorand.signer import _decode
from x402_algorand.utils import verify_transaction_signature


def _algod(gh: str = GH) -> MagicMock:
    client = MagicMock()
    client.suggested_params.return_value = sp(gh=gh)
    client.simulate_transactions.return_value = {"txn-groups": [{}]}
    client.send_transactions.return_value = "TXID"
    return client


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [PayerAvmSigner, ServerAvmSigner])
def test_from_private_key_and_mnemonic(cls):
    a = acct()
    by_key = cls.from_private_key(a.sk)
    by_words = cls.from_mnemonic(mnemonic.from_private_key(a.sk))
    assert by_key.address == by_words.address == a.addr


@pytest.mark.parametrize("cls", [PayerAvmSigner, ServerAvmSigner])
def test_repr_and_str_never_contain_the_key(cls):
    a = acct()
    signer = cls.from_private_key(a.sk)
    text = repr(signer) + str(signer)
    assert a.addr in text
    assert a.sk not in text
    assert a.sk[:20] not in text
    assert not any(a.sk in str(v) for v in vars(signer).values())


def _bad_keys():
    a, b = acct(), acct()
    raw_a, raw_b = base64.b64decode(a.sk), base64.b64decode(b.sk)
    return {
        "not_base64": "!!!",
        "short": base64.b64encode(raw_a[:32]).decode(),
        "mismatched_public_key": base64.b64encode(raw_a[:32] + raw_b[32:]).decode(),
        "not_str": 12345,
    }


@pytest.mark.parametrize("name", list(_bad_keys()))
@pytest.mark.parametrize("cls", [PayerAvmSigner, ServerAvmSigner])
def test_invalid_private_keys_raise_signing_error(cls, name):
    key = _bad_keys()[name]
    with pytest.raises(SigningError) as exc:
        cls.from_private_key(key)
    assert isinstance(exc.value, ValueError)
    assert isinstance(exc.value, X402AlgorandError)


@pytest.mark.parametrize("words", ["abandon " * 24 + "abandon", "only three words", 42])
def test_invalid_mnemonic_raises_without_echoing_it(words):
    with pytest.raises(SigningError) as exc:
        PayerAvmSigner.from_mnemonic(words)
    assert str(words) not in str(exc.value)


def test_server_signer_requires_a_key():
    with pytest.raises(SigningError):
        ServerAvmSigner([])


def test_signers_satisfy_protocols():
    a = acct()
    payer: ClientAvmSigner = PayerAvmSigner(a.sk)
    server: FacilitatorAvmSigner = ServerAvmSigner(a.sk)
    assert payer.address == a.addr
    assert server.get_addresses() == [a.addr]


# ---------------------------------------------------------------------------
# signing
# ---------------------------------------------------------------------------


def test_payer_signs_only_requested_indexes():
    a, b = acct(), acct()
    signer = PayerAvmSigner(a.sk)
    t1, t2 = transaction.assign_group_id([pay(b.addr, b.addr, 0), pay(a.addr, b.addr, 7)])
    out = signer.sign_transactions([raw(t1), raw(t2)], [1])
    assert out[0] is None
    ok, err = verify_transaction_signature(base64.b64encode(out[1]).decode())
    assert ok, err
    assert _decode(out[1]).transaction.get_txid() == t2.get_txid()


def test_payer_refuses_foreign_sender_and_signed_input():
    a, b = acct(), acct()
    signer = PayerAvmSigner(a.sk)
    with pytest.raises(SigningError, match="not managed"):
        signer.sign_transactions([raw(pay(b.addr, a.addr, 1))], [0])
    with pytest.raises(SigningError, match="not an unsigned"):
        signer.sign_transactions([raw(sign(pay(a.addr, b.addr, 1), a.sk))], [0])


def test_server_sign_transaction_and_group_with_multiple_keys():
    a, b, c = acct(), acct(), acct()
    signer = ServerAvmSigner([a.sk, b.sk])
    assert signer.get_addresses() == [a.addr, b.addr]
    assert "addresses=" in repr(signer)

    fee_txn = pay(b.addr, b.addr, 0, fee=2000)
    signed = signer.sign_transaction(raw(fee_txn), b.addr, NETWORK)
    assert verify_transaction_signature(base64.b64encode(signed).decode()) == (True, "")

    group = [raw(fee_txn), raw(pay(c.addr, a.addr, 1))]
    out = signer.sign_group(group, b.addr, [0], NETWORK)
    assert out[1] == group[1]
    assert _decode(out[0]).signature

    with pytest.raises(SigningError):
        signer.sign_transaction(raw(fee_txn), c.addr, NETWORK)
    with pytest.raises(SigningError, match="cannot decode"):
        signer.sign_transaction(b"\xc1", a.addr, NETWORK)

    # ClientAvmSigner role: signs each index with its sender's key
    both = signer.sign_transactions(
        [raw(pay(a.addr, c.addr, 1)), raw(pay(b.addr, c.addr, 1))], [0, 1]
    )
    assert all(both)


# ---------------------------------------------------------------------------
# algod: network selection, simulate, send, confirm
# ---------------------------------------------------------------------------


def test_algod_for_checks_genesis_once_and_caches():
    client = _algod()
    signer = ServerAvmSigner(acct().sk, client)
    assert signer.algod_for(NETWORK) is client
    assert signer.algod_for("algorand-testnet") is client
    assert client.suggested_params.call_count == 1


def test_algod_for_rejects_other_network():
    signer = ServerAvmSigner(acct().sk, _algod(gh=OTHER_GH))
    with pytest.raises(NetworkMismatchError) as exc:
        signer.algod_for(NETWORK)
    assert isinstance(exc.value, NetworkError)
    assert isinstance(exc.value, ValueError)


def test_algod_for_defaults_to_network_config_and_algod_url():
    signer = ServerAvmSigner(acct().sk)
    client = signer.algod_for(NETWORK)
    assert "testnet" in client.algod_address
    with pytest.raises(NetworkError, match="no algod configured"):
        signer.algod_for("algorand:unregisteredunregisteredunregist")

    by_url = ServerAvmSigner.from_private_key(acct().sk, algod_url="http://localhost:4001")
    assert by_url._algod.algod_address == "http://localhost:4001"


def test_simulate_send_confirm(monkeypatch):
    client = _algod()
    a, b = acct(), acct()
    signer = ServerAvmSigner.from_private_key(a.sk, client)
    unsigned_fee = raw(pay(a.addr, a.addr, 0))
    signed_payment = raw(sign(pay(b.addr, a.addr, 5), b.sk))

    assert signer.simulate_group([unsigned_fee, signed_payment], NETWORK) is None
    request = client.simulate_transactions.call_args[0][0]
    assert request.allow_empty_signatures is True
    # unsigned transactions are wrapped so algod accepts them for simulation
    assert all(isinstance(t, transaction.SignedTransaction) for t in request.txn_groups[0].txns)

    client.simulate_transactions.return_value = {"txn-groups": [{"failure-message": "overspend"}]}
    with pytest.raises(SimulationError, match="overspend") as exc:
        signer.simulate_group([signed_payment], NETWORK)
    assert isinstance(exc.value, RuntimeError)

    assert signer.send_group([signed_payment], NETWORK) == "TXID"

    waited = {}
    monkeypatch.setattr(
        transaction,
        "wait_for_confirmation",
        lambda c, txid, rounds: waited.update(client=c, txid=txid, rounds=rounds),
    )
    assert signer.confirm_transaction("TXID", NETWORK, rounds=7) is None
    assert waited == {"client": client, "txid": "TXID", "rounds": 7}


def test_signed_payload_round_trips_through_b64():
    a, b = acct(), acct()
    out = PayerAvmSigner(a.sk).sign_transactions([raw(pay(a.addr, b.addr, 3))], [0])
    assert b64(_decode(out[0])) == base64.b64encode(out[0]).decode()
