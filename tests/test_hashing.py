"""Determinism and sensitivity of the SHA-256 evidence fingerprint."""

import json

import pytest

from integrity.hashing import (
    EvidenceRecord,
    build_record,
    canonical_json,
    fingerprint,
    sha256_bytes,
)

RECORD_KWARGS = dict(
    platform="Instagram",
    source_url="https://www.instagram.com/p/EXAMPLE/",
    title="A discovered post",
    source_name="Instagram",
    image_url="https://example.com/image.jpg",
    image_sha256="ab" * 32,
    face_similarity=0.789123456789,
    match_threshold=0.45,
    query_image_sha256="cd" * 32,
    search_engine="google_lens",
    search_provider="serpapi",
    search_id="search-123",
    match_section="visual_matches",
    discovered_at="2026-09-05T10:00:00+00:00",
)


def test_canonical_json_sorts_keys_at_every_level():
    a = canonical_json({"b": 1, "a": {"z": 1, "y": 2}})
    b = canonical_json({"a": {"y": 2, "z": 1}, "b": 1})
    assert a == b == '{"a":{"y":2,"z":1},"b":1}'


def test_canonical_json_has_no_insignificant_whitespace():
    assert " " not in canonical_json({"a": 1, "b": [1, 2]})


def test_canonical_json_preserves_unicode_literally():
    assert "é" in canonical_json({"title": "café"})
    assert "\\u" not in canonical_json({"title": "café"})


def test_fingerprint_is_stable_across_key_order():
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


def test_fingerprint_is_64_hex_characters():
    digest = fingerprint({"a": 1})
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_float_precision_is_pinned():
    """Trailing float noise must not change the digest."""
    assert fingerprint({"s": 0.1234567891}) == fingerprint({"s": 0.1234567894})


def test_identical_records_produce_identical_digests():
    assert build_record(**RECORD_KWARGS).digest == build_record(**RECORD_KWARGS).digest


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_url", "https://www.instagram.com/p/DIFFERENT/"),
        ("title", "A different post"),
        ("platform", "Facebook"),
        ("image_sha256", "ef" * 32),
        ("face_similarity", 0.6),
    ],
)
def test_any_changed_field_changes_the_digest(field, value):
    baseline = build_record(**RECORD_KWARGS).digest
    altered = build_record(**{**RECORD_KWARGS, field: value}).digest
    assert altered != baseline


def test_empty_fields_are_dropped_not_stored_as_null():
    record = build_record(**{**RECORD_KWARGS, "image_url": None})
    assert "image_url" not in record.data["discovered_post"]


def test_record_survives_a_save_load_round_trip(tmp_path):
    record = build_record(**RECORD_KWARGS)
    path = record.save(tmp_path / "record.json")
    assert EvidenceRecord.load(path).digest == record.digest


def test_saved_file_records_the_digest_it_was_built_with(tmp_path):
    record = build_record(**RECORD_KWARGS)
    payload = json.loads(record.save(tmp_path / "r.json").read_text(encoding="utf-8"))
    assert payload["sha256"] == record.digest


def test_sha256_bytes_matches_known_value():
    # SHA-256 of the empty string.
    assert sha256_bytes(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
