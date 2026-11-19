"""Offline tests for the server scheme, the V1 wrappers, and the registration helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from algosdk import encoding
from avm_builders import ASA, NETWORK, acct, b64, mock_fac_signer, pay, sign, sp
from x402.schemas import AssetAmount, SupportedKind

from x402_algorand.constants import (
    ALGORAND_MAINNET_CAIP2,
    ALGORAND_TESTNET_CAIP2,
    ERR_AMOUNT_INSUFFICIENT,
    TESTNET_GENESIS_HASH,
    USDC_MAINNET_ASA_ID,
    USDC_TESTNET_ASA_ID,
    V1_NETWORKS,
)
from x402_algorand.errors import NetworkError
from x402_algorand.exact.register import (
    register_exact_avm_client,
    register_exact_avm_facilitator,
    register_exact_avm_server,
)
from x402_algorand.exact.server import ExactAvmScheme as ServerScheme
from x402_algorand.exact.v1 import ExactAvmSchemeV1Client, ExactAvmSchemeV1Facilitator

UNREGISTERED = "algorand:zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"


# ---------------------------------------------------------------------------
# server: parse_price
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "network", "expected"),
    [
        ("$0.01", ALGORAND_TESTNET_CAIP2, ("10000", str(USDC_TESTNET_ASA_ID))),
        ("1,000.5", ALGORAND_MAINNET_CAIP2, ("1000500000", str(USDC_MAINNET_ASA_ID))),
        (0.25, "algorand-testnet", ("250000", str(USDC_TESTNET_ASA_ID))),
        (2, ALGORAND_MAINNET_CAIP2, ("2000000", str(USDC_MAINNET_ASA_ID))),
        ({"amount": "10000", "asset": "0"}, ALGORAND_TESTNET_CAIP2, ("10000", "0")),
        ({"amount": "7"}, ALGORAND_TESTNET_CAIP2, ("7", str(USDC_TESTNET_ASA_ID))),
    ],
)
def test_parse_price(price, network, expected):
    result = ServerScheme().parse_price(price, network)
    assert (result.amount, result.asset) == expected


def test_parse_price_asset_amount_object():
    scheme = ServerScheme()
    given = AssetAmount(amount="5", asset="0")
    assert scheme.parse_price(given, NETWORK) is given
    blank = AssetAmount(amount="5", asset="")
    assert scheme.parse_price(blank, NETWORK).asset == str(USDC_TESTNET_ASA_ID)


def test_custom_money_parsers_are_tried_in_order():
    calls = []

    def first(amount, network):
        calls.append(("first", amount, network))
        return None

    def second(amount, network):
        calls.append(("second", amount, network))
        return AssetAmount(amount=str(int(amount * 1_000_000)), asset="0")

    scheme = ServerScheme()
    assert scheme.register_money_parser(first).register_money_parser(second) is scheme
    result = scheme.parse_price("$0.5", NETWORK)
    assert (result.amount, result.asset) == ("500000", "0")
    assert [c[0] for c in calls] == ["first", "second"]


def test_parse_price_unknown_network_raises_network_error():
    with pytest.raises(NetworkError):
        ServerScheme().parse_price("$1", UNREGISTERED)


# ---------------------------------------------------------------------------
# server: enhance_payment_requirements / get_asset_info
# ---------------------------------------------------------------------------


def _kind(extra=None, network=NETWORK):
    return SupportedKind(x402_version=2, scheme="exact", network=network, extra=extra)


def test_enhance_adds_decimals_fee_payer_and_genesis():
    from avm_builders import req

    r = req(acct().addr)
    r.extra = None
    out = ServerScheme().enhance_payment_requirements(r, _kind({"feePayer": "FP"}), [])
    assert out.extra == {
        "decimals": 6,
        "feePayer": "FP",
        "genesisHash": TESTNET_GENESIS_HASH,
        "genesisId": "testnet-v1.0",
    }


def test_enhance_keeps_existing_values_and_skips_unknown_network():
    from avm_builders import req

    r = req(acct().addr, extra={"decimals": 2, "genesisId": "custom"})
    out = ServerScheme().enhance_payment_requirements(r, _kind(), [])
    assert out.extra["decimals"] == 2
    assert out.extra["genesisId"] == "custom"
    assert "feePayer" not in out.extra

    r2 = req(acct().addr, network=UNREGISTERED)
    out2 = ServerScheme().enhance_payment_requirements(r2, _kind(network=UNREGISTERED), [])
    assert "genesisHash" not in out2.extra


def test_get_asset_info():
    scheme = ServerScheme()
    usdc = scheme.get_asset_info(NETWORK, str(USDC_TESTNET_ASA_ID))
    assert usdc == {"asa_id": USDC_TESTNET_ASA_ID, "name": "USDC", "decimals": 6}
    assert scheme.get_asset_info(NETWORK, "123")["name"] == "ASA-123"


# ---------------------------------------------------------------------------
# V1 facilitator / client
# ---------------------------------------------------------------------------


def _v1_dicts(payer, pay_to, amount_paid=5000, amount_required="5000"):
    group = [b64(sign(pay(payer.addr, pay_to, amount_paid), payer.sk))]
    requirements = {
        "scheme": "exact",
        "network": "algorand-testnet",
        "maxAmountRequired": amount_required,
        "payTo": pay_to,
        "asset": "0",
        "maxTimeoutSeconds": 60,
    }
    v1_payload = {
        **requirements,
        "payload": {"paymentGroup": group, "paymentIndex": 0},
        "resource": "https://example.test/r",
    }
    return v1_payload, requirements, group


def test_v1_facilitator_verify_and_settle():
    payer, server = acct(), acct()
    signer = mock_fac_signer(["FP"])
    fac = ExactAvmSchemeV1Facilitator(signer)
    assert fac.get_signers("algorand-testnet") == ["FP"]
    assert fac.get_extra("algorand-testnet") == {"feePayer": "FP"}

    v1_payload, requirements, group = _v1_dicts(payer, server.addr)
    assert fac.verify(v1_payload, requirements) == {
        "isValid": True,
        "invalidReason": None,
        "payer": payer.addr,
    }
    settled = fac.settle(v1_payload, requirements)
    assert settled["success"] is True
    assert settled["network"] == "algorand-testnet"
    assert settled["transaction"] == encoding.msgpack_decode(group[0]).get_txid()


def test_v1_facilitator_rejects_wrong_amount():
    payer, server = acct(), acct()
    fac = ExactAvmSchemeV1Facilitator(mock_fac_signer([]))
    v1_payload, requirements, _ = _v1_dicts(payer, server.addr, amount_required="6000")
    v1_payload["maxAmountRequired"] = "6000"
    result = fac.verify(v1_payload, requirements)
    assert result["isValid"] is False
    assert result["invalidReason"] == ERR_AMOUNT_INSUFFICIENT
    settled = fac.settle(v1_payload, requirements)
    assert settled["success"] is False
    assert settled["errorReason"] == ERR_AMOUNT_INSUFFICIENT


def test_v1_client_builds_payload_and_finds_default_asset():
    a, server = acct(), acct()
    from x402_algorand import PayerAvmSigner

    client = ExactAvmSchemeV1Client(PayerAvmSigner(a.sk), algod_url="http://mock:4001")
    algod = MagicMock()
    algod.suggested_params.return_value = sp()
    client._v2_scheme._clients[NETWORK] = algod
    out = client.create_payment_payload(
        {
            "scheme": "exact",
            "network": "algorand-testnet",
            "maxAmountRequired": "1234",
            "payTo": server.addr,
            "asset": "0",
            "maxTimeoutSeconds": 60,
        }
    )
    assert out["paymentIndex"] == 0
    assert len(out["paymentGroup"]) == 1
    assert client.find_default_asset("0", "algorand-testnet")["symbol"] == "ALGO"
    assert client.find_default_asset(str(ASA), "algorand-testnet")["symbol"] == "USDC"


# ---------------------------------------------------------------------------
# registration helpers
# ---------------------------------------------------------------------------


def test_register_client_with_networks_and_policies():
    client = MagicMock()
    policy = object()
    assert (
        register_exact_avm_client(client, MagicMock(), networks=NETWORK, policies=[policy])
        is client
    )
    assert client.register.call_args[0][0] == NETWORK
    assert [c[0][0] for c in client.register_v1.call_args_list] == V1_NETWORKS
    client.register_policy.assert_called_once_with(policy)

    client2 = MagicMock()
    register_exact_avm_client(client2, MagicMock(), networks=[NETWORK, ALGORAND_MAINNET_CAIP2])
    assert [c[0][0] for c in client2.register.call_args_list] == [NETWORK, ALGORAND_MAINNET_CAIP2]


@pytest.mark.parametrize(
    ("networks", "expected"),
    [
        (None, ["algorand:*"]),
        (NETWORK, [NETWORK]),
        ([NETWORK, UNREGISTERED], [NETWORK, UNREGISTERED]),
    ],
)
def test_register_server(networks, expected):
    server = MagicMock()
    assert register_exact_avm_server(server, networks) is server
    assert [c[0][0] for c in server.register.call_args_list] == expected
    assert all(isinstance(c[0][1], ServerScheme) for c in server.register.call_args_list)


@pytest.mark.parametrize("networks", [NETWORK, [NETWORK]])
def test_register_facilitator(networks):
    fac = MagicMock()
    assert register_exact_avm_facilitator(fac, mock_fac_signer([]), networks) is fac
    assert fac.register.call_args[0][0] == [NETWORK]
    assert fac.register_v1.call_args[0][0] == V1_NETWORKS


# ---------------------------------------------------------------------------
# end to end through the official SDK (offline: mocked algod)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", [1, 2])
def test_official_sync_client_and_facilitator_round_trip(version, monkeypatch):
    from algosdk import transaction
    from algosdk.v2client import algod as algod_module
    from x402 import x402ClientSync, x402FacilitatorSync
    from x402.schemas import PaymentRequired
    from x402.schemas.v1 import PaymentRequiredV1, PaymentRequirementsV1

    from x402_algorand import PayerAvmSigner, ServerAvmSigner

    payer, server = acct(), acct()
    algod = MagicMock()
    algod.suggested_params.return_value = sp()
    algod.simulate_transactions.return_value = {"txn-groups": [{}]}
    algod.send_transactions.return_value = "SENT"
    monkeypatch.setattr(algod_module, "AlgodClient", lambda *a, **k: algod)
    monkeypatch.setattr(transaction, "wait_for_confirmation", lambda *a, **k: {})

    client = x402ClientSync()
    register_exact_avm_client(client, PayerAvmSigner(payer.sk))
    facilitator = x402FacilitatorSync()
    register_exact_avm_facilitator(facilitator, ServerAvmSigner(server.sk, algod), NETWORK)

    if version == 2:
        from avm_builders import req

        requirements = req(server.addr, amount="5000", asset="0")
        required = PaymentRequired(x402_version=2, accepts=[requirements])
    else:
        requirements = PaymentRequirementsV1(
            scheme="exact",
            network="algorand-testnet",
            max_amount_required="5000",
            resource="https://example.test/r",
            pay_to=server.addr,
            max_timeout_seconds=60,
            asset="0",
        )
        required = PaymentRequiredV1(accepts=[requirements])

    payload = client.create_payment_payload(required)
    verified = facilitator.verify(payload, requirements)
    assert verified.is_valid, verified.invalid_message
    assert verified.payer == payer.addr

    settled = facilitator.settle(payload, requirements)
    assert settled.success, settled.error_message
    payment_b64 = payload.payload["paymentGroup"][0]
    assert settled.transaction == encoding.msgpack_decode(payment_b64).get_txid()
