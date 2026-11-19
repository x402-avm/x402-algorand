"""Public network simulation tests for x402-algorand (TestNet and MainNet).

Performs read-only validation against real MainNet and TestNet ledgers without spending funds:
1. Queries the public AlgoNode indexer to identify real funded accounts holding USDC and ALGO.
2. Constructs payment groups for ALGO (asset 0) and USDC, both with and without fee payers.
3. Evaluates the constructed atomic groups via Algod's simulate endpoint using empty signatures.
4. Confirms that all test cases simulate successfully without on-chain execution.

Only executed when PUBLIC_NETS=1.
"""

import httpx
import pytest
from algosdk import encoding, transaction
from algosdk.v2client import algod
from algosdk.v2client.models import SimulateRequest, SimulateRequestTransactionGroup
from x402.schemas import PaymentRequirements

from x402_algorand.constants import (
    ALGORAND_MAINNET_CAIP2,
    ALGORAND_TESTNET_CAIP2,
    FALLBACK_ALGOD_MAINNET,
    FALLBACK_ALGOD_TESTNET,
    FALLBACK_INDEXER_MAINNET,
    FALLBACK_INDEXER_TESTNET,
    USDC_MAINNET_ASA_ID,
    USDC_TESTNET_ASA_ID,
)
from x402_algorand.exact.client import ExactAvmScheme as ExactAvmClient

NETWORKS = [
    {
        "name": "testnet",
        "caip": ALGORAND_TESTNET_CAIP2,
        "algod_url": FALLBACK_ALGOD_TESTNET,
        "indexer_url": FALLBACK_INDEXER_TESTNET,
        "usdc_id": USDC_TESTNET_ASA_ID,
    },
    {
        "name": "mainnet",
        "caip": ALGORAND_MAINNET_CAIP2,
        "algod_url": FALLBACK_ALGOD_MAINNET,
        "indexer_url": FALLBACK_INDEXER_MAINNET,
        "usdc_id": USDC_MAINNET_ASA_ID,
    },
]


class _WatchOnly:
    """Watch-only signer providing an address without private keys.

    Generates unsigned transactions for simulate endpoint evaluation.
    """

    def __init__(self, address: str):
        self.address = address

    def sign_transactions(self, txns: list[bytes], indexes: list[int]) -> list[None]:
        return [None] * len(txns)


def get_algod(cfg: dict) -> algod.AlgodClient:
    return algod.AlgodClient("", cfg["algod_url"])


def find_funded_holders(cfg: dict, n: int = 3) -> list[str]:
    """Find real funded accounts holding ALGO and USDC via public indexer."""
    client = get_algod(cfg)
    idx_url = cfg["indexer_url"]
    usdc_id = cfg["usdc_id"]

    try:
        resp = httpx.get(
            f"{idx_url}/v2/assets/{usdc_id}/balances",
            params={"currency-greater-than": 5_000_000, "limit": 40},
            timeout=20,
        )
        balances = resp.json().get("balances", [])
    except Exception as e:
        pytest.skip(f"Could not reach public indexer on {cfg['name']}: {e}")

    out = []
    for b in balances:
        try:
            info = client.account_info(b["address"])
            if info["amount"] - info["min-balance"] > 2_000_000 and not info.get("auth-addr"):
                out.append(b["address"])
                if len(out) == n:
                    return out
        except Exception:
            continue
    if len(out) < n:
        pytest.skip(f"Not enough funded USDC holders found on {cfg['name']}")
    return out


def simulate_group(client: algod.AlgodClient, group_b64: list[str]) -> str | None:
    """Run transaction group through Algod simulation with empty signatures."""
    stx = []
    for b in group_b64:
        d = encoding.msgpack_decode(b)
        stx.append(
            d
            if isinstance(d, transaction.SignedTransaction)
            else transaction.SignedTransaction(d, None)
        )
    req = SimulateRequest(
        txn_groups=[SimulateRequestTransactionGroup(txns=stx)],
        allow_empty_signatures=True,
    )
    res = client.simulate_transactions(req)
    return res["txn-groups"][0].get("failure-message")


@pytest.mark.public_nets
@pytest.mark.parametrize("cfg", NETWORKS, ids=lambda c: c["name"])
@pytest.mark.parametrize("asset_name", ["ALGO", "USDC"])
@pytest.mark.parametrize("fee_payer", [True, False], ids=["with_fee_payer", "without_fee_payer"])
def test_public_network_simulate_payments(cfg, asset_name, fee_payer):
    """Simulate ALGO and USDC payments on real public networks (MainNet and TestNet)."""
    holders = find_funded_holders(cfg, n=3)
    payer, pay_to, fp = holders
    client = get_algod(cfg)

    asset_id = "0" if asset_name == "ALGO" else str(cfg["usdc_id"])
    extra = {"feePayer": fp} if fee_payer else {}

    req = PaymentRequirements(
        scheme="exact",
        network=cfg["caip"],
        asset=asset_id,
        amount="10000",
        pay_to=pay_to,
        max_timeout_seconds=300,
        extra=extra,
    )

    avm_client = ExactAvmClient(_WatchOnly(payer), algod_url=cfg["algod_url"])
    payload = avm_client.create_payment_payload(req)
    failure = simulate_group(client, payload["paymentGroup"])
    assert failure is None, (
        f"Simulation failed on {cfg['name']} {asset_name} (fee_payer={fee_payer}): {failure}"
    )
