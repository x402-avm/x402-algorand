"""Offline builders for Algorand transactions and x402 payloads used by unit tests."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from algosdk import account, encoding, transaction
from algosdk.atomic_transaction_composer import AccountTransactionSigner
from x402.schemas import PaymentPayload, PaymentRequirements

from x402_algorand.constants import (
    ALGORAND_MAINNET_CAIP2,
    ALGORAND_TESTNET_CAIP2,
    MAINNET_GENESIS_HASH,
    TESTNET_GENESIS_HASH,
)

NETWORK = ALGORAND_TESTNET_CAIP2
GH = TESTNET_GENESIS_HASH
OTHER_NETWORK = ALGORAND_MAINNET_CAIP2
OTHER_GH = MAINNET_GENESIS_HASH
ASA = 10458941


@dataclass
class Acct:
    sk: str
    addr: str


def acct() -> Acct:
    sk, addr = account.generate_account()
    return Acct(sk, addr)


def sp(fee: int = 1000, gh: str = GH) -> transaction.SuggestedParams:
    return transaction.SuggestedParams(
        fee=fee, first=1, last=1000, gh=gh, gen="testnet-v1.0", flat_fee=True, min_fee=1000
    )


def pay(sender: str, receiver: str, amt: int, *, fee: int = 1000, gh: str = GH, **kw: Any):
    return transaction.PaymentTxn(sender, sp(fee, gh), receiver, amt, **kw)


def axfer(sender: str, receiver: str, amt: int, index: int = ASA, *, fee: int = 1000, **kw: Any):
    return transaction.AssetTransferTxn(sender, sp(fee), receiver, amt, index, **kw)


def sign(txn: transaction.Transaction, sk: str):
    return AccountTransactionSigner(sk).sign_transactions([txn], [0])[0]


def b64(obj: Any) -> str:
    """Base64 msgpack of a Transaction / SignedTransaction (what paymentGroup holds)."""
    return encoding.msgpack_encode(obj)


def raw(obj: Any) -> bytes:
    return base64.b64decode(encoding.msgpack_encode(obj))


def req(
    pay_to: str,
    amount: str = "5000",
    asset: str = "0",
    extra: dict[str, Any] | None = None,
    network: str = NETWORK,
    scheme: str = "exact",
) -> PaymentRequirements:
    kwargs: dict[str, Any] = {} if extra is None else {"extra": extra}
    return PaymentRequirements(
        scheme=scheme,
        network=network,
        asset=asset,
        amount=amount,
        pay_to=pay_to,
        max_timeout_seconds=300,
        **kwargs,
    )


def payload(
    group: list[str], index: int, accepted: PaymentRequirements, version: int = 2
) -> PaymentPayload:
    return PaymentPayload(
        x402_version=version,
        payload={"paymentGroup": group, "paymentIndex": index},
        accepted=accepted,
    )


def mock_fac_signer(addresses: list[str]) -> MagicMock:
    signer = MagicMock()
    signer.get_addresses.return_value = list(addresses)
    signer.sign_group.side_effect = lambda group, fee_payer, idx, net: list(group)
    signer.simulate_group.return_value = None
    signer.send_group.return_value = "SENT"
    signer.confirm_transaction.return_value = None
    return signer


def fee_payer_group(
    payer: Acct,
    fee_payer: str,
    pay_to: str,
    amount: int = 5000,
    *,
    asset: int = 0,
    fee_payer_fee: int = 2000,
    fee_payer_kw: dict[str, Any] | None = None,
) -> list[str]:
    """[fee payer self-payment (unsigned), client payment (signed)] as base64."""
    fp = pay(fee_payer, fee_payer, 0, fee=fee_payer_fee, **(fee_payer_kw or {}))
    if asset:
        p = axfer(payer.addr, pay_to, amount, asset, fee=0)
    else:
        p = pay(payer.addr, pay_to, amount, fee=0)
    fp, p = transaction.assign_group_id([fp, p])
    return [b64(fp), b64(sign(p, payer.sk))]
