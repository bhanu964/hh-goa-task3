"""Face detection backed by InsightFace's RetinaFace (``det_10g.onnx``).

Only the ``detection`` and ``recognition`` sub-models of the model pack are
loaded — the landmark and gender/age models are not needed for this pipeline
and skipping them roughly halves start-up time.

Adapted from the public API of deepinsight/insightface (MIT licensed code;
see README for the pretrained-model licence note).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from utils.imaging import ImageError, LoadedImage
from utils.imaging import decode_bytes as _decode_bytes
from utils.imaging import load_image as _load_image


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
    """Read an image from disk into a BGR array.

    Accepts JPG/JPEG, PNG, WebP, BMP, TIFF and GIF, identified by content
    rather than by file extension. See :mod:`utils.imaging`.
    """
    return load_input(path).bgr


def load_input(path: str | Path) -> LoadedImage:
    """Read an input image along with its raw bytes and detected format."""
    try:
        return _load_image(path)
    except ImageError as exc:
        raise FaceDetectionError(str(exc)) from exc


def decode_image(data: bytes) -> np.ndarray | None:
    """Decode raw image bytes to BGR. Returns None if the bytes aren't an image."""
    return _decode_bytes(data)


class FaceDetector:
    """Lazy wrapper around ``insightface.app.FaceAnalysis``.

    The model pack (~280 MB) downloads on first use into ``~/.insightface``.
    """

    def __init__(
        self,
        model_pack: str = "buffalo_l",
        det_size: int = 640,
        det_threshold: float = 0.5,
        model_root: str | None = None,
    ) -> None:
        self.model_pack = model_pack
        self.det_size = det_size
        self.det_threshold = det_threshold
        # Where the model pack lives. Defaults to InsightFace's own
        # ``~/.insightface``; container images set INSIGHTFACE_HOME so the
        # weights baked in at build time are found instead of being
        # re-downloaded (or failing outright on a read-only filesystem).
        self.model_root = model_root or os.getenv("INSIGHTFACE_HOME") or "~/.insightface"
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
                    root=self.model_root,
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
