"""Exceptions raised by x402-algorand.

Every exception the package raises on purpose derives from :class:`X402AlgorandError`.
Each concrete class also derives from the built-in exception the package raised before
0.3.0 (``ValueError`` or ``RuntimeError``), so existing ``except ValueError:`` handlers
keep working.

These exceptions describe programming, configuration and transport problems. They are
not used for payment verification results: ``verify()`` and ``settle()`` never raise for
an invalid payment, they return a ``VerifyResponse`` / ``SettleResponse`` whose
``invalid_reason`` / ``error_reason`` holds one of the protocol error codes in
:mod:`x402_algorand.constants`.
"""

from __future__ import annotations

__all__ = [
    "X402AlgorandError",
    "NetworkError",
    "NetworkMismatchError",
    "TransactionDecodeError",
    "SigningError",
    "SimulationError",
]


class X402AlgorandError(Exception):
    """Base class for all exceptions raised by x402-algorand."""


class NetworkError(X402AlgorandError, ValueError):
    """A network identifier is malformed, unsupported, or not registered."""


class NetworkMismatchError(NetworkError):
    """An algod node is connected to a different network than the one requested."""


class TransactionDecodeError(X402AlgorandError, ValueError):
    """Bytes or base64 text could not be decoded as an Algorand transaction."""


class SigningError(X402AlgorandError, ValueError):
    """A signer could not sign: bad key material or an address it does not manage."""


class SimulationError(X402AlgorandError, RuntimeError):
    """An algod ``simulate`` call reported that the transaction group would fail."""
