# x402-algorand

[![CI](https://github.com/x402-avm/x402-algorand/actions/workflows/ci.yml/badge.svg)](https://github.com/x402-avm/x402-algorand/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/x402-algorand.svg)](https://pypi.org/project/x402-algorand/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Algorand (AVM) exact payment scheme plugin for the official x402 Python SDK.

`x402-algorand` provides Algorand Virtual Machine (AVM) payment scheme support for the official [x402](https://github.com/x402-foundation/x402) payment protocol. It supports native ALGO payments, Algorand Standard Asset (ASA) transfers such as USDC, atomic transaction groups with fee pooling, and integration with `x402Client` spend controls.

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

Register the Algorand exact payment scheme with the official `x402Client`, `x402ResourceServer`, and `x402Facilitator`:

```python
from x402 import x402Client, x402ResourceServer, x402Facilitator
from x402_algorand.exact.register import (
    register_exact_avm_client,
    register_exact_avm_server,
    register_exact_avm_facilitator,
)

# 1. Client setup
client = x402Client()
register_exact_avm_client(client, client_signer)

# 2. Server setup
server = x402ResourceServer(facilitator_client)
register_exact_avm_server(server)

# 3. Facilitator setup
facilitator = x402Facilitator()
register_exact_avm_facilitator(
    facilitator,
    facilitator_signer,
    networks="algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k",
)
```

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
# 1. Offline tests (unit tests, mock tests, CAIP-2 verification)
pytest

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

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
