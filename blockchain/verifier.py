"""Read a fingerprint back from the chain and re-verify the local record.

Verification deliberately re-derives the local digest from the record data
rather than reusing the value computed during the write. That is the whole
point: if the record is altered afterwards, the recomputed digest changes and
stops matching the immutable on-chain commitment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from integrity.hashing import fingerprint as compute_fingerprint

from .chain import ChainConnection, ChainError, load_artifact


@dataclass
class VerificationResult:
    """Outcome of comparing a recomputed digest with the on-chain one."""

    record_id: int
    local_fingerprint: str
    onchain_fingerprint: str
    anchored_at: int
    submitter: str
    network: str
    contract_address: str
    onchain_self_check: bool

    @property
    def verified(self) -> bool:
        return self.local_fingerprint == self.onchain_fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "local_fingerprint": self.local_fingerprint,
            "onchain_fingerprint": self.onchain_fingerprint,
            "verified": self.verified,
            "anchored_at": self.anchored_at,
            "submitter": self.submitter,
            "network": self.network,
            "contract_address": self.contract_address,
            "onchain_self_check": self.onchain_self_check,
        }


class EvidenceVerifier:
    """Reads anchored records and checks them against local data."""

    def __init__(self, connection: ChainConnection) -> None:
        self.connection = connection
        self.web3 = connection.web3
        self.artifact = load_artifact()

    def _contract(self, address: str):
        return self.web3.eth.contract(
            address=self.web3.to_checksum_address(address), abi=self.artifact["abi"]
        )

    def read_record(self, contract_address: str, record_id: int) -> tuple[str, int, str]:
        """Fetch ``(fingerprint_hex, timestamp, submitter)`` from the chain."""
        contract = self._contract(contract_address)
        try:
            fingerprint_bytes, timestamp, submitter = contract.functions.getRecord(
                record_id
            ).call()
        except Exception as exc:  # noqa: BLE001 - revert or transport failure
            raise ChainError(
                f"Could not read record {record_id} from {contract_address}: {exc}"
            ) from exc

        return fingerprint_bytes.hex(), int(timestamp), str(submitter)

    def verify_record(
        self,
        contract_address: str,
        record_id: int,
        record_data: dict[str, Any],
    ) -> VerificationResult:
        """Recompute the digest of ``record_data`` and compare it on-chain.

        Returns a result either way — a mismatch is a legitimate outcome to
        report, not an exception.
        """
        onchain_fingerprint, anchored_at, submitter = self.read_record(
            contract_address, record_id
        )
        local_fingerprint = compute_fingerprint(record_data)

        contract = self._contract(contract_address)
        try:
            onchain_self_check = bool(
                contract.functions.verify(
                    record_id, bytes.fromhex(local_fingerprint)
                ).call()
            )
        except Exception:  # noqa: BLE001 - convenience check only
            onchain_self_check = False

        return VerificationResult(
            record_id=record_id,
            local_fingerprint=local_fingerprint,
            onchain_fingerprint=onchain_fingerprint,
            anchored_at=anchored_at,
            submitter=submitter,
            network=self.connection.network,
            contract_address=contract_address,
            onchain_self_check=onchain_self_check,
        )
