"""Face comparison: cosine similarity between ArcFace embeddings.

InsightFace's ``normed_embedding`` is already L2-normalised, so cosine
similarity reduces to a dot product and always lands in [-1, 1].

Threshold
---------
The default acceptance threshold is **0.45**, which is a widely used operating
point for ArcFace/``buffalo_l`` 512-d embeddings: typical same-person pairs
score well above it and different-person pairs well below. It is configurable
via ``FACE_MATCH_THRESHOLD`` so it can be tightened for a stricter demo.
The threshold that was actually applied is recorded in the evidence record, so
a verifier can see the criterion the decision was made under.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_MATCH_THRESHOLD = 0.45


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors, robust to non-normalised input."""
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()

    if a.shape != b.shape:
        raise ValueError(f"Embedding dimension mismatch: {a.shape} vs {b.shape}")

    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise ValueError("Cannot compare a zero-length embedding")

    similarity = float(np.dot(a, b) / (norm_a * norm_b))
    # Guard against float error pushing the value a hair outside [-1, 1].
    return max(-1.0, min(1.0, similarity))


@dataclass(frozen=True)
class FaceMatch:
    """Outcome of comparing two face embeddings."""

    similarity: float
    threshold: float

    @property
    def is_match(self) -> bool:
        return self.similarity >= self.threshold

    @property
    def percent(self) -> float:
        """Similarity as a 0-100 figure for display only.

        Cosine similarity is mapped from [-1, 1] onto [0, 100] so the printed
        percentage never looks negative. Decisions always use ``similarity``.
        """
        return round((self.similarity + 1.0) / 2.0 * 100.0, 2)


def compare(
    a: np.ndarray,
    b: np.ndarray,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> FaceMatch:
    """Compare two embeddings against a threshold."""
    return FaceMatch(similarity=cosine_similarity(a, b), threshold=threshold)
