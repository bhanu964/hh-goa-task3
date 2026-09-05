"""Blockchain anchoring and verification against a real in-process EVM.

These run a genuine py-evm chain: contracts are deployed, transactions are
mined and state is read back through the ABI. No mocks stand in for the chain.
"""

import pytest

from blockchain.chain import ChainError, connect, load_artifact
from blockchain.verifier import EvidenceVerifier
from blockchain.writer import EvidenceWriter
from integrity.hashing import build_record

RECORD_KWARGS = dict(
    platform="Instagram",
    source_url="https://www.instagram.com/p/EXAMPLE/",
    title="A discovered post",
    source_name="Instagram",
    image_url="https://example.com/image.jpg",
    image_sha256="ab" * 32,
    face_similarity=0.7891,
    match_threshold=0.45,
    query_image_sha256="cd" * 32,
    search_engine="google_lens",
    search_provider="serpapi",
    search_id="search-123",
    match_section="visual_matches",
    discovered_at="2026-09-05T10:00:00+00:00",
)


@pytest.fixture(scope="module")
def chain():
    return connect("memory", "", None)


@pytest.fixture(scope="module")
def deployed(chain):
    writer = EvidenceWriter(chain)
    return writer, writer.deploy()


@pytest.fixture()
def record():
    return build_record(**RECORD_KWARGS)


def test_artifact_exposes_the_expected_abi():
    names = {e.get("name") for e in load_artifact()["abi"]}
    assert {"anchor", "getRecord", "verify", "recordCount"} <= names


def test_unknown_network_is_rejected():
    with pytest.raises(ChainError, match="Unknown BLOCKCHAIN_NETWORK"):
        connect("dogecoin", "", None)


def test_contract_deploys_to_an_address(deployed):
    _, address = deployed
    assert address.startswith("0x") and len(address) == 42


def test_anchoring_produces_a_real_mined_transaction(deployed, record):
    writer, address = deployed
    receipt = writer.anchor(record.digest, address)

    assert receipt.tx_hash.startswith("0x") and len(receipt.tx_hash) == 66
    assert receipt.block_number > 0
    assert receipt.gas_used > 0
    assert receipt.fingerprint == record.digest


def test_unchanged_record_verifies(deployed, record):
    writer, address = deployed
    receipt = writer.anchor(record.digest, address)

    result = EvidenceVerifier(writer.connection).verify_record(
        address, receipt.record_id, record.data
    )
    assert result.verified
    assert result.local_fingerprint == result.onchain_fingerprint
    assert result.onchain_self_check


def test_tampered_record_fails_verification(deployed, record):
    writer, address = deployed
    receipt = writer.anchor(record.digest, address)

    tampered = dict(record.data)
    tampered["discovered_post"] = dict(tampered["discovered_post"]) | {"title": "changed"}

    result = EvidenceVerifier(writer.connection).verify_record(
        address, receipt.record_id, tampered
    )
    assert not result.verified
    assert result.local_fingerprint != result.onchain_fingerprint
    assert not result.onchain_self_check


def test_onchain_fingerprint_is_exactly_what_was_written(deployed, record):
    writer, address = deployed
    receipt = writer.anchor(record.digest, address)

    onchain, timestamp, submitter = EvidenceVerifier(writer.connection).read_record(
        address, receipt.record_id
    )
    assert onchain == record.digest
    assert timestamp > 0
    assert submitter.lower() == writer.connection.account_address.lower()


def test_record_ids_increment_across_anchors(deployed, record):
    writer, address = deployed
    first = writer.anchor(record.digest, address)
    second = writer.anchor(record.digest, address)
    assert second.record_id == first.record_id + 1


def test_reading_a_missing_record_raises(deployed):
    writer, address = deployed
    with pytest.raises(ChainError, match="Could not read record"):
        EvidenceVerifier(writer.connection).read_record(address, 99_999)


def test_malformed_fingerprint_is_rejected_before_any_transaction(deployed):
    writer, address = deployed
    with pytest.raises(ChainError, match="64-character SHA-256"):
        writer.anchor("deadbeef", address)


def test_a_zero_fingerprint_is_refused_by_the_contract(deployed):
    writer, address = deployed
    with pytest.raises(ChainError):
        writer.anchor("00" * 32, address)
