"""Deploy the registry (when needed) and anchor a fingerprint on-chain.

Every transaction here is a real one: signed, broadcast, and waited on until a
receipt with ``status == 1`` comes back. Nothing is simulated, and a failed
transaction is reported as a failure rather than smoothed over.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web3.exceptions import ContractLogicError, TimeExhausted

from .chain import ChainConnection, ChainError, load_artifact

DEPLOYMENT_PATH = Path(__file__).resolve().parent.parent / "blockchain" / "deployment.json"


@dataclass
class AnchorReceipt:
    """Result of anchoring one fingerprint."""

    record_id: int
    fingerprint: str
    tx_hash: str
    block_number: int
    gas_used: int
    contract_address: str
    network: str
    explorer_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "fingerprint": self.fingerprint,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
            "contract_address": self.contract_address,
            "network": self.network,
            "explorer_url": self.explorer_url,
        }


class EvidenceWriter:
    """Writes evidence fingerprints to the FaceEvidenceRegistry contract."""

    def __init__(self, connection: ChainConnection, tx_timeout: int = 300) -> None:
        self.connection = connection
        self.tx_timeout = tx_timeout
        self.artifact = load_artifact()
        self.web3 = connection.web3

    # -- transaction plumbing ---------------------------------------------

    def _send(self, transaction: dict[str, Any]) -> Any:
        """Sign (if we hold a key) and broadcast, then wait for the receipt."""
        web3 = self.web3
        sender = web3.to_checksum_address(self.connection.account_address)
        transaction.setdefault("from", sender)
        transaction.setdefault("nonce", web3.eth.get_transaction_count(sender))
        transaction.setdefault("chainId", web3.eth.chain_id)

        if "gas" not in transaction:
            try:
                transaction["gas"] = int(web3.eth.estimate_gas(transaction) * 1.25)
            except Exception:  # noqa: BLE001 - fall back to a safe ceiling
                transaction["gas"] = 500_000

        try:
            if self.connection.private_key:
                signed = web3.eth.account.sign_transaction(
                    transaction, self.connection.private_key
                )
                tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
            else:
                # In-process EVM: accounts are unlocked, no signing needed.
                tx_hash = web3.eth.send_transaction(transaction)
        except ContractLogicError as exc:
            raise ChainError(f"Transaction reverted: {exc}") from exc
        except ValueError as exc:
            message = str(exc)
            if "insufficient funds" in message.lower():
                raise ChainError(
                    f"Wallet {sender} has no funds on {self.connection.network}. "
                    "Fund it from a Sepolia faucet (e.g. https://sepoliafaucet.com) "
                    "and try again."
                ) from exc
            raise ChainError(f"Transaction rejected by the node: {message}") from exc
        except Exception as exc:  # noqa: BLE001 - transport-level failures
            raise ChainError(f"Could not broadcast transaction: {exc}") from exc

        try:
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.tx_timeout)
        except TimeExhausted as exc:
            raise ChainError(
                f"Transaction {web3.to_hex(tx_hash)} was not mined within "
                f"{self.tx_timeout}s. It may still confirm later."
            ) from exc

        if receipt.get("status") != 1:
            raise ChainError(
                f"Transaction {web3.to_hex(tx_hash)} failed on-chain (status 0)"
            )
        return receipt

    def _build(self, builder, overrides: dict[str, Any]) -> dict[str, Any]:
        """Build a transaction, converting node-side reverts into ChainError.

        ``build_transaction`` estimates gas, so a ``require`` failure is raised
        here rather than at broadcast time.
        """
        try:
            return builder.build_transaction(overrides)
        except ContractLogicError as exc:
            raise ChainError(f"Transaction would revert: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - node-specific revert types
            message = str(exc)
            if "revert" in message.lower():
                raise ChainError(f"Transaction would revert: {message}") from exc
            raise ChainError(f"Could not build transaction: {message}") from exc

    def _fee_fields(self) -> dict[str, Any]:
        """EIP-1559 fees where supported, legacy gasPrice otherwise."""
        web3 = self.web3
        try:
            base_fee = web3.eth.get_block("latest").get("baseFeePerGas")
        except Exception:  # noqa: BLE001
            base_fee = None

        if base_fee is None:
            try:
                return {"gasPrice": web3.eth.gas_price}
            except Exception:  # noqa: BLE001
                return {}

        try:
            priority = web3.eth.max_priority_fee
        except Exception:  # noqa: BLE001
            priority = web3.to_wei(1.5, "gwei")

        return {
            "maxFeePerGas": base_fee * 2 + priority,
            "maxPriorityFeePerGas": priority,
        }

    # -- contract lifecycle -----------------------------------------------

    def deploy(self) -> str:
        """Deploy a fresh registry and return its address."""
        contract = self.web3.eth.contract(
            abi=self.artifact["abi"], bytecode=self.artifact["bytecode"]
        )
        sender = self.web3.to_checksum_address(self.connection.account_address)
        transaction = self._build(
            contract.constructor(),
            {
                "from": sender,
                "nonce": self.web3.eth.get_transaction_count(sender),
                **self._fee_fields(),
            },
        )
        receipt = self._send(transaction)
        address = receipt["contractAddress"]
        self._record_deployment(address, receipt)
        return address

    def _record_deployment(self, address: str, receipt) -> None:
        """Note the deployment for reuse on later runs.

        Best-effort only: this is a convenience so a repeat run can set
        CONTRACT_ADDRESS instead of paying to redeploy. A container with a
        read-only or non-writable app directory must not fail a otherwise
        successful deployment just because this note could not be saved.
        """
        try:
            DEPLOYMENT_PATH.write_text(
                json.dumps(
                    {
                        "network": self.connection.network,
                        "contractAddress": address,
                        "deployedBy": self.connection.account_address,
                        "blockNumber": receipt["blockNumber"],
                        "txHash": self.web3.to_hex(receipt["transactionHash"]),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def get_contract(self, address: str | None = None):
        """Return a bound contract instance, deploying one if needed.

        A configured ``CONTRACT_ADDRESS`` is reused so repeat runs on a public
        testnet don't pay to redeploy.
        """
        if not address:
            address = self.deploy()
        return self.web3.eth.contract(
            address=self.web3.to_checksum_address(address), abi=self.artifact["abi"]
        )

    # -- anchoring ---------------------------------------------------------

    def anchor(self, fingerprint_hex: str, contract_address: str | None = None) -> AnchorReceipt:
        """Write a SHA-256 fingerprint on-chain and return its receipt."""
        digest = fingerprint_hex.removeprefix("0x")
        if len(digest) != 64:
            raise ChainError(
                f"Fingerprint must be a 64-character SHA-256 hex digest, got {len(digest)}"
            )
        fingerprint_bytes = bytes.fromhex(digest)

        contract = self.get_contract(contract_address)
        sender = self.web3.to_checksum_address(self.connection.account_address)

        transaction = self._build(
            contract.functions.anchor(fingerprint_bytes),
            {
                "from": sender,
                "nonce": self.web3.eth.get_transaction_count(sender),
                **self._fee_fields(),
            },
        )
        receipt = self._send(transaction)

        # recordCount is incremented by this transaction, so it is our id.
        record_id = int(contract.functions.recordCount().call())
        tx_hash = self.web3.to_hex(receipt["transactionHash"])

        return AnchorReceipt(
            record_id=record_id,
            fingerprint=digest,
            tx_hash=tx_hash,
            block_number=int(receipt["blockNumber"]),
            gas_used=int(receipt["gasUsed"]),
            contract_address=contract.address,
            network=self.connection.network,
            explorer_url=self.connection.tx_url(tx_hash),
        )
