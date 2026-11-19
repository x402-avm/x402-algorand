"""Offline, table-driven tests for the V2 exact facilitator (verify and settle).

Every ``invalid_reason`` the facilitator can produce without a network is covered,
using real algosdk transactions and a mocked ``FacilitatorAvmSigner``.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from algosdk import encoding, transaction
from algosdk.atomic_transaction_composer import MultisigTransactionSigner
from avm_builders import (
    ASA,
    OTHER_GH,
    Acct,
    acct,
    axfer,
    b64,
    fee_payer_group,
    mock_fac_signer,
    pay,
    payload,
    req,
    sign,
    sp,
)

from x402_algorand.constants import (
    ERR_AMOUNT_INSUFFICIENT,
    ERR_BLOCKED_TXN_TYPE,
    ERR_CLOSE_TO_DETECTED,
    ERR_EMPTY_GROUP,
    ERR_FEE_PAYER_HAS_AMOUNT,
    ERR_FEE_PAYER_HAS_CLOSE,
    ERR_FEE_PAYER_HAS_REKEY,
    ERR_FEE_PAYER_INVALID_TXN,
    ERR_FEE_PAYER_MISSING,
    ERR_FEE_PAYER_NOT_MANAGED,
    ERR_FEE_PAYER_TRANSFERRING,
    ERR_GENESIS_HASH_MISMATCH,
    ERR_GROUP_DECODE_FAILED,
    ERR_GROUP_TOO_LARGE,
    ERR_INVALID_ASSET_ID,
    ERR_INVALID_GROUP_ID,
    ERR_INVALID_PAYMENT_INDEX,
    ERR_INVALID_SIGNATURE,
    ERR_MISSING_GROUP_ID,
    ERR_MISSING_SIGNATURE,
    ERR_NETWORK_MISMATCH,
    ERR_RECIPIENT_MISMATCH,
    ERR_REKEY_DETECTED,
    ERR_SIMULATION_FAILED,
    ERR_TRANSACTION_FAILED,
    ERR_UNSUPPORTED_SCHEME,
    MAX_GROUP_SIZE,
)
from x402_algorand.exact.facilitator import ExactAvmScheme
from x402_algorand.types import DecodedTransactionInfo
from x402_algorand.utils import validate_fee_payer_transaction


@dataclass
class World:
    payer: Acct = field(default_factory=acct)
    server: Acct = field(default_factory=acct)
    fee_payer: Acct = field(default_factory=acct)
    other: Acct = field(default_factory=acct)

    def signed_pay(self, amount: int = 5000, **kw) -> str:
        return b64(sign(pay(self.payer.addr, self.server.addr, amount, **kw), self.payer.sk))


@dataclass
class Case:
    """Builds (payload, requirements) for a world; signer manages ``fee_payer``."""

    build: Callable[[World], tuple]
    reason: str | None


def _simple(w: World, group: list[str], index: int = 0, **req_kw):
    r = req(w.server.addr, **req_kw)
    return payload(group, index, r), r


def _grouped(*txns):
    return list(transaction.assign_group_id(list(txns)))


def _case_unsupported_scheme(w):
    r = req(w.server.addr)
    accepted = req(w.server.addr, scheme="upto")
    return payload([w.signed_pay()], 0, accepted), r


def _case_network_mismatch(w):
    r = req(w.server.addr)
    accepted = req(w.server.addr, network="algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k")
    return payload([w.signed_pay()], 0, accepted), r


def _case_missing_group_id(w):
    t1 = pay(w.payer.addr, w.server.addr, 5000)
    t2 = pay(w.payer.addr, w.payer.addr, 0)
    return _simple(w, [b64(sign(t1, w.payer.sk)), b64(sign(t2, w.payer.sk))])


def _case_group_id_mismatch(w):
    a1, _ = _grouped(pay(w.payer.addr, w.server.addr, 5000), pay(w.payer.addr, w.payer.addr, 0))
    _, b2 = _grouped(pay(w.payer.addr, w.server.addr, 1), pay(w.payer.addr, w.payer.addr, 1))
    return _simple(w, [b64(sign(a1, w.payer.sk)), b64(sign(b2, w.payer.sk))])


def _case_genesis_mismatch(w):
    return _simple(w, [w.signed_pay(gh=OTHER_GH)])


def _case_close_to(w):
    return _simple(w, [w.signed_pay(close_remainder_to=w.other.addr)])


def _case_asset_close_to(w):
    t = axfer(w.payer.addr, w.server.addr, 5000, close_assets_to=w.other.addr)
    return _simple(w, [b64(sign(t, w.payer.sk))], asset=str(ASA))


def _case_keyreg(w):
    p = pay(w.payer.addr, w.server.addr, 5000)
    k = transaction.KeyregOfflineTxn(w.payer.addr, sp())
    p, k = _grouped(p, k)
    return _simple(w, [b64(sign(p, w.payer.sk)), b64(sign(k, w.payer.sk))])


def _case_unbalanced_rekey(w):
    return _simple(w, [w.signed_pay(rekey_to=w.other.addr)])


def _case_alg_required_got_axfer(w):
    t = axfer(w.payer.addr, w.server.addr, 5000)
    return _simple(w, [b64(sign(t, w.payer.sk))])


def _case_asa_required_got_pay(w):
    return _simple(w, [w.signed_pay()], asset=str(ASA))


def _case_wrong_asa(w):
    t = axfer(w.payer.addr, w.server.addr, 5000, index=ASA + 1)
    return _simple(w, [b64(sign(t, w.payer.sk))], asset=str(ASA))


def _case_pay_wrong_receiver(w):
    t = pay(w.payer.addr, w.other.addr, 5000)
    return _simple(w, [b64(sign(t, w.payer.sk))])


def _case_axfer_wrong_receiver(w):
    t = axfer(w.payer.addr, w.other.addr, 5000)
    return _simple(w, [b64(sign(t, w.payer.sk))], asset=str(ASA))


def _case_amount_low(w):
    return _simple(w, [w.signed_pay(4999)])


def _case_amount_high(w):
    # The exact scheme requires the amount to match, not exceed.
    return _simple(w, [w.signed_pay(5001)])


def _case_asa_amount_low(w):
    t = axfer(w.payer.addr, w.server.addr, 1)
    return _simple(w, [b64(sign(t, w.payer.sk))], asset=str(ASA))


def _case_unsigned(w):
    return _simple(w, [b64(pay(w.payer.addr, w.server.addr, 5000))])


def _case_forged_signature(w):
    t = pay(w.payer.addr, w.server.addr, 5000)
    forged = sign(t, w.other.sk)  # signed by someone else, then sgnr stripped
    forged.authorizing_address = None
    return _simple(w, [b64(forged)])


def _case_fee_payer_pays(w):
    t = pay(w.fee_payer.addr, w.server.addr, 5000)
    return _simple(w, [b64(sign(t, w.fee_payer.sk))])


def _case_fee_payer_not_managed(w):
    group = fee_payer_group(w.payer, w.other.addr, w.server.addr)
    return _simple(w, group, 1, extra={"feePayer": w.other.addr})


def _case_fee_payer_missing(w):
    return _simple(w, [w.signed_pay()], extra={"feePayer": w.fee_payer.addr})


def _fp_case(**kw):
    def build(w):
        group = fee_payer_group(w.payer, w.fee_payer.addr, w.server.addr, **kw)
        return _simple(w, group, 1, extra={"feePayer": w.fee_payer.addr})

    return build


def _case_fee_payer_not_self_payment(w):
    fp = pay(w.fee_payer.addr, w.other.addr, 0, fee=2000)
    p = pay(w.payer.addr, w.server.addr, 5000, fee=0)
    fp, p = _grouped(fp, p)
    group = [b64(fp), b64(sign(p, w.payer.sk))]
    return _simple(w, group, 1, extra={"feePayer": w.fee_payer.addr})


def _case_fee_payer_axfer(w):
    fp = axfer(w.fee_payer.addr, w.fee_payer.addr, 0, fee=2000)
    p = pay(w.payer.addr, w.server.addr, 5000, fee=0)
    fp, p = _grouped(fp, p)
    group = [b64(fp), b64(sign(p, w.payer.sk))]
    return _simple(w, group, 1, extra={"feePayer": w.fee_payer.addr})


def _case_fee_payer_rekey_sandwich(w):
    # A balanced rekey sandwich passes the group check but the fee payer may not rekey.
    fp1 = pay(w.fee_payer.addr, w.fee_payer.addr, 0, fee=3000, rekey_to=w.other.addr)
    p = pay(w.payer.addr, w.server.addr, 5000, fee=0)
    fp2 = pay(w.fee_payer.addr, w.fee_payer.addr, 0, fee=0, rekey_to=w.fee_payer.addr)
    fp1, p, fp2 = _grouped(fp1, p, fp2)
    group = [b64(fp1), b64(sign(p, w.payer.sk)), b64(fp2)]
    return _simple(w, group, 1, extra={"feePayer": w.fee_payer.addr})


def _case_extra_facilitator_txn(w):
    # Spec: *every* transaction sent by the facilitator is checked, not only the first.
    fp = pay(w.fee_payer.addr, w.fee_payer.addr, 0, fee=3000)
    p = pay(w.payer.addr, w.server.addr, 5000, fee=0)
    drain = pay(w.fee_payer.addr, w.payer.addr, 1_000_000, fee=0)
    fp, p, drain = _grouped(fp, p, drain)
    group = [b64(fp), b64(sign(p, w.payer.sk)), b64(drain)]
    return _simple(w, group, 1, extra={"feePayer": w.fee_payer.addr})


CASES: dict[str, Case] = {
    "unsupported_scheme": Case(_case_unsupported_scheme, ERR_UNSUPPORTED_SCHEME),
    "network_mismatch": Case(_case_network_mismatch, ERR_NETWORK_MISMATCH),
    "empty_group": Case(lambda w: _simple(w, []), ERR_EMPTY_GROUP),
    "group_too_large": Case(
        lambda w: _simple(w, [w.signed_pay()] * (MAX_GROUP_SIZE + 1)), ERR_GROUP_TOO_LARGE
    ),
    "index_negative": Case(lambda w: _simple(w, [w.signed_pay()], -1), ERR_INVALID_PAYMENT_INDEX),
    "index_too_big": Case(lambda w: _simple(w, [w.signed_pay()], 1), ERR_INVALID_PAYMENT_INDEX),
    "not_base64": Case(lambda w: _simple(w, ["***not base64***"]), ERR_GROUP_DECODE_FAILED),
    "not_msgpack": Case(
        lambda w: _simple(w, [base64.b64encode(b"\xc1garbage").decode()]),
        ERR_GROUP_DECODE_FAILED,
    ),
    "missing_group_id": Case(_case_missing_group_id, ERR_MISSING_GROUP_ID),
    "group_id_mismatch": Case(_case_group_id_mismatch, ERR_INVALID_GROUP_ID),
    "genesis_mismatch": Case(_case_genesis_mismatch, ERR_GENESIS_HASH_MISMATCH),
    "close_to": Case(_case_close_to, ERR_CLOSE_TO_DETECTED),
    "asset_close_to": Case(_case_asset_close_to, ERR_CLOSE_TO_DETECTED),
    "keyreg": Case(_case_keyreg, ERR_BLOCKED_TXN_TYPE),
    "unbalanced_rekey": Case(_case_unbalanced_rekey, ERR_REKEY_DETECTED),
    "algo_required_got_axfer": Case(_case_alg_required_got_axfer, ERR_INVALID_ASSET_ID),
    "asa_required_got_pay": Case(_case_asa_required_got_pay, ERR_INVALID_ASSET_ID),
    "wrong_asa": Case(_case_wrong_asa, ERR_INVALID_ASSET_ID),
    "pay_wrong_receiver": Case(_case_pay_wrong_receiver, ERR_RECIPIENT_MISMATCH),
    "axfer_wrong_receiver": Case(_case_axfer_wrong_receiver, ERR_RECIPIENT_MISMATCH),
    "amount_low": Case(_case_amount_low, ERR_AMOUNT_INSUFFICIENT),
    "amount_high": Case(_case_amount_high, ERR_AMOUNT_INSUFFICIENT),
    "asa_amount_low": Case(_case_asa_amount_low, ERR_AMOUNT_INSUFFICIENT),
    "unsigned": Case(_case_unsigned, ERR_MISSING_SIGNATURE),
    "forged_signature": Case(_case_forged_signature, ERR_INVALID_SIGNATURE),
    "fee_payer_pays": Case(_case_fee_payer_pays, ERR_FEE_PAYER_TRANSFERRING),
    "fee_payer_not_managed": Case(_case_fee_payer_not_managed, ERR_FEE_PAYER_NOT_MANAGED),
    "fee_payer_missing": Case(_case_fee_payer_missing, ERR_FEE_PAYER_MISSING),
    "fee_payer_fee_too_high": Case(_fp_case(fee_payer_fee=16_001), ERR_FEE_PAYER_INVALID_TXN),
    "fee_payer_not_self": Case(_case_fee_payer_not_self_payment, ERR_FEE_PAYER_INVALID_TXN),
    "fee_payer_axfer": Case(_case_fee_payer_axfer, ERR_FEE_PAYER_INVALID_TXN),
    "fee_payer_rekey": Case(_case_fee_payer_rekey_sandwich, ERR_FEE_PAYER_HAS_REKEY),
    "extra_facilitator_txn": Case(_case_extra_facilitator_txn, ERR_FEE_PAYER_INVALID_TXN),
    # valid payloads
    "valid_algo": Case(lambda w: _simple(w, [w.signed_pay()]), None),
    "valid_asa": Case(
        lambda w: _simple(
            w, [b64(sign(axfer(w.payer.addr, w.server.addr, 5000), w.payer.sk))], asset=str(ASA)
        ),
        None,
    ),
    "valid_fee_payer_algo": Case(_fp_case(), None),
    "valid_fee_payer_asa": Case(
        lambda w: _simple(
            w,
            fee_payer_group(w.payer, w.fee_payer.addr, w.server.addr, asset=ASA),
            1,
            asset=str(ASA),
            extra={"feePayer": w.fee_payer.addr},
        ),
        None,
    ),
}


@pytest.mark.parametrize("name", list(CASES))
def test_verify_table(name: str):
    w = World()
    case = CASES[name]
    pl, r = case.build(w)
    signer = mock_fac_signer([w.fee_payer.addr])
    result = ExactAvmScheme(signer).verify(pl, r)
    assert result.invalid_reason == case.reason, result.invalid_message
    assert result.is_valid is (case.reason is None)
    if case.reason is None:
        assert result.payer == w.payer.addr
        signer.simulate_group.assert_called_once()


def test_verify_signs_fee_payer_before_simulating():
    w = World()
    pl, r = _fp_case()(w)
    signer = mock_fac_signer([w.fee_payer.addr])
    assert ExactAvmScheme(signer).verify(pl, r).is_valid
    _, fee_payer, indexes, _ = signer.sign_group.call_args[0]
    assert fee_payer == w.fee_payer.addr
    assert indexes == [0]


def test_verify_sign_failure_is_reported():
    w = World()
    pl, r = _fp_case()(w)
    signer = mock_fac_signer([w.fee_payer.addr])
    signer.sign_group.side_effect = RuntimeError("hsm offline")
    result = ExactAvmScheme(signer).verify(pl, r)
    assert result.invalid_reason == ERR_SIMULATION_FAILED
    assert "hsm offline" in result.invalid_message


def test_verify_simulation_failure_is_reported():
    w = World()
    pl, r = _simple(w, [w.signed_pay()])
    signer = mock_fac_signer([w.fee_payer.addr])
    signer.simulate_group.side_effect = RuntimeError("overspend")
    result = ExactAvmScheme(signer).verify(pl, r)
    assert result.is_valid is False
    assert result.invalid_reason == ERR_SIMULATION_FAILED
    assert "overspend" in result.invalid_message
    assert result.payer == w.payer.addr


def test_verify_accepts_rekeyed_payer_signed_by_auth_address():
    w = World()
    t = pay(w.payer.addr, w.server.addr, 5000)
    stx = sign(t, w.other.sk)  # algosdk sets sgnr = other (payer rekeyed to other)
    assert stx.authorizing_address == w.other.addr
    pl, r = _simple(w, [b64(stx)])
    assert ExactAvmScheme(mock_fac_signer([])).verify(pl, r).is_valid


def _msig(w: World, threshold: int, signers: list[Acct]):
    """A payment from a 2-member multisig, signed by ``signers`` (via the current API)."""
    members = [w.payer.addr, w.other.addr]
    msig = transaction.Multisig(1, threshold, members)
    t = pay(msig.address(), w.server.addr, 5000)
    keys = [a.sk for a in signers]
    return MultisigTransactionSigner(msig, keys).sign_transactions([t], [0])[0]


def test_verify_multisig_payment():
    w = World()
    ok = _msig(w, 2, [w.payer, w.other])
    pl, r = _simple(w, [b64(ok)])
    assert ExactAvmScheme(mock_fac_signer([])).verify(pl, r).is_valid

    short = _msig(w, 2, [w.payer])
    pl, r = _simple(w, [b64(short)])
    assert ExactAvmScheme(mock_fac_signer([])).verify(pl, r).invalid_reason == (
        ERR_INVALID_SIGNATURE
    )


def test_verify_logicsig_contract_account_payment():
    w = World()
    program = b"\x06\x81\x01"  # #pragma version 6; int 1
    lsig = transaction.LogicSigAccount(program)
    t = pay(lsig.address(), w.server.addr, 5000)
    ltx = transaction.LogicSigTransaction(t, lsig)
    pl, r = _simple(w, [b64(ltx)])
    result = ExactAvmScheme(mock_fac_signer([])).verify(pl, r)
    assert result.is_valid, result.invalid_message

    # A delegated logic signature whose signature is not the sender's is rejected offline.
    forged = transaction.LogicSig(program)
    forged.sig = base64.b64encode(b"\x01" * 64).decode()
    t2 = pay(w.payer.addr, w.server.addr, 5000)
    bad = transaction.LogicSigTransaction(t2, forged)
    pl, r = _simple(w, [b64(bad)])
    assert ExactAvmScheme(mock_fac_signer([])).verify(pl, r).invalid_reason == (
        ERR_INVALID_SIGNATURE
    )


def test_validate_fee_payer_transaction_rules():
    fp = acct().addr
    base = dict(type="pay", sender=fp, fee=2000, first_valid=1, last_valid=2, genesis_hash="")
    assert validate_fee_payer_transaction(DecodedTransactionInfo(**base, receiver=fp), fp) is None
    other = acct().addr
    cases = [
        (dict(receiver=fp, amount=1), ERR_FEE_PAYER_HAS_AMOUNT),
        (dict(receiver=fp, close_remainder_to=other), ERR_FEE_PAYER_HAS_CLOSE),
        (dict(receiver=fp, rekey_to=other), ERR_FEE_PAYER_HAS_REKEY),
        (dict(receiver=other), ERR_FEE_PAYER_INVALID_TXN),
    ]
    for fields, reason in cases:
        assert validate_fee_payer_transaction(DecodedTransactionInfo(**base, **fields), fp) == (
            reason
        )
    wrong_sender = DecodedTransactionInfo(**{**base, "sender": other}, receiver=fp)
    assert validate_fee_payer_transaction(wrong_sender, fp) == ERR_FEE_PAYER_INVALID_TXN


def test_get_extra_and_signers():
    signer = mock_fac_signer(["A", "B"])
    scheme = ExactAvmScheme(signer)
    assert scheme.get_extra("algorand:x")["feePayer"] in {"A", "B"}
    assert scheme.get_signers("algorand:x") == ["A", "B"]
    assert ExactAvmScheme(mock_fac_signer([])).get_extra("algorand:x") is None


# ---------------------------------------------------------------------------
# settle
# ---------------------------------------------------------------------------


def _txid(b64_txn: str) -> str:
    return encoding.msgpack_decode(b64_txn).get_txid()


def test_settle_returns_payment_txid_and_signs_fee_payer():
    w = World()
    pl, r = _fp_case()(w)
    signer = mock_fac_signer([w.fee_payer.addr])
    result = ExactAvmScheme(signer).settle(pl, r)
    assert result.success is True
    assert result.payer == w.payer.addr
    # Spec: the response carries the ID of paymentGroup[paymentIndex], not the fee txn.
    assert result.transaction == _txid(pl.payload["paymentGroup"][1])
    signer.send_group.assert_called_once()
    signer.confirm_transaction.assert_called_once_with("SENT", r.network)
    # signed once in verify (for simulation) and once for submission
    assert signer.sign_group.call_count == 2


def test_settle_without_fee_payer():
    w = World()
    pl, r = _simple(w, [w.signed_pay()])
    signer = mock_fac_signer([])
    result = ExactAvmScheme(signer).settle(pl, r)
    assert result.success is True
    assert result.transaction == _txid(pl.payload["paymentGroup"][0])
    signer.sign_group.assert_not_called()


def test_settle_rejects_invalid_payment_without_sending():
    w = World()
    pl, r = _simple(w, [w.signed_pay(1)])
    signer = mock_fac_signer([])
    result = ExactAvmScheme(signer).settle(pl, r)
    assert result.success is False
    assert result.error_reason == ERR_AMOUNT_INSUFFICIENT
    assert result.transaction == ""
    signer.send_group.assert_not_called()


@pytest.mark.parametrize("failing", ["send_group", "confirm_transaction"])
def test_settle_reports_submission_failure(failing: str):
    w = World()
    pl, r = _simple(w, [w.signed_pay()])
    signer = mock_fac_signer([])
    getattr(signer, failing).side_effect = RuntimeError("node down")
    result = ExactAvmScheme(signer).settle(pl, r)
    assert result.success is False
    assert result.error_reason == ERR_TRANSACTION_FAILED
    assert result.error_message == "node down"
    assert result.transaction == _txid(pl.payload["paymentGroup"][0])
    assert result.payer == w.payer.addr
