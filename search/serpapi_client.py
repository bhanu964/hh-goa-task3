"""SerpApi Google Lens client — the real reverse-image search step.

Flow (per SerpApi's documented Image + Google Lens APIs):

    local file -> POST /image  -> image_id (valid ~10 minutes)
                              -> GET /search?engine=google_lens&image_id=...
                              -> structured JSON (visual_matches / exact_matches)

There is no browser, no scraping and no CAPTCHA in this path: it is a plain
authenticated HTTPS API call made fresh on every run. Results are therefore
generated dynamically at execution time and are never cached or hardcoded.

Uses the official ``serpapi`` package (MIT, serpapi/serpapi-python), whose only
dependency is ``requests``.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import serpapi

# SerpApi's /image endpoint rejects uploads above this size.
MAX_UPLOAD_BYTES = 500 * 1024

SUPPORTED_UPLOAD_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class SearchError(Exception):
    """Any failure of the reverse-image-search step, reported honestly."""


@dataclass
class LensSearchResult:
    """Raw Google Lens payload plus the bookkeeping we want to keep."""

    payload: dict[str, Any]
    image_id: str
    search_types: list[str] = field(default_factory=list)

    @property
    def search_metadata(self) -> dict[str, Any]:
        return self.payload.get("search_metadata") or {}

    @property
    def search_id(self) -> str | None:
        return self.search_metadata.get("id")

    @property
    def lens_url(self) -> str | None:
        return self.search_metadata.get("google_lens_url")


def prepare_upload_copy(path: str | Path, max_bytes: int = MAX_UPLOAD_BYTES) -> tuple[Path, bool]:
    """Return a path that satisfies SerpApi's upload constraints.

    The original file is used untouched when it is already an accepted format
    and within the size cap. Otherwise a temporary JPEG copy is produced by
    stepping quality down and then scale, which keeps the face detail that the
    search actually depends on.

    Returns ``(path, is_temporary)``.
    """
    path = Path(path)
    if not path.exists():
        raise SearchError(f"Image not found: {path}")

    within_size = path.stat().st_size <= max_bytes
    supported = path.suffix.lower() in SUPPORTED_UPLOAD_SUFFIXES
    if within_size and supported:
        return path, False

    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise SearchError(f"Could not decode {path} for upload")

    tmp = Path(tempfile.mkstemp(prefix="hhgoa_lens_", suffix=".jpg")[1])

    for scale in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3):
        resized = image
        if scale < 1.0:
            height, width = image.shape[:2]
            resized = cv2.resize(
                image,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        for quality in (92, 85, 75, 65, 55):
            cv2.imwrite(str(tmp), resized, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if tmp.stat().st_size <= max_bytes:
                return tmp, True

    tmp.unlink(missing_ok=True)
    raise SearchError(
        f"Could not compress {path.name} below {max_bytes // 1024} KB for upload"
    )


class SerpApiLensClient:
    """Thin, well-behaved wrapper around ``serpapi.Client`` for Google Lens."""

    def __init__(
        self,
        api_key: str | None,
        timeout: int = 60,
        country: str = "us",
        language: str = "en",
    ) -> None:
        if not api_key:
            raise SearchError(
                "SERPAPI_API_KEY is not set. Copy .env.example to .env and add your "
                "key from https://serpapi.com/manage-api-key"
            )
        self.api_key = api_key
        self.timeout = timeout
        self.country = country
        self.language = language
        self._client = serpapi.Client(api_key=api_key, timeout=timeout)

    # -- account -----------------------------------------------------------

    def account_info(self) -> dict[str, Any] | None:
        """Best-effort quota lookup; never fatal."""
        try:
            return self._client.account()
        except Exception:  # noqa: BLE001 - purely informational
            return None

    # -- search ------------------------------------------------------------

    def upload(self, image_path: str | Path) -> str:
        """Upload a local image, returning SerpApi's temporary ``image_id``."""
        try:
            response = self._client.upload_image(str(image_path))
        except serpapi.HTTPError as exc:
            raise SearchError(self._explain_http_error(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - network/timeout/etc.
            raise SearchError(f"Image upload to SerpApi failed: {exc}") from exc

        image_id = (response or {}).get("image_id")
        if not image_id:
            raise SearchError(f"SerpApi did not return an image_id (got: {response})")
        return image_id

    def lens_search(self, image_id: str, search_type: str = "all") -> dict[str, Any]:
        """Run one Google Lens query against an uploaded image."""
        params = {
            "engine": "google_lens",
            "image_id": image_id,
            "type": search_type,
            "hl": self.language,
            "country": self.country,
            "no_cache": "true",
        }
        try:
            results = self._client.search(params)
        except serpapi.HTTPError as exc:
            raise SearchError(self._explain_http_error(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - network/timeout/etc.
            raise SearchError(f"Google Lens search failed: {exc}") from exc

        payload = dict(results)
        if payload.get("error"):
            raise SearchError(f"SerpApi returned an error: {payload['error']}")
        return payload

    def search_local_image(
        self,
        image_path: str | Path,
        include_exact_matches: bool = True,
    ) -> LensSearchResult:
        """Upload a local image and collect Google Lens results for it.

        ``all`` is always fetched (it carries ``visual_matches``). When
        ``include_exact_matches`` is set, a second query for pages hosting the
        very same image is merged in — those are the strongest evidence, at the
        cost of one extra API credit.
        """
        upload_path, is_temp = prepare_upload_copy(image_path)
        try:
            image_id = self.upload(upload_path)
        finally:
            if is_temp:
                Path(upload_path).unlink(missing_ok=True)

        payload = self.lens_search(image_id, search_type="all")
        types = ["all"]

        if include_exact_matches:
            try:
                exact = self.lens_search(image_id, search_type="exact_matches")
            except SearchError:
                # A failed secondary query must not sink a good primary result.
                exact = None
            if exact:
                merged = exact.get("exact_matches") or []
                if merged:
                    payload["exact_matches"] = merged
                    types.append("exact_matches")

        return LensSearchResult(payload=payload, image_id=image_id, search_types=types)

    # -- errors ------------------------------------------------------------

    @staticmethod
    def _explain_http_error(exc: "serpapi.HTTPError") -> str:
        status = getattr(exc, "status_code", None)
        detail = getattr(exc, "error", None) or str(exc)
        if status == 401:
            return f"SerpApi rejected the API key (401). {detail}"
        if status == 429:
            return (
                "SerpApi quota exhausted or rate limited (429). Check your plan at "
                f"https://serpapi.com/dashboard — {detail}"
            )
        if status == 400:
            return f"SerpApi rejected the request (400). {detail}"
        return f"SerpApi request failed (HTTP {status}). {detail}"
