"""Canonical evidence records and their SHA-256 fingerprints.

The fingerprint is what goes on-chain, so it has to be reproducible: the same
record must hash to the same digest on any machine, at any later date, or
verification is meaningless.

Determinism comes from :func:`canonical_json`:

* keys sorted at every level
* no insignificant whitespace
* UTF-8 without ``\\uXXXX`` escaping, so text hashes by its actual characters
* floats rounded to a fixed precision before serialisation

This fingerprint is a cryptographic hash of *discovered public post metadata*.
It is emphatically not the face embedding — biometric vectors never enter the
record and never reach the blockchain.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

# Similarity is a float; pinning the precision keeps its JSON form stable.
FLOAT_PRECISION = 6


def _normalise(value: Any) -> Any:
    """Recursively make a value safe to serialise deterministically."""
    if isinstance(value, float):
        return round(value, FLOAT_PRECISION)
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    return value


def canonical_json(record: dict[str, Any]) -> str:
    """Serialise a record to its one canonical string form."""
    return json.dumps(
        _normalise(record),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def fingerprint(record: dict[str, Any]) -> str:
    """SHA-256 of the canonical form of a record, as lowercase hex."""
    return hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class EvidenceRecord:
    """A discovered post plus the evidence that it matched, and its digest."""

    data: dict[str, Any]

    @property
    def digest(self) -> str:
        return fingerprint(self.data)

    @property
    def canonical(self) -> str:
        return canonical_json(self.data)

    def save(self, path: str | Path) -> Path:
        """Write the record and its digest to disk for later re-verification."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "record": _normalise(self.data),
            "sha256": self.digest,
            "canonical_form_note": (
                "sha256 is taken over json.dumps(record, sort_keys=True, "
                "separators=(',',':'), ensure_ascii=False) encoded as UTF-8"
            ),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def load(path: str | Path) -> "EvidenceRecord":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return EvidenceRecord(data=payload["record"])


def build_record(
    *,
    platform: str,
    source_url: str,
    title: str,
    source_name: str,
    image_url: str | None,
    image_sha256: str,
    face_similarity: float,
    match_threshold: float,
    query_image_sha256: str,
    search_engine: str,
    search_provider: str,
    search_id: str | None,
    match_section: str,
    discovered_at: str | None = None,
) -> EvidenceRecord:
    """Assemble the evidence record for a face-verified discovery.

    Only fields that are genuinely available are included — empty values are
    dropped rather than stored as nulls, so the record never implies it holds
    data the search did not actually return.
    """
    discovered = {
        "platform": platform,
        "source_url": source_url,
        "title": title,
        "source_name": source_name,
        "image_url": image_url,
        "image_sha256": image_sha256,
    }
    provenance = {
        "search_provider": search_provider,
        "search_engine": search_engine,
        "search_id": search_id,
        "match_section": match_section,
        "query_image_sha256": query_image_sha256,
    }
    verification = {
        "face_similarity": round(float(face_similarity), FLOAT_PRECISION),
        "match_threshold": round(float(match_threshold), FLOAT_PRECISION),
        "metric": "cosine_similarity",
        "embedding_model": "insightface/buffalo_l (ArcFace w600k_r50, 512-d)",
    }

    record = {
        "schema_version": SCHEMA_VERSION,
        "discovered_at": discovered_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "discovered_post": {k: v for k, v in discovered.items() if v not in (None, "")},
        "provenance": {k: v for k, v in provenance.items() if v not in (None, "")},
        "face_verification": verification,
    }
    return EvidenceRecord(data=record)
