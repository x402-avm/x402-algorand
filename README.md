# x402-algorand

[![CI](https://github.com/x402-avm/x402-algorand/actions/workflows/ci.yml/badge.svg)](https://github.com/x402-avm/x402-algorand/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/x402-algorand.svg)](https://pypi.org/project/x402-algorand/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Algorand (AVM) exact payment scheme plugin for the official x402 Python SDK.

This project is not affiliated with GoPlausible's `x402-avm` packages. It started as a fork of GoPlausible/x402-avm 2.0.2 (see [NOTICE](NOTICE)).

`x402-algorand` provides Algorand Virtual Machine (AVM) payment scheme support for the official [x402](https://github.com/x402-foundation/x402) payment protocol, implementing the [exact scheme on Algorand](https://github.com/x402-foundation/x402/blob/main/specs/schemes/exact/scheme_exact_algo.md) specification. It supports Algorand Standard Asset (ASA) transfers such as USDC, native ALGO payments, atomic transaction groups with fee pooling, and integration with `x402Client` spend controls.

## Requirements

- Python 3.10+
- `x402` >= 2.28, < 3.0
- `py-algorand-sdk` >= 2.6

## Installation

```bash
pip install x402-algorand
```

Installing `x402-algorand` automatically pulls the official `x402` package.

## Quickstart

Register the Algorand exact scheme with the official `x402Client`, `x402ResourceServer`
and `x402Facilitator`. `PayerAvmSigner` and `ServerAvmSigner` are ready-made signers
backed by an Algorand private key or 25-word mnemonic.

### Paid API (FastAPI, in-process facilitator, AlgoKit LocalNet)

The server's account is both the payee and the fee payer, so the buyer pays exactly the price
with no network fee.

```python
import os

from algosdk.v2client.algod import AlgodClient
from fastapi import FastAPI
from x402 import x402Facilitator, x402ResourceServer
from x402.http.middleware.fastapi import payment_middleware

from x402_algorand import ServerAvmSigner, caip2_from_genesis_hash
from x402_algorand.exact import register_exact_avm_facilitator, register_exact_avm_server

algod = AlgodClient("a" * 64, "http://localhost:4001")  # AlgoKit LocalNet
network = caip2_from_genesis_hash(algod.suggested_params().gh)
signer = ServerAvmSigner.from_mnemonic(os.environ["SERVER_MNEMONIC"], algod)

facilitator = x402Facilitator()
register_exact_avm_facilitator(facilitator, signer, network)
server = x402ResourceServer(facilitator)
register_exact_avm_server(server)

app = FastAPI()
routes = {
    "GET /weather": {
        "accepts": [
            {
                "scheme": "exact",
                "price": {"amount": "10000", "asset": "0"},  # 0.01 ALGO
                "network": network,
                "pay_to": signer.address,
            }
        ]
    }
}
app.middleware("http")(payment_middleware(routes, server))


@app.get("/weather")
async def weather():
    return {"city": "Boston", "temperature": 68}
```

### Paying client (httpx)

```python
import asyncio
import os

from x402 import x402Client
from x402.http.clients.httpx import wrapHttpxWithPayment

from x402_algorand import PayerAvmSigner
from x402_algorand.exact import register_exact_avm_client


async def main() -> None:
    client = x402Client()
    register_exact_avm_client(
        client,
        PayerAvmSigner.from_mnemonic(os.environ["PAYER_MNEMONIC"]),
        algod_url="http://localhost:4001",
        algod_token="a" * 64,
    )
    async with wrapHttpxWithPayment(client) as http:
        response = await http.get("http://127.0.0.1:8000/weather")
        print(response.status_code, response.json())


asyncio.run(main())
```

On MainNet and TestNet, omit `algod_url` / the `AlgodClient` argument to use the public
AlgoNode endpoints configured in `NETWORK_CONFIGS` (overridable with the `ALGOD_MAINNET_URL`
and `ALGOD_TESTNET_URL` environment variables), and use the network constants
`ALGORAND_MAINNET_CAIP2` / `ALGORAND_TESTNET_CAIP2`.

## Signers

| Class | Role | Constructors |
|---|---|---|
| `PayerAvmSigner` | `ClientAvmSigner`: signs the buyer's payment transaction | `from_private_key(key)`, `from_mnemonic(words)` |
| `ServerAvmSigner` | `FacilitatorAvmSigner`: signs fee payer transactions, simulates, sends and confirms groups. Also implements `ClientAvmSigner`. | `from_private_key(key, algod_client=None, *, algod_url=None, algod_token=None)`, `from_mnemonic(...)`, or `ServerAvmSigner([key1, key2], ...)` for several fee payers |

- Keys are kept in private attributes and are not included in `repr()`, exception messages or logs.
- `ServerAvmSigner` with an algod client checks, on first use for a network, that the node's
  genesis hash matches that network and raises `NetworkMismatchError` otherwise. Without one, it
  uses the algod URL configured for the network.
- To use a KMS, HSM or wallet instead, implement the `ClientAvmSigner` / `FacilitatorAvmSigner`
  protocols from `x402_algorand.signer`.

## Errors

Exceptions raised by the package derive from `X402AlgorandError`. Each also derives from the
built-in type raised before 0.3.0, so existing `except ValueError` handlers keep working.

| Exception | Also a | Raised when |
|---|---|---|
| `NetworkError` | `ValueError` | A network id is malformed, unsupported, or not registered |
| `NetworkMismatchError` | `NetworkError` | algod is connected to a different network than requested |
| `TransactionDecodeError` | `ValueError` | Bytes or base64 are not a decodable Algorand transaction |
| `SigningError` | `ValueError` | Bad key or mnemonic, or an address the signer does not manage |
| `SimulationError` | `RuntimeError` | algod `simulate` reports that the group would fail |

Payment verification never raises for an invalid payment: `verify()` and `settle()` return a
`VerifyResponse` / `SettleResponse` with a protocol `invalid_reason` / `error_reason` code (see
`x402_algorand.constants`, `ERR_*`). The package logs to the `x402_algorand` logger.

## Specification conformance

The facilitator follows the verification steps of the
[exact scheme on Algorand](https://github.com/x402-foundation/x402/blob/main/specs/schemes/exact/scheme_exact_algo.md):

- `paymentGroup` has at most 16 transactions; all decode; all share one group id and the genesis hash of the requested network.
- `paymentGroup[paymentIndex]` pays exactly `amount` of `asset` to `payTo`, and is authorized by an ed25519 signature (of the sender or its auth address), a k-of-n multisig, or a logic signature.
- Every transaction sent by a facilitator address is a zero-amount `pay` to itself with no `close`/`rekey` and a fee of at most 16,000 microAlgos; the advertised `feePayer`'s transactions are signed only after these checks.
- The group is simulated before it is accepted, and settlement returns the ID of `paymentGroup[paymentIndex]`.

Additional checks in this package: close-to fields and `keyreg` transactions are rejected in any
transaction, and rekeys are only accepted as a balanced pair that returns authority to the sender.

`asset: "0"` (native ALGO via a `pay` transaction) is an extension of this package; the
specification defines ASA transfers only.

## Network Identifiers (CAIP-2)

In accordance with the Algorand CAIP-2 profile, network references use the first 32 characters of the URL-safe base64 encoding of the 32-byte genesis hash:

| Network | Genesis Hash (full base64) | CAIP-2 Identifier |
|---|---|---|
| MainNet | `wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=` | `algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k` |
| TestNet | `SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=` | `algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDe` |
| CAIP-2 spec example | `mFgazF+2uRS1tMiL9dsj01hJGySEmPN28B/TjjvpVW0=` | `algorand:mFgazF-2uRS1tMiL9dsj01hJGySEmPN2` |
| LocalNet (default) | `tg0cyjEz14FZK9BTpL2q0TOyFbc0McwYsFJbszmFANk=` | `algorand:tg0cyjEz14FZK9BTpL2q0TOyFbc0McwY` |

Custom networks can be registered dynamically via `register_network(genesis_hash)`.

## Spend Controls

The official `x402Client` applies spend controls by default to prevent unintentional or excessive payments. `ExactAvmScheme` integrates directly with these controls via `find_default_asset`.

### Default Allowances and Limits

By default, without custom configuration:
- **Allowed Assets**:
  - **ALGO** (`asset: "0"`): Allowed on all valid Algorand networks (MainNet, TestNet, LocalNet, custom).
  - **USDC**: Allowed on MainNet (`asset: "31566704"`) and TestNet (`asset: "10458941"`).
- **Default Cap**:
  - Payments are capped at `$1` (`DEFAULT_MAX_AMOUNT_PER_PAYMENT`), corresponding to **1,000,000 base atomic units** (6 decimals):
    - **1 ALGO** (1,000,000 microAlgos)
    - **1 USDC** (1,000,000 atomic units)
- Any payment requesting an unknown asset or an amount exceeding 1,000,000 base units is rejected with `NoMatchingRequirementsError`.

### Allowing Other ASAs and Custom Caps

You can whitelist additional ASAs, adjust per-asset caps, raise global USD caps, or disable spend controls using `client.set_spend_controls(...)` or `x402Client.from_config(...)`:

```python
# 1. Allow a custom ASA with an atomic spending cap:
client.set_spend_controls(
    {
        "allowed_assets": [
            {
                "network": "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k",
                "asset": "12345678",  # ASA ID
                "max_amount_per_payment": "5000000",  # Base atomic units
            }
        ]
    }
)

# 2. Raise the default USD cap for recognized assets (e.g. up to $10 per payment):
client.set_spend_controls({"max_amount_per_payment": "$10"})

# 3. Allow any asset without asset-filtering restrictions:
client.set_spend_controls({"allowed_assets": True})

# 4. Disable all spend controls entirely:
client.set_spend_controls(False)
```

## Migration from 0.1.x

In version 0.1.x, `x402-algorand` replaced the entire `x402` package and used `from x402.mechanisms.avm...`.
In version 0.2.0:
- Use `from x402_algorand import ...` instead of `from x402.mechanisms.avm import ...`.
- Core x402 classes (`x402Client`, `x402ResourceServer`, `x402Facilitator`) are imported directly from `x402`.
- Network identifiers follow the 32-character CAIP-2 profile. Legacy 44-character IDs (`algorand:<hash>=`) remain accepted and are automatically converted.

## Related Packages and Links

- Documentation: [https://x402-avm.github.io](https://x402-avm.github.io)
- Examples Repository: [https://github.com/x402-avm/examples](https://github.com/x402-avm/examples)
- Python High-Level SDK: [ai-economy-sdk](https://github.com/x402-avm/ai-economy-sdk)
- TypeScript Browser / Node Client: [x402-avm-js](https://github.com/x402-avm/x402-avm-js)
- Official x402 Specification: [x402 Foundation](https://github.com/x402-foundation/x402)

## Development

Install the package in editable mode with development dependencies:

```bash
pip install -e ".[dev]"
```

Run test tiers:

```bash
# 1. Offline tests (unit tests, mock tests, CAIP-2 verification), with coverage
pytest --cov

# 2. LocalNet tests (requires running AlgoKit LocalNet: algokit localnet start)
LOCALNET=1 pytest

# 3. Public network simulations (read-only simulations on MainNet and TestNet)
PUBLIC_NETS=1 pytest
```

Linting and formatting:

```bash
ruff check .
ruff format --check .
```

Build distribution packages:

```bash
python -m build
twine check dist/*
```

Releases are published to PyPI by the maintainers. `.github/workflows/release.yml` is prepared
for PyPI trusted publishing and only runs when started manually.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
