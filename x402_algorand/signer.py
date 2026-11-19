# Copyright 2024 Coinbase; 2026 x402 Foundation; GoPlausible (x402-avm). Licensed under the Apache License 2.0.
# Modified in 2026 by x402-avm contributors for x402-algorand.
# Changes are listed in the NOTICE file.
"""AVM signers.

Protocols (implement these to plug in your own key management, e.g. a KMS or wallet):

- ClientAvmSigner: used by x402Client for creating payment payloads.
- FacilitatorAvmSigner: used by x402Facilitator for verification/settlement.

Ready-made implementations backed by in-memory Algorand private keys:

- PayerAvmSigner: implements ClientAvmSigner (the paying side).
- ServerAvmSigner: implements FacilitatorAvmSigner (fee payer, simulate, send,
  confirm) and also ClientAvmSigner.

Private keys are held in private attributes and never appear in ``repr()``,
exception messages, or log records.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from algosdk import encoding, mnemonic, transaction
from algosdk import error as algosdk_error
from algosdk.atomic_transaction_composer import AccountTransactionSigner
from algosdk.v2client import algod
from algosdk.v2client.models import SimulateRequest, SimulateRequestTransactionGroup
from nacl.signing import SigningKey

from x402_algorand.constants import NETWORK_CONFIGS
from x402_algorand.errors import (
    NetworkError,
    NetworkMismatchError,
    SigningError,
    SimulationError,
)
from x402_algorand.utils import caip2_from_genesis_hash, normalize_network


class ClientAvmSigner(Protocol):
    """Protocol for AVM client-side signing operations.

    Used by x402Client to sign transactions for payment payloads.

    The client signer is responsible for:
    - Providing the sender address
    - Signing transactions where the client is the sender
    """

    @property
    def address(self) -> str:
        """Get the signer's Algorand address.

        Returns:
            58-character Algorand address.
        """
        ...

    def sign_transactions(
        self,
        unsigned_txns: list[bytes],
        indexes_to_sign: list[int],
    ) -> list[bytes | None]:
        """Sign specified transactions in a group.

        Only signs transactions at the specified indexes.
        Returns None for transactions that should not be signed by this signer.

        Args:
            unsigned_txns: List of unsigned transaction bytes (msgpack encoded).
            indexes_to_sign: Indexes of transactions this signer should sign.

        Returns:
            List parallel to unsigned_txns, with signed transaction bytes
            at indexes_to_sign and None elsewhere.
        """
        ...


class FacilitatorAvmSigner(Protocol):
    """Protocol for AVM facilitator-side signing operations.

    Used by x402Facilitator to verify, sign, simulate, and settle transactions.

    The facilitator signer is responsible for:
    - Providing the fee payer addresses it manages
    - Signing fee payer transactions
    - Simulating transaction groups
    - Sending transaction groups to the network
    - Confirming transaction finality
    """

    def get_addresses(self) -> list[str]:
        """Get all managed fee payer addresses.

        Returns:
            List of 58-character Algorand addresses that can be used
            as fee payers. Enables load distribution across multiple signers.
        """
        ...

    def sign_transaction(
        self,
        txn_bytes: bytes,
        fee_payer: str,
        network: str,
    ) -> bytes:
        """Sign a single transaction with the fee payer's key.

        Args:
            txn_bytes: Unsigned transaction bytes (msgpack encoded).
            fee_payer: Algorand address of the fee payer.
            network: CAIP-2 network identifier.

        Returns:
            Signed transaction bytes (msgpack encoded).

        Raises:
            ValueError: If fee_payer is not managed by this signer.
        """
        ...

    def sign_group(
        self,
        group_bytes: list[bytes],
        fee_payer: str,
        indexes_to_sign: list[int],
        network: str,
    ) -> list[bytes]:
        """Sign specified transactions in a group with the fee payer's key.

        Args:
            group_bytes: List of transaction bytes (some signed, some unsigned).
            fee_payer: Algorand address of the fee payer.
            indexes_to_sign: Indexes of transactions the fee payer should sign.
            network: CAIP-2 network identifier.

        Returns:
            List of transaction bytes with fee payer's transactions now signed.

        Raises:
            ValueError: If fee_payer is not managed by this signer.
        """
        ...

    def simulate_group(
        self,
        group_bytes: list[bytes],
        network: str,
    ) -> None:
        """Simulate a transaction group to verify it will succeed.

        Uses Algorand's simulate endpoint to dry-run the transaction group
        without committing it to the network.

        Args:
            group_bytes: List of signed/unsigned transaction bytes.
            network: CAIP-2 network identifier.

        Raises:
            Exception: If simulation fails (contains error message).
        """
        ...

    def send_group(
        self,
        group_bytes: list[bytes],
        network: str,
    ) -> str:
        """Send a transaction group to the network.

        Args:
            group_bytes: List of fully-signed transaction bytes.
            network: CAIP-2 network identifier.

        Returns:
            Transaction ID of the first transaction in the group.

        Raises:
            Exception: If sending fails.
        """
        ...

    def confirm_transaction(
        self,
        txid: str,
        network: str,
        rounds: int = 4,
    ) -> None:
        """Wait for transaction confirmation.

        Algorand has instant finality - once a transaction is in a block,
        it is final and will never be reverted.

        Args:
            txid: Transaction ID to confirm.
            network: CAIP-2 network identifier.
            rounds: Maximum rounds to wait (default 4).

        Raises:
            Exception: If confirmation times out or transaction fails.
        """
        ...


# ============================================================================
# Ready-made signers
# ============================================================================


def _address_for_private_key(private_key: str) -> str:
    """Validate a base64 64-byte Algorand private key and return its address."""
    if not isinstance(private_key, str):
        raise SigningError("private key must be a base64 string")
    try:
        raw = base64.b64decode(private_key, validate=True)
    except (binascii.Error, ValueError):
        raise SigningError("private key is not valid base64") from None
    if len(raw) != 64:
        raise SigningError("private key must decode to 64 bytes (seed + public key)")
    if bytes(SigningKey(raw[:32]).verify_key) != raw[32:]:
        raise SigningError("private key seed does not match its public key")
    return encoding.encode_address(raw[32:])


def _private_key_from_mnemonic(words: str) -> str:
    if not isinstance(words, str):
        raise SigningError("mnemonic must be a string")
    try:
        return mnemonic.to_private_key(words)
    except (
        algosdk_error.WrongChecksumError,
        algosdk_error.WrongMnemonicLengthError,
        KeyError,
        ValueError,
    ):
        # Never include the mnemonic (or parts of it) in the message.
        raise SigningError("invalid 25-word Algorand mnemonic") from None


def _decode(raw_bytes: bytes) -> Any:
    return encoding.msgpack_decode(base64.b64encode(raw_bytes).decode())


def _encode(obj: Any) -> bytes:
    return base64.b64decode(encoding.msgpack_encode(obj))


class _KeyRing:
    """Address -> private key store shared by the ready-made signers."""

    def __init__(self, private_keys: Iterable[str]):
        self._keys: dict[str, str] = {}
        for private_key in private_keys:
            self._keys[_address_for_private_key(private_key)] = private_key
        if not self._keys:
            raise SigningError("at least one private key is required")

    @property
    def addresses(self) -> list[str]:
        return list(self._keys)

    def sign(self, txn_bytes: bytes, address: str) -> bytes:
        """Sign unsigned msgpack ``txn_bytes`` with the key of ``address``."""
        private_key = self._keys.get(address)
        if private_key is None:
            raise SigningError(f"address {address} is not managed by this signer")
        try:
            txn = _decode(txn_bytes)
        except Exception as e:  # malformed bytes from the caller
            raise SigningError(f"cannot decode transaction to sign: {e}") from e
        if not isinstance(txn, transaction.Transaction):
            raise SigningError(f"expected an unsigned transaction, got {type(txn).__name__}")
        signed = AccountTransactionSigner(private_key).sign_transactions([txn], [0])[0]
        return _encode(signed)

    def sign_by_sender(
        self, unsigned_txns: list[bytes], indexes_to_sign: list[int]
    ) -> list[bytes | None]:
        wanted = set(indexes_to_sign)
        result: list[bytes | None] = []
        for i, txn_bytes in enumerate(unsigned_txns):
            if i not in wanted:
                result.append(None)
                continue
            txn = _decode(txn_bytes)
            if not isinstance(txn, transaction.Transaction):
                raise SigningError(f"transaction {i} is not an unsigned transaction")
            result.append(self.sign(txn_bytes, txn.sender))
        return result


class PayerAvmSigner:
    """Client-side signer (``ClientAvmSigner``) for a single Algorand account.

    Example:
        ```python
        signer = PayerAvmSigner.from_mnemonic(os.environ["PAYER_MNEMONIC"])
        register_exact_avm_client(client, signer)
        ```
    """

    def __init__(self, private_key: str):
        """Create a signer from a base64 64-byte Algorand private key.

        Raises:
            SigningError: If the key is malformed.
        """
        self._keyring = _KeyRing([private_key])
        self._address = self._keyring.addresses[0]

    @classmethod
    def from_private_key(cls, private_key: str) -> PayerAvmSigner:
        """Create a signer from a base64 private key (as returned by ``algosdk``)."""
        return cls(private_key)

    @classmethod
    def from_mnemonic(cls, mnemonic_phrase: str) -> PayerAvmSigner:
        """Create a signer from a 25-word Algorand mnemonic."""
        return cls(_private_key_from_mnemonic(mnemonic_phrase))

    @property
    def address(self) -> str:
        """The account address (58 characters)."""
        return self._address

    def sign_transactions(
        self,
        unsigned_txns: list[bytes],
        indexes_to_sign: list[int],
    ) -> list[bytes | None]:
        """Sign the transactions at ``indexes_to_sign``; ``None`` elsewhere.

        Raises:
            SigningError: If a transaction to sign is not sent by this account.
        """
        return self._keyring.sign_by_sender(unsigned_txns, indexes_to_sign)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(address={self._address!r})"


class ServerAvmSigner:
    """Facilitator-side signer (``FacilitatorAvmSigner``) backed by private keys and algod.

    Signs fee payer transactions, simulates groups, sends them, and waits for
    confirmation. It also implements ``ClientAvmSigner`` (``address`` /
    ``sign_transactions``), so one object can serve both roles in tests and demos.

    algod selection:

    - ``algod_client`` (or ``algod_url``/``algod_token``) given: that node is used for
      every call. The first call for a network checks that the node's genesis hash
      matches it and raises ``NetworkMismatchError`` otherwise.
    - nothing given: the algod URL configured for the network in ``NETWORK_CONFIGS``
      (MainNet / TestNet defaults, or a network added with ``register_network``).

    Example:
        ```python
        signer = ServerAvmSigner.from_mnemonic(
            os.environ["FACILITATOR_MNEMONIC"],
            algod_url="http://localhost:4001",
            algod_token="a" * 64,
        )
        register_exact_avm_facilitator(facilitator, signer, network)
        ```
    """

    def __init__(
        self,
        private_keys: str | Sequence[str],
        algod_client: algod.AlgodClient | None = None,
        *,
        algod_url: str | None = None,
        algod_token: str | None = None,
    ):
        """Create a signer.

        Args:
            private_keys: One base64 private key, or several (fee payers are then
                chosen at random per request by the facilitator).
            algod_client: algod client to use for all networks.
            algod_url: Build an algod client for this URL (ignored if ``algod_client``).
            algod_token: Token for ``algod_url`` (default ``""``).

        Raises:
            SigningError: If any key is malformed.
        """
        if isinstance(private_keys, str) or not isinstance(private_keys, Iterable):
            keys = [private_keys]
        else:
            keys = list(private_keys)
        self._keyring = _KeyRing(keys)
        if algod_client is None and algod_url is not None:
            algod_client = algod.AlgodClient(algod_token or "", algod_url)
        self._algod = algod_client
        self._clients: dict[str, algod.AlgodClient] = {}

    @classmethod
    def from_private_key(
        cls,
        private_key: str,
        algod_client: algod.AlgodClient | None = None,
        *,
        algod_url: str | None = None,
        algod_token: str | None = None,
    ) -> ServerAvmSigner:
        """Create a signer from one base64 private key."""
        return cls(private_key, algod_client, algod_url=algod_url, algod_token=algod_token)

    @classmethod
    def from_mnemonic(
        cls,
        mnemonic_phrase: str,
        algod_client: algod.AlgodClient | None = None,
        *,
        algod_url: str | None = None,
        algod_token: str | None = None,
    ) -> ServerAvmSigner:
        """Create a signer from a 25-word Algorand mnemonic."""
        return cls(
            _private_key_from_mnemonic(mnemonic_phrase),
            algod_client,
            algod_url=algod_url,
            algod_token=algod_token,
        )

    # -- ClientAvmSigner ---------------------------------------------------

    @property
    def address(self) -> str:
        """The first managed address (handy as ``pay_to``)."""
        return self._keyring.addresses[0]

    def sign_transactions(
        self,
        unsigned_txns: list[bytes],
        indexes_to_sign: list[int],
    ) -> list[bytes | None]:
        """Sign the transactions at ``indexes_to_sign`` with the key of each sender."""
        return self._keyring.sign_by_sender(unsigned_txns, indexes_to_sign)

    # -- FacilitatorAvmSigner ----------------------------------------------

    def get_addresses(self) -> list[str]:
        """All managed fee payer addresses."""
        return self._keyring.addresses

    def sign_transaction(self, txn_bytes: bytes, fee_payer: str, network: str) -> bytes:
        """Sign one unsigned transaction with ``fee_payer``'s key.

        Raises:
            SigningError: If ``fee_payer`` is not managed by this signer.
        """
        _ = network
        return self._keyring.sign(txn_bytes, fee_payer)

    def sign_group(
        self,
        group_bytes: list[bytes],
        fee_payer: str,
        indexes_to_sign: list[int],
        network: str,
    ) -> list[bytes]:
        """Sign the transactions at ``indexes_to_sign`` with ``fee_payer``'s key.

        Raises:
            SigningError: If ``fee_payer`` is not managed by this signer.
        """
        _ = network
        signed = list(group_bytes)
        for i in indexes_to_sign:
            signed[i] = self._keyring.sign(group_bytes[i], fee_payer)
        return signed

    def simulate_group(self, group_bytes: list[bytes], network: str) -> None:
        """Simulate the group with algod (unsigned transactions allowed).

        Raises:
            SimulationError: If algod reports the group would fail.
            NetworkMismatchError: If algod is on a different network.
        """
        client = self.algod_for(network)
        txns = [self._as_signed(_decode(b)) for b in group_bytes]
        request = SimulateRequest(
            txn_groups=[SimulateRequestTransactionGroup(txns=txns)],
            allow_empty_signatures=True,
        )
        result = client.simulate_transactions(request)
        groups = result.get("txn-groups", []) if isinstance(result, dict) else []
        if groups and groups[0].get("failure-message"):
            raise SimulationError(groups[0]["failure-message"])

    def send_group(self, group_bytes: list[bytes], network: str) -> str:
        """Submit a fully signed group; returns the ID of its first transaction."""
        client = self.algod_for(network)
        return client.send_transactions([_decode(b) for b in group_bytes])

    def confirm_transaction(self, txid: str, network: str, rounds: int = 4) -> None:
        """Wait up to ``rounds`` rounds for ``txid`` to be in a block.

        Raises:
            algosdk.error.ConfirmationTimeoutError: If not confirmed in time.
            algosdk.error.TransactionRejectedError: If the pool rejected it.
        """
        transaction.wait_for_confirmation(self.algod_for(network), txid, rounds)

    # -- helpers -------------------------------------------------------------

    def algod_for(self, network: str) -> algod.AlgodClient:
        """The algod client used for ``network`` (CAIP-2 or V1 name).

        Raises:
            NetworkError: If no algod is configured for the network.
            NetworkMismatchError: If the configured algod is on another network.
        """
        caip2 = normalize_network(network)
        client = self._clients.get(caip2)
        if client is not None:
            return client
        if self._algod is not None:
            actual = caip2_from_genesis_hash(self._algod.suggested_params().gh)
            if actual != caip2:
                raise NetworkMismatchError(f"algod is on {actual} but the request is for {caip2}")
            client = self._algod
        else:
            config = NETWORK_CONFIGS.get(caip2)
            if not config:
                raise NetworkError(
                    f"no algod configured for {caip2}: pass algod_client or algod_url"
                )
            client = algod.AlgodClient("", config["algod_url"])
        self._clients[caip2] = client
        return client

    @staticmethod
    def _as_signed(txn: Any) -> Any:
        if isinstance(txn, transaction.Transaction):
            return transaction.SignedTransaction(txn, None)
        return txn

    def __repr__(self) -> str:
        return f"{type(self).__name__}(addresses={self._keyring.addresses!r})"
