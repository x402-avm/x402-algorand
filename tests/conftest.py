"""Pytest configuration and test helpers for x402-algorand."""

import base64
import os
import sys
import types

import pytest
from algosdk import account, encoding, kmd, transaction
from algosdk.atomic_transaction_composer import AccountTransactionSigner
from algosdk.v2client import algod
from algosdk.v2client.models import SimulateRequest, SimulateRequestTransactionGroup

from x402_algorand.utils import caip2_from_genesis_hash, register_network

LOCALNET_ALGOD_URL = os.environ.get("ALGOD_URL", "http://localhost:4001")
LOCALNET_ALGOD_TOKEN = os.environ.get("ALGOD_TOKEN", "a" * 64)
LOCALNET_KMD_URL = os.environ.get("KMD_URL", "http://localhost:4002")
LOCALNET_KMD_TOKEN = os.environ.get("KMD_TOKEN", "a" * 64)


class DefaultAvmSigner:
    """A default implementation of AvmSigner for tests."""

    def __init__(self, private_key: str, algod_client=None):
        self.private_key = private_key
        self.address = account.address_from_private_key(private_key)
        self.algod_client = algod_client

    def get_addresses(self):
        return [self.address]

    def sign_transactions(self, unsigned_txns, indexes):
        signed = []
        for i, txn_bytes in enumerate(unsigned_txns):
            if i in indexes:
                signed.append(self._sign_raw(txn_bytes))
            else:
                signed.append(None)
        return signed

    def sign_transaction(self, txn_bytes, fee_payer, network):
        return self._sign_raw(txn_bytes)

    def sign_group(self, group_bytes, fee_payer, indexes, network):
        signed = list(group_bytes)
        for i in indexes:
            signed[i] = self._sign_raw(group_bytes[i])
        return signed

    def simulate_group(self, group_bytes, network):
        if self.algod_client is None:
            raise RuntimeError("algod_client required")
        decoded = [self._decode(b) for b in group_bytes]
        req = SimulateRequest(
            txn_groups=[SimulateRequestTransactionGroup(txns=decoded)],
            allow_empty_signatures=True,
        )
        result = self.algod_client.simulate_transactions(req)
        txn_groups = result.get("txn-groups", [])
        if txn_groups and txn_groups[0].get("failure-message"):
            raise RuntimeError(txn_groups[0]["failure-message"])
        return result

    def send_group(self, group_bytes, network):
        if not self.algod_client:
            raise RuntimeError("algod_client required")
        decoded = [self._decode(b) for b in group_bytes]
        return self.algod_client.send_transactions(decoded)

    def confirm_transaction(self, txid, network, rounds=4):
        if not self.algod_client:
            raise RuntimeError("algod_client required")
        return transaction.wait_for_confirmation(self.algod_client, txid, rounds)

    def _decode(self, raw_bytes):
        return encoding.msgpack_decode(base64.b64encode(raw_bytes).decode())

    def _sign_raw(self, txn_bytes):
        txn = self._decode(txn_bytes)
        stxn = AccountTransactionSigner(self.private_key).sign_transactions([txn], [0])[0]
        return base64.b64decode(encoding.msgpack_encode(stxn))


# Register dummy ai_economy_sdk in sys.modules for any backward compatibility
ai_economy_sdk_mod = types.ModuleType("ai_economy_sdk")
ai_economy_sdk_mod.DefaultAvmSigner = DefaultAvmSigner
sys.modules["ai_economy_sdk"] = ai_economy_sdk_mod


def get_localnet_algod() -> algod.AlgodClient:
    return algod.AlgodClient(LOCALNET_ALGOD_TOKEN, LOCALNET_ALGOD_URL)


def get_localnet_kmd() -> kmd.KMDClient:
    return kmd.KMDClient(LOCALNET_KMD_TOKEN, LOCALNET_KMD_URL)


def get_dispenser(algod_client: algod.AlgodClient | None = None) -> tuple[str, str]:
    """Retrieve the KMD dispenser address and private key on LocalNet."""
    algod_c = algod_client or get_localnet_algod()
    k = get_localnet_kmd()
    wallets = [w for w in k.list_wallets() if w["name"] == "unencrypted-default-wallet"]
    if not wallets:
        raise RuntimeError("No unencrypted-default-wallet found in KMD")
    h = k.init_wallet_handle(wallets[0]["id"], "")
    keys = k.list_keys(h)
    addr = max(keys, key=lambda a: algod_c.account_info(a)["amount"])
    sk = k.export_key(h, "", addr)
    return addr, sk


def new_funded_account(
    algos: float = 10.0, algod_client: algod.AlgodClient | None = None
) -> tuple[str, str]:
    """Create a new account on LocalNet and fund it from the KMD dispenser."""
    algod_c = algod_client or get_localnet_algod()
    sk, addr = account.generate_account()
    d_addr, d_sk = get_dispenser(algod_c)
    sp = algod_c.suggested_params()
    txn = transaction.PaymentTxn(d_addr, sp, addr, int(algos * 1_000_000))
    stxn = AccountTransactionSigner(d_sk).sign_transactions([txn], [0])[0]
    txid = algod_c.send_transaction(stxn)
    transaction.wait_for_confirmation(algod_c, txid, 4)
    return sk, addr


def get_localnet_network(algod_client: algod.AlgodClient | None = None) -> str:
    algod_c = algod_client or get_localnet_algod()
    sp = algod_c.suggested_params()
    register_network(sp.gh)
    return caip2_from_genesis_hash(sp.gh)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "localnet: mark test as requiring running LocalNet (LOCALNET=1)"
    )
    config.addinivalue_line(
        "markers", "public_nets: mark test as requiring public networks (PUBLIC_NETS=1)"
    )


def pytest_collection_modifyitems(config, items):
    """Filter tests by environment tiers."""
    is_localnet = os.environ.get("LOCALNET") == "1"
    is_public = os.environ.get("PUBLIC_NETS") == "1"

    skip_localnet = pytest.mark.skip(reason="set LOCALNET=1 with algokit localnet running")
    skip_public = pytest.mark.skip(reason="set PUBLIC_NETS=1 to run public network tests")

    for item in items:
        if "localnet" in item.keywords and not is_localnet:
            item.add_marker(skip_localnet)
        if "public_nets" in item.keywords and not is_public:
            item.add_marker(skip_public)
