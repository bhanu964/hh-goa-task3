"""Robust image input handling.

One place that answers "can we actually use this file, and as what?", so the
face layer and the upload layer never disagree about a file's format.

What it handles:

* Any common still format — JPG/JPEG, PNG, WebP, BMP, TIFF, GIF — recognised by
  its *content*, not its file extension, so ``photo.jpg`` that is really a PNG
  is still read correctly and uploaded in a form SerpApi accepts.
* Paths as people actually type them: ``~/Pictures/x.jpg``, values with stray
  surrounding quotes or trailing spaces, and non-ASCII filenames (bytes are
  read in Python and decoded in memory, which also avoids OpenCV's unicode-path
  problem on Windows).
* EXIF orientation. ``cv2.imdecode`` applies it, so a portrait phone photo is
  loaded upright rather than sideways.
* HEIC/HEIF and AVIF — the iPhone default — are detected and reported with the
  exact command to convert, instead of failing as "not an image".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

#: Formats the pipeline can read.
SUPPORTED_FORMATS = ("JPEG", "PNG", "WEBP", "BMP", "TIFF", "GIF")

#: Extensions to advertise in help text and errors.
SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")

#: Formats SerpApi's image upload endpoint accepts directly.
UPLOAD_FORMATS = ("JPEG", "PNG", "WEBP")

#: Formats we can name but not decode without an extra dependency.
UNDECODABLE_FORMATS = ("HEIF", "AVIF")

#: Beyond this edge length an image is downscaled before detection. The
#: recognition model works from a 112x112 aligned crop, so this costs no
#: accuracy on any reasonably framed face and keeps memory bounded.
MAX_DETECTION_EDGE = 2400


class ImageError(Exception):
    """A file could not be used as an input image, with a reason a user can act on."""


def resolve_image_path(raw: str | os.PathLike[str]) -> Path:
    """Turn a user-supplied path string into a real path.

    Strips surrounding quotes and whitespace left by copy-paste or drag-and-drop,
    and expands ``~`` and environment variables.
    """
    text = str(raw).strip()
    for quote in ('"', "'"):
        if len(text) >= 2 and text.startswith(quote) and text.endswith(quote):
            text = text[1:-1].strip()
            break
    return Path(os.path.expandvars(os.path.expanduser(text)))


def sniff_format(data: bytes) -> str | None:
    """Identify an image format from its magic bytes.

    Returns a format name, or ``None`` if the bytes are not a recognised image.
    """
    if len(data) < 12:
        return None

    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data[:2] == b"BM":
        return "BMP"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "TIFF"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"

    # ISO-BMFF container: HEIC/HEIF (iPhone) and AVIF share this shape.
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
            return "HEIF"
        if brand in (b"avif", b"avis"):
            return "AVIF"

    return None


def _conversion_hint(image_format: str, path: Path) -> str:
    """Tell the user exactly how to get a usable file."""
    if image_format in UNDECODABLE_FORMATS:
        return (
            f"{image_format} images (the iPhone default) are not supported. Convert to JPEG "
            f"first:\n"
            f"    macOS:  sips -s format jpeg '{path}' --out '{path.with_suffix('.jpg')}'\n"
            f"    other:  pip install pillow-heif, or export the photo as JPEG"
        )
    return f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}"


def decode_bytes(data: bytes) -> np.ndarray | None:
    """Decode image bytes to a BGR array, honouring EXIF orientation.

    Returns ``None`` when the bytes are not a decodable image — an ordinary
    outcome when walking search results, not an error.
    """
    if not data:
        return None
    try:
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        return None


@dataclass(frozen=True)
class LoadedImage:
    """A successfully read input image and what we know about it."""

    path: Path
    bgr: np.ndarray
    data: bytes
    image_format: str

    @property
    def height(self) -> int:
        return int(self.bgr.shape[0])

    @property
    def width(self) -> int:
        return int(self.bgr.shape[1])

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def is_uploadable(self) -> bool:
        """Whether SerpApi accepts this format without re-encoding."""
        return self.image_format in UPLOAD_FORMATS

    def for_detection(self) -> np.ndarray:
        """The array to run detection on, downscaled if very large."""
        longest = max(self.height, self.width)
        if longest <= MAX_DETECTION_EDGE:
            return self.bgr
        scale = MAX_DETECTION_EDGE / longest
        return cv2.resize(
            self.bgr,
            (max(1, int(self.width * scale)), max(1, int(self.height * scale))),
            interpolation=cv2.INTER_AREA,
        )


def load_image(path: str | os.PathLike[str]) -> LoadedImage:
    """Read an input image, raising :class:`ImageError` with an actionable message."""
    resolved = resolve_image_path(path)

    if not resolved.exists():
        raise ImageError(f"Image not found: {resolved}")
    if resolved.is_dir():
        raise ImageError(f"That is a directory, not an image file: {resolved}")
    if not resolved.is_file():
        raise ImageError(f"Not a regular file: {resolved}")

    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise ImageError(f"Could not read {resolved}: {exc}") from exc

    if not data:
        raise ImageError(f"Image file is empty: {resolved}")

    image_format = sniff_format(data)
    if image_format is None:
        raise ImageError(
            f"{resolved.name} is not a recognised image file. "
            f"{_conversion_hint('', resolved)}"
        )
    if image_format in UNDECODABLE_FORMATS:
        raise ImageError(_conversion_hint(image_format, resolved))

    bgr = decode_bytes(data)
    if bgr is None:
        raise ImageError(
            f"{resolved.name} looks like a {image_format} file but could not be "
            "decoded — it may be truncated or corrupt."
        )
    if bgr.size == 0:
        raise ImageError(f"{resolved.name} decoded to an empty image.")

    return LoadedImage(path=resolved, bgr=bgr, data=data, image_format=image_format)
