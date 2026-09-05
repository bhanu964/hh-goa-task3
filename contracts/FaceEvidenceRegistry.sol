// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title FaceEvidenceRegistry
/// @notice Tamper-evident anchor for face-verified discoveries.
///
/// The pipeline discovers a public post via reverse-image search, verifies the
/// face in it off-chain, builds a deterministic metadata record, and anchors
/// only the SHA-256 digest of that record here.
///
/// Deliberately NOT stored on-chain: face images, face embeddings, or any
/// other biometric data. Biometric processing stays entirely off-chain; the
/// chain is the trust and audit layer, holding a 32-byte commitment that
/// proves the record existed in this exact form at this block time.
contract FaceEvidenceRegistry {
    struct Record {
        bytes32 fingerprint; // SHA-256 of the canonical evidence record
        uint64 timestamp; // block time of anchoring; 0 means "does not exist"
        address submitter;
    }

    mapping(uint256 => Record) private _records;

    /// @notice Number of records anchored so far; also the id of the newest.
    uint256 public recordCount;

    event EvidenceAnchored(
        uint256 indexed recordId,
        bytes32 indexed fingerprint,
        address indexed submitter,
        uint64 timestamp
    );

    /// @notice Anchor a record fingerprint on-chain.
    /// @param fingerprint SHA-256 digest of the canonical evidence record.
    /// @return recordId Sequential id used to read the record back.
    function anchor(bytes32 fingerprint) external returns (uint256 recordId) {
        require(fingerprint != bytes32(0), "empty fingerprint");

        unchecked {
            recordId = ++recordCount;
        }

        _records[recordId] = Record({
            fingerprint: fingerprint,
            timestamp: uint64(block.timestamp),
            submitter: msg.sender
        });

        emit EvidenceAnchored(recordId, fingerprint, msg.sender, uint64(block.timestamp));
    }

    /// @notice Read an anchored record back.
    /// @dev Reverts on an unknown id so a missing record can never be mistaken
    ///      for a zero fingerprint.
    function getRecord(uint256 recordId)
        external
        view
        returns (bytes32 fingerprint, uint64 timestamp, address submitter)
    {
        Record memory record = _records[recordId];
        require(record.timestamp != 0, "record not found");
        return (record.fingerprint, record.timestamp, record.submitter);
    }

    /// @notice True only if `recordId` exists and holds exactly `fingerprint`.
    /// @dev A convenience cross-check. The pipeline's real verification
    ///      recomputes the SHA-256 locally and compares it against the value
    ///      returned by `getRecord`.
    function verify(uint256 recordId, bytes32 fingerprint) external view returns (bool) {
        Record memory record = _records[recordId];
        return record.timestamp != 0 && record.fingerprint == fingerprint;
    }

    /// @notice Whether a record id has been anchored.
    function exists(uint256 recordId) external view returns (bool) {
        return _records[recordId].timestamp != 0;
    }
}
