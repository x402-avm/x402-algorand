# AGENTS.md

Practical guidance for AI coding agents and human contributors working on `x402-algorand`.

## Project Overview

`x402-algorand` is an Algorand Virtual Machine (AVM) exact payment scheme plugin for the official Python `x402` SDK (`x402 >= 2.28, < 3`). It provides:
- Client, server, and facilitator scheme implementations for the `exact` payment scheme.
- Native ALGO payments (`asset: "0"`) and ASA transfers (e.g., USDC).
- Atomic transaction groups with fee pooling and fee payer abstraction.
- CAIP-2 network resolution adhering to the Algorand CAIP-2 profile.
- Built-in `find_default_asset` integration with official `x402Client` spend controls.

## Environment Setup

Create an isolated virtual environment with Python 3.10+ (Python 3.12 recommended):

```bash
uv venv -q --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Running Tests

Tests are structured into three distinct tiers:

```bash
# 1. Offline tests (default, fast, no external network needed), with coverage gate:
pytest --cov --cov-fail-under=99

# 2. LocalNet tests (requires AlgoKit LocalNet running on localhost:4001/4002):
LOCALNET=1 pytest

# 3. Public network simulation tests (read-only simulations against TestNet/MainNet):
PUBLIC_NETS=1 pytest

# Run all test tiers:
LOCALNET=1 PUBLIC_NETS=1 pytest
```

## Code Style and Linting

We enforce linting and formatting standards using `ruff`:

```bash
# Check code style:
ruff check .

# Check formatting:
ruff format --check .

# Auto-fix lint issues:
ruff check --fix .
```

## Repository Structure

```
.
├── .github/
│   ├── dependabot.yml          # Weekly dependency update configuration
│   └── workflows/
│       ├── ci.yml              # Multi-tier GitHub Actions workflow
│       └── release.yml         # PyPI trusted publishing (manual trigger only, disabled)
├── x402_algorand/              # Main package source
│   ├── __init__.py             # Public exports
│   ├── constants.py            # CAIP-2 IDs, ASA IDs, error codes, DEFAULT_ASSETS
│   ├── errors.py               # Exception hierarchy (X402AlgorandError and subclasses)
│   ├── py.typed                # PEP 561 marker
│   ├── signer.py               # Signer protocols + PayerAvmSigner / ServerAvmSigner
│   ├── types.py                # Payload dataclasses and group info types
│   ├── utils.py                # Network normalization, transaction encoding/decoding
│   └── exact/                  # Scheme implementation
│       ├── __init__.py
│       ├── client.py           # ExactAvmScheme (V2 client)
│       ├── facilitator.py      # ExactAvmScheme (V2 facilitator)
│       ├── register.py         # Registration helpers for x402Client, Server, Facilitator
│       ├── server.py           # ExactAvmScheme (V2 server)
│       └── v1/                 # V1 backwards compatibility wrappers
├── tests/                      # Self-contained pytest test suite
│   ├── conftest.py             # DefaultAvmSigner, LocalNet KMD dispenser, tier filters
│   ├── avm_builders.py         # Offline transaction / payload builders for unit tests
│   ├── test_avm_fork.py        # Offline unit tests for AVM exact scheme
│   ├── test_caip2.py           # Offline unit tests for CAIP-2 specification vectors
│   ├── test_facilitator.py     # Table-driven verify/settle tests (every invalid_reason)
│   ├── test_server_v1_register.py # Server scheme, V1 wrappers, register helpers, SDK round trip
│   ├── test_signers.py         # PayerAvmSigner / ServerAvmSigner
│   ├── test_utils_client.py    # Utilities, client scheme, exceptions, __version__
│   ├── test_localnet_algo_payment.py # Live payment verification & settlement on LocalNet
│   ├── test_public_networks.py # Read-only simulate tests on MainNet and TestNet
│   └── test_spend_controls.py  # Spend controls filtering, caps, and ASA whitelisting
├── AGENTS.md                   # This agent guidance document
├── CHANGELOG.md                # Version history (Keep a Changelog format)
├── LICENSE                     # Apache License 2.0
├── NOTICE                      # Upstream copyright notices and modification list
├── README.md                   # Public documentation and quickstart
├── pyproject.toml              # Build metadata, dependencies, and URLs
├── ruff.toml                   # Ruff linter and formatter configuration
├── .editorconfig               # Editor whitespace and encoding rules
└── .gitignore                  # Git ignore rules for Python builds and artifacts
```

## Conventions and Rules

1. **Self-Contained Tests**: Tests must never rely on local machine paths, absolute host directory paths, specific usernames, or hardcoded account credential files. LocalNet tests must create and fund fresh accounts from the LocalNet KMD dispenser.
2. **Network Identifiers**: Use the 32-character canonical CAIP-2 network identifiers:
   - MainNet: `algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k`
   - TestNet: `algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDe`
   - LocalNet: `algorand:tg0cyjEz14FZK9BTpL2q0TOyFbc0McwY` (or derived from algod genesis hash)
   Always pass raw network strings through `normalize_network()` when parsing user input.
3. **Spend Controls**:
   - `find_default_asset` recognizes ALGO (`asset: "0"`) and USDC (`31566704` on MainNet, `10458941` on TestNet) with 6 decimals.
   - Default atomic cap is 1,000,000 units ($1).
   - Other ASAs must be explicitly allowed using `client.set_spend_controls({"allowed_assets": [...]})`.
4. **No Secrets**: Never commit real private keys, mnemonics, or tokens.
5. **Errors**: Raise subclasses of `X402AlgorandError` (see `errors.py`) that also inherit the built-in type callers already catch. Never raise from `verify()`/`settle()` for an invalid payment; return a protocol `ERR_*` code. Log via `logging.getLogger("x402_algorand")`; never log keys or mnemonics.
6. **No deprecated algosdk APIs**: tests run with `DeprecationWarning` as an error. Sign with `AccountTransactionSigner`, not `Transaction.sign()`.
7. **Licensing**: This package is licensed under Apache-2.0. Upstream notices in `LICENSE` and `NOTICE` must remain intact.

## Pull Request Checklist

Before submitting a PR, verify:
- [ ] `ruff check .` reports no errors.
- [ ] `ruff format --check .` reports no errors.
- [ ] `pytest --cov --cov-fail-under=99` passes all offline unit tests.
- [ ] `LOCALNET=1 pytest` passes all live LocalNet tests.
- [ ] `PUBLIC_NETS=1 pytest` passes public network simulations.
- [ ] `python -m build && twine check dist/*` succeeds without packaging errors.
- [ ] `CHANGELOG.md` is updated with your changes.
