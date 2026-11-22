# x402-algorand

[![CI](https://github.com/x402-avm/x402-algorand/actions/workflows/ci.yml/badge.svg)](https://github.com/x402-avm/x402-algorand/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/x402-algorand.svg)](https://pypi.org/project/x402-algorand/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Algorand payments for the official x402 Python SDK.**

[x402](https://www.x402.org) is the open standard for charging per HTTP request: the server answers `402 Payment Required` with a price, and the client pays and retries. This package adds Algorand to the official [`x402`](https://github.com/x402-foundation/x402) SDK. Charge for a FastAPI or Flask route in ALGO or USDC, pay for one from `httpx` or `requests`, or run your own facilitator, all with the SDK's own middleware and clients.

It implements the official [exact scheme on Algorand](https://github.com/x402-foundation/x402/blob/main/specs/schemes/exact/scheme_exact_algo.md). Part of [x402-avm](https://github.com/x402-avm/x402-avm). **[Documentation](https://x402-avm.github.io/build/paywall-http-api)**

```bash
pip install x402-algorand
```

## Charge for an API

The server's account receives the payment and also pays the network fee, so the buyer pays exactly the price.

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
        "accepts": [{
            "scheme": "exact",
            "price": {"amount": "10000", "asset": "0"},  # 0.01 ALGO
            "network": network,
            "pay_to": signer.address,
        }]
    }
}
app.middleware("http")(payment_middleware(routes, server))

@app.get("/weather")
async def weather():
    return {"city": "Boston", "temperature": 68}
```

## Pay for one

```python
import os

from x402 import x402Client
from x402.http.clients.httpx import wrapHttpxWithPayment

from x402_algorand import PayerAvmSigner
from x402_algorand.exact import register_exact_avm_client

client = x402Client()
register_exact_avm_client(
    client,
    PayerAvmSigner.from_mnemonic(os.environ["PAYER_MNEMONIC"]),
    algod_url="http://localhost:4001",
    algod_token="a" * 64,
)
async with wrapHttpxWithPayment(client) as http:
    response = await http.get("http://127.0.0.1:8000/weather")
```

The x402 client refuses anything over 1 ALGO or 1 USDC per payment, or in an asset it doesn't know, until you change its spend controls. On MainNet and TestNet, leave out `algod_url` to use public AlgoNode endpoints.

## What you get

- **ALGO, USDC and any Algorand asset**, on MainNet, TestNet, LocalNet or a private network, using [CAIP-2](https://x402-avm.github.io/production/networks) network ids.
- **Ready-made signers** for a key or mnemonic (`PayerAvmSigner`, `ServerAvmSigner`), or your own KMS or wallet behind a small protocol.
- **A strict facilitator.** It checks every rule in the specification and simulates the group before accepting it. It also rejects close-outs and key registrations, and accepts a rekey only when it is undone in the same group. See [the scheme](https://x402-avm.github.io/reference/protocol/avm-exact-scheme).
- **Typed errors** under `X402AlgorandError`. Verification never raises; it returns a reason code. See [errors](https://x402-avm.github.io/reference/errors).

Flask, `requests`, standalone facilitators and custom networks are covered in the [documentation](https://x402-avm.github.io/build/paywall-http-api). To sell MCP tools rather than HTTP routes, use [`ai-economy-sdk`](https://github.com/x402-avm/ai-economy-sdk), which builds on this package. Supports Python 3.10 to 3.14 and `x402` 2.28 or later.

Upgrading from 0.1.x? Import from `x402_algorand` instead of `x402.mechanisms.avm`, and import the core classes from `x402`. 44-character network ids are still accepted.

## Development

```bash
git clone https://github.com/x402-avm/x402-algorand.git && cd x402-algorand
pip install -e ".[dev]"
pytest --cov              # offline tests
LOCALNET=1 pytest         # also against AlgoKit LocalNet (algokit localnet start)
ruff check . && ruff format --check .
```

See [CONTRIBUTING](https://github.com/x402-avm/.github/blob/main/CONTRIBUTING.md). Report security problems privately, following the [security policy](https://github.com/x402-avm/.github/blob/main/SECURITY.md).

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). This package started as a fork of GoPlausible/x402-avm 2.0.2. x402-avm is not affiliated with GoPlausible.
