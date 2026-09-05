"""Face detection backed by InsightFace's RetinaFace (``det_10g.onnx``).

Only the ``detection`` and ``recognition`` sub-models of the model pack are
loaded — the landmark and gender/age models are not needed for this pipeline
and skipping them roughly halves start-up time.

Adapted from the public API of deepinsight/insightface (MIT licensed code;
see README for the pretrained-model licence note).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


class FaceDetectionError(Exception):
    """Raised when an image cannot be read or contains no usable face."""


@dataclass(frozen=True)
class DetectedFace:
    """One detected face and its ArcFace embedding.

    ``embedding`` is L2-normalised, so the cosine similarity between two of
    them is just their dot product.
    """

    bbox: tuple[int, int, int, int]
    det_score: float
    embedding: np.ndarray

    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.bbox
        return max(0, x2 - x1) * max(0, y2 - y1)


def load_image(path: str | Path) -> np.ndarray:
    """Read an image from disk into a BGR array, with clear errors."""
    path = Path(path)
    if not path.exists():
        raise FaceDetectionError(f"Image not found: {path}")
    if not path.is_file():
        raise FaceDetectionError(f"Not a file: {path}")
    if path.stat().st_size == 0:
        raise FaceDetectionError(f"Image is empty: {path}")

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FaceDetectionError(
            f"Could not decode {path} — is it a valid JPG/PNG/WebP image?"
        )
    return image


def decode_image(data: bytes) -> np.ndarray | None:
    """Decode raw image bytes to BGR. Returns None if the bytes aren't an image."""
    if not data:
        return None
    buffer = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


class FaceDetector:
    """Lazy wrapper around ``insightface.app.FaceAnalysis``.

    The model pack (~280 MB) downloads on first use into ``~/.insightface``.
    """

    def __init__(
        self,
        model_pack: str = "buffalo_l",
        det_size: int = 640,
        det_threshold: float = 0.5,
    ) -> None:
        self.model_pack = model_pack
        self.det_size = det_size
        self.det_threshold = det_threshold
        self._app = None

    def _ensure_loaded(self):
        if self._app is not None:
            return self._app

        # InsightFace prints provider/model chatter on stdout that would clutter
        # the recorded demo; keep it out of the way but still available on stderr
        # if something goes wrong.
        import contextlib
        import io

        from insightface.app import FaceAnalysis

        noise = io.StringIO()
        try:
            with contextlib.redirect_stdout(noise):
                app = FaceAnalysis(
                    name=self.model_pack,
                    allowed_modules=["detection", "recognition"],
                    providers=["CPUExecutionProvider"],
                )
                app.prepare(
                    ctx_id=-1,
                    det_thresh=self.det_threshold,
                    det_size=(self.det_size, self.det_size),
                )
        except Exception as exc:  # noqa: BLE001 - surfaced to the CLI as a clean error
            raise FaceDetectionError(
                f"Could not initialise InsightFace model pack '{self.model_pack}': {exc}"
            ) from exc

        self._app = app
        return app

    def detect(self, image: np.ndarray) -> list[DetectedFace]:
        """Detect every face in a BGR image, largest first."""
        app = self._ensure_loaded()
        faces = app.get(image)

        detected = [
            DetectedFace(
                bbox=tuple(int(v) for v in face.bbox),  # type: ignore[arg-type]
                det_score=float(face.det_score),
                embedding=np.asarray(face.normed_embedding, dtype=np.float32),
            )
            for face in faces
        ]
        detected.sort(key=lambda f: f.area, reverse=True)
        return detected

    def detect_primary(self, image: np.ndarray) -> tuple[DetectedFace, int]:
        """Return the largest face plus the total number of faces found.

        Raises ``FaceDetectionError`` when there is no face at all. Callers
        decide how to report the multi-face case.
        """
        faces = self.detect(image)
        if not faces:
            raise FaceDetectionError("No face detected in the image")
        return faces[0], len(faces)
