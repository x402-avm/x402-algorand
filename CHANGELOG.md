# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-11-19

### Added
- Ready-made signers: `PayerAvmSigner` (client side) and `ServerAvmSigner` (facilitator side:
  fee payer signing, simulate, send, confirm; also usable as a client signer). Both can be built
  with `from_private_key(...)` or `from_mnemonic(...)`; `ServerAvmSigner` accepts several keys,
  an `algod_client` or `algod_url`/`algod_token`, and checks that algod is on the requested network.
  Keys are never included in `repr()`, error messages or logs.
- Exception hierarchy in `x402_algorand.errors`, exported from `x402_algorand`:
  `X402AlgorandError`, `NetworkError`, `NetworkMismatchError`, `TransactionDecodeError`,
  `SigningError`, `SimulationError`.
- `x402_algorand.__version__`.
- `py.typed` marker, so type checkers use the package's inline type hints.
- Payments authorized by a k-of-n multisig, a logic signature, or the auth address of a rekeyed
  account are accepted, as allowed by the exact scheme specification.
- Python 3.14 support.

### Changed
- Errors raised for unsupported or unregistered networks are now `NetworkError`, for an algod on
  the wrong network `NetworkMismatchError`, and for undecodable transactions
  `TransactionDecodeError`. All are subclasses of `ValueError`, as before.
- The facilitator checks every transaction sent by one of its own addresses (not only the first),
  and signs all of the advertised `feePayer`'s transactions, as the specification requires.
- Fee payer signing, simulation and settlement failures are also logged to the
  `x402_algorand` logger; the returned `invalid_reason` / `error_reason` codes are unchanged.
- Package metadata: authors are "x402-avm contributors"; added a `Repository` URL; `pynacl` is
  a declared dependency (it was already required through `py-algorand-sdk`).

### Fixed
- `settle()` returns the ID of `paymentGroup[paymentIndex]` as the transaction, as required by the
  specification. With a fee payer it previously returned the ID of the fee payer transaction.
- The V1 facilitator and client wrappers now accept the official SDK's `PaymentPayloadV1` /
  `PaymentRequirementsV1` models and return `VerifyResponse` / `SettleResponse`, so V1 payments
  routed through `x402Facilitator` / `x402Client` work. Requirements without `extra` no longer fail
  validation. Plain dict input still returns the V1 dict responses.
- Ed25519 signature verification of a payment from a rekeyed account uses the auth address.
- A rekey pair is only accepted when the second rekey returns authority to the sender.

## [0.2.1] - 2026-11-19

### Added
- Project URLs (`Homepage`, `Documentation`, `Issues`, `Changelog`) and classifiers (Python 3.10–3.13, `Typing :: Typed`, `Development Status :: 4 - Beta`) in `pyproject.toml`.
- `dev` optional dependencies extra in `pyproject.toml` (`pytest`, `pytest-asyncio`, `ruff`, `build`, `twine`, `httpx`).
- Public network simulation tests in `tests/test_public_networks.py` covering ALGO and USDC on TestNet and MainNet (`PUBLIC_NETS=1`).
- Public documentation and agent guidance: comprehensive `README.md` and `AGENTS.md`.
- Tooling and CI configurations: `ruff.toml`, `.gitignore`, `.editorconfig`, `.github/workflows/ci.yml`, and `.github/dependabot.yml` with ecosystem update groups.

### Changed
- Made LocalNet tests (`tests/test_localnet_algo_payment.py`, `tests/test_spend_controls.py`, `tests/conftest.py`) self-contained by generating and funding ephemeral test accounts directly from the LocalNet KMD dispenser.
- Applied code formatting with `ruff` across package and tests with no behavior changes.

## [0.2.0] - 2026-11-18
### Changed
- x402-algorand is now a plugin for the official `x402` Python SDK (`x402>=2.28,<3`, github.com/x402-foundation/x402). It ships only the
  Algorand exact scheme, under the import name `x402_algorand` (was `x402.mechanisms.avm` inside a fork of the whole SDK).
- Network ids follow the Algorand CAIP-2 profile: `algorand:` + the first 32 characters of the URL-safe base64 genesis hash
  (MainNet `algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k`, TestNet `algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDe`). Legacy long ids are accepted and converted.
- The facilitator checks the network by the id derived from each transaction's genesis hash, so LocalNet and private networks need no registry entry.
### Added
- `caip2_from_genesis_hash`, `register_network`, `get_genesis_hash` helpers.
- The client scheme implements `find_default_asset`, so the official `x402Client` spend controls pay ALGO and USDC by default
  (capped at 1,000,000 base units per payment); other assets are allowed with `x402Client.set_spend_controls(...)`.
- The client refuses to build a payment when its algod is on a different network than the requirement.
### Removed
- The bundled copy of the x402 core SDK (`x402/`); install the official `x402` package instead.

## [0.1.4] - 2026-11-18
### Changed
- Licensed Apache-2.0 like the projects it derives from (GoPlausible/x402-avm, coinbase/x402); ships LICENSE and NOTICE, and each file
  changed from x402-avm 2.0.2 says so. Releases 0.1.0-0.1.3 were labelled MIT by mistake.

## [0.1.3] - 2026-11-18
### Changed
- Package metadata update (readme as PyPI description). Network ids were still the long form `algorand:<full genesis hash>`.

## [0.1.0] - [0.1.2]
- Fork of GoPlausible/x402-avm 2.0.2 (Python, the whole x402 SDK): native ALGO payments (asset 0), algod token parameter,
  any `algorand:<genesis hash>` network (LocalNet / private), facilitator fixes for sync facilitators and streaming (SSE) responses.
