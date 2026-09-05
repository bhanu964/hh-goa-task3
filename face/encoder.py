"""Turn images into ArcFace embeddings.

This is a thin convenience layer over :class:`face.detector.FaceDetector` so
the orchestrator reads as ``load image -> encode -> compare`` rather than
poking at detection internals.

An embedding is a 512-dimensional float vector used *only* for comparing
faces. It is deliberately never written to the blockchain, and never fed into
the SHA-256 integrity fingerprint — those are separate concerns.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .detector import DetectedFace, FaceDetectionError, FaceDetector, decode_image, load_image


class FaceEncoder:
    """Produces embeddings from image files or raw bytes."""

    EMBEDDING_DIM = 512

    def __init__(self, detector: FaceDetector) -> None:
        self.detector = detector

    def encode_file(self, path: str | Path) -> tuple[DetectedFace, int]:
        """Encode the primary (largest) face in an image file.

        Returns the face and the total number of faces detected.
        """
        image = load_image(path)
        return self.detector.detect_primary(image)

    def encode_bytes(self, data: bytes) -> DetectedFace | None:
        """Encode the primary face in raw image bytes.

        Returns ``None`` when the bytes are not a decodable image or contain no
        face — both are ordinary outcomes when walking search results, not
        errors worth aborting the pipeline for.
        """
        image = decode_image(data)
        if image is None:
            return None
        faces = self.detector.detect(image)
        return faces[0] if faces else None

    @staticmethod
    def as_vector(face: DetectedFace) -> np.ndarray:
        return face.embedding


__all__ = ["FaceEncoder", "FaceDetectionError"]
