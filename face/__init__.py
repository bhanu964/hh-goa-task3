"""Face detection, embedding and matching (InsightFace / ArcFace)."""

from .detector import FaceDetectionError, FaceDetector, DetectedFace
from .encoder import FaceEncoder
from .matcher import FaceMatch, cosine_similarity, compare

__all__ = [
    "FaceDetectionError",
    "FaceDetector",
    "DetectedFace",
    "FaceEncoder",
    "FaceMatch",
    "cosine_similarity",
    "compare",
]
