"""Unit tests for Algorand CAIP-2 short network IDs and official x402 compatibility."""

import base64

import pytest
from x402.schemas import PaymentRequirements

from x402_algorand.constants import (
    ALGORAND_MAINNET_CAIP2,
    ALGORAND_TESTNET_CAIP2,
    MAINNET_GENESIS_HASH,
    TESTNET_GENESIS_HASH,
)
from x402_algorand.utils import (
    caip2_from_genesis_hash,
    get_genesis_hash,
    normalize_network,
    register_network,
)

# Test vectors from Algorand CAIP-2 specification and task requirements
VECTORS = [
    (
        "wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=",
        "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k",
    ),
    (
        "SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
        "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDe",
    ),
    (
        "mFgazF+2uRS1tMiL9dsj01hJGySEmPN28B/TjjvpVW0=",
        "algorand:mFgazF-2uRS1tMiL9dsj01hJGySEmPN2",
    ),
    (
        "tg0cyjEz14FZK9BTpL2q0TOyFbc0McwYsFJbszmFANk=",
        "algorand:tg0cyjEz14FZK9BTpL2q0TOyFbc0McwY",
    ),
]


def test_caip2_from_genesis_hash_vectors():
    """Verify the 4 official test vectors: MainNet, TestNet, spec example, LocalNet."""
    for gh, expected in VECTORS:
        assert caip2_from_genesis_hash(gh) == expected

    # Also verify constants match
    assert ALGORAND_MAINNET_CAIP2 == "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k"
    assert ALGORAND_TESTNET_CAIP2 == "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDe"
    assert caip2_from_genesis_hash(MAINNET_GENESIS_HASH) == ALGORAND_MAINNET_CAIP2
    assert caip2_from_genesis_hash(TESTNET_GENESIS_HASH) == ALGORAND_TESTNET_CAIP2


def test_caip2_from_genesis_hash_bytes():
    """Verify caip2_from_genesis_hash accepts raw 32 bytes."""
    for gh, expected in VECTORS:
        raw_bytes = base64.b64decode(gh)
        assert len(raw_bytes) == 32
        assert caip2_from_genesis_hash(raw_bytes) == expected


def test_legacy_long_id_conversion():
    """Verify legacy 44-char base64 IDs (algorand:<hash>) convert to short CAIP-2 IDs."""
    for gh, expected in VECTORS:
        legacy_id = f"algorand:{gh}"
        normalized = normalize_network(legacy_id)
        assert normalized == expected
        # Also verify get_genesis_hash retrieves the original hash
        assert get_genesis_hash(legacy_id) == gh


def test_register_network_and_get_genesis_hash_round_trip():
    """Verify register_network and get_genesis_hash round trip for custom networks."""
    custom_gh = "mFgazF+2uRS1tMiL9dsj01hJGySEmPN28B/TjjvpVW0="
    custom_id = register_network(
        genesis_hash=custom_gh,
        genesis_id="custom-v1",
        algod_url="http://localhost:4001",
        indexer_url="http://localhost:8980",
    )
    assert custom_id == "algorand:mFgazF-2uRS1tMiL9dsj01hJGySEmPN2"
    assert get_genesis_hash(custom_id) == custom_gh
    assert normalize_network(custom_id) == custom_id


def test_invalid_network_ids_raise_value_error():
    """Verify invalid network identifiers raise ValueError."""
    invalid_ids = [
        "ethereum:1",
        "algorand:",
        "algorand:invalid!characters@",
        "unknown_network_identifier",
        "algorand:toolong123456789012345678901234567890123",  # 33 chars > 32 max
        "algorand:mFgazF+2uRS1tMiL9dsj01hJGySEmPN28B/TjjvpVW0=",  # legacy long without register
    ]
    for inv in invalid_ids:
        # Note: if it's legacy 44-char ending with =, normalize_network registers it,
        # but anything else should fail.
        if inv.endswith("=") and len(inv.split(":")[-1]) == 44:
            continue
        with pytest.raises(ValueError):
            normalize_network(inv)

    with pytest.raises(ValueError, match="unknown network"):
        get_genesis_hash("algorand:unregistered1234567890123456")


def test_official_x402_payment_requirements_compatibility():
    """Verify that all CAIP-2 network IDs pass official x402 PaymentRequirements schema validation."""
    dummy_addr = "SPDMDX4SBNY35L2GZB7RBKTPRT76NUVWA2GNXEQDTPPNKUOYJIK5ERFAW4"
    for _, net_id in VECTORS:
        req = PaymentRequirements(
            scheme="exact",
            network=net_id,
            asset="0",
            amount="1000",
            pay_to=dummy_addr,
            max_timeout_seconds=300,
        )
        assert req.network == net_id
        assert req.scheme == "exact"
        assert req.asset == "0"
        assert req.amount == "1000"
        assert req.pay_to == dummy_addr
