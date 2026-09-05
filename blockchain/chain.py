"""Ethereum connection handling for the three supported networks.

===========  ==========================================================
``sepolia``  Public Ethereum test network over a JSON-RPC endpoint.
             Transactions are real, permanent and visible on Etherscan.
``local``    Any JSON-RPC node on localhost (Anvil, Hardhat, Ganache).
``memory``   In-process py-evm chain via eth-tester. A genuine EVM — real
             transactions, receipts and state — but it exists only for the
             lifetime of the process. Offline fallback; never presented as
             a public chain.
===========  ==========================================================

Whichever is used, the pipeline prints it, so a viewer of the recording can
always tell which chain the transaction landed on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web3 import Web3

DEFAULT_ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "FaceEvidenceRegistry.json"

NETWORK_LABELS = {
    "sepolia": "Ethereum Sepolia testnet",
    "local": "Local EVM node (JSON-RPC)",
    "memory": "In-process EVM (py-evm / eth-tester, ephemeral)",
}


class ChainError(Exception):
    """Any blockchain connectivity, funding or transaction failure."""


def load_artifact(path: str | Path = DEFAULT_ARTIFACT) -> dict[str, Any]:
    """Load the committed ABI + bytecode artifact."""
    path = Path(path)
    if not path.exists():
        raise ChainError(
            f"Contract artifact missing: {path}\n"
            "Run: python scripts/compile_contract.py"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChainError(f"Contract artifact is not valid JSON: {exc}") from exc


@dataclass
class ChainConnection:
    """A connected Web3 instance plus the account that pays for writes."""

    web3: Web3
    network: str
    account_address: str
    private_key: str | None
    explorer_base: str | None

    @property
    def label(self) -> str:
        return NETWORK_LABELS.get(self.network, self.network)

    @property
    def is_public_testnet(self) -> bool:
        return self.network == "sepolia"

    def balance_eth(self) -> float:
        wei = self.web3.eth.get_balance(self.web3.to_checksum_address(self.account_address))
        return float(self.web3.from_wei(wei, "ether"))

    def tx_url(self, tx_hash: str) -> str | None:
        return f"{self.explorer_base}/tx/{tx_hash}" if self.explorer_base else None

    def address_url(self, address: str) -> str | None:
        return f"{self.explorer_base}/address/{address}" if self.explorer_base else None


def connect(
    network: str,
    rpc_url: str,
    private_key: str | None,
    explorer_base: str | None = None,
    timeout: int = 30,
) -> ChainConnection:
    """Open a connection to the configured network.

    Raises :class:`ChainError` with an actionable message rather than letting a
    transport error surface raw.
    """
    network = (network or "local").strip().lower()
    if network not in NETWORK_LABELS:
        raise ChainError(
            f"Unknown BLOCKCHAIN_NETWORK '{network}'. Use one of: {', '.join(NETWORK_LABELS)}"
        )

    if network == "memory":
        return _connect_memory()

    web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))
    try:
        connected = web3.is_connected()
    except Exception as exc:  # noqa: BLE001 - transport failures vary widely
        raise ChainError(f"Could not reach {network} RPC at {rpc_url}: {exc}") from exc

    if not connected:
        hint = (
            "Start a local node, e.g. `anvil`, or point LOCAL_RPC_URL at one. "
            "Alternatively set BLOCKCHAIN_NETWORK=memory to use the in-process EVM."
            if network == "local"
            else "Check SEPOLIA_RPC_URL in your .env."
        )
        raise ChainError(f"No JSON-RPC node answering at {rpc_url}. {hint}")

    if not private_key:
        raise ChainError(
            "WALLET_PRIVATE_KEY is not set — it is needed to sign the anchoring "
            "transaction. Generate a throwaway testnet wallet with: "
            "python scripts/new_wallet.py"
        )

    key = private_key if private_key.startswith("0x") else f"0x{private_key}"
    try:
        account = web3.eth.account.from_key(key)
    except Exception as exc:  # noqa: BLE001 - malformed key
        raise ChainError(f"WALLET_PRIVATE_KEY is not a valid private key: {exc}") from exc

    return ChainConnection(
        web3=web3,
        network=network,
        account_address=account.address,
        private_key=key,
        explorer_base=explorer_base,
    )


def _connect_memory() -> ChainConnection:
    """Spin up an in-process py-evm chain with pre-funded accounts."""
    try:
        from web3 import EthereumTesterProvider
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ChainError(
            "The in-process EVM needs eth-tester: pip install 'eth-tester' 'py-evm'"
        ) from exc

    web3 = Web3(EthereumTesterProvider())
    if not web3.eth.accounts:
        raise ChainError("In-process EVM started with no accounts available")

    return ChainConnection(
        web3=web3,
        network="memory",
        account_address=web3.eth.accounts[0],
        private_key=None,  # eth-tester signs with its own unlocked accounts
        explorer_base=None,
    )
