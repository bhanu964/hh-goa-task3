"""Turn candidate pages into face-verified evidence.

For each candidate the selector downloads the image, runs InsightFace on it,
and scores it against the input embedding. A candidate is only ever accepted
because of that cosine similarity — never because the search engine returned
it. Candidates that fail are kept in the report so the run is auditable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable

import cv2
import numpy as np
import requests

from face.detector import DetectedFace
from face.encoder import FaceEncoder
from face.matcher import FaceMatch, compare

from .result_parser import (
    PREFERENCE_WEB,
    TIER_WEB,
    Candidate,
    rank_candidates,
    resolve_preference,
)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Below this, a thumbnail is upscaled before detection — RetinaFace loses small
# faces otherwise, and Lens thumbnails are routinely only ~250 px wide.
MIN_DETECTION_EDGE = 320


@dataclass
class VerifiedCandidate:
    """A candidate that was actually fetched and face-checked."""

    candidate: Candidate
    match: FaceMatch
    image_sha256: str
    image_url_used: str
    image_bytes: int
    faces_found: int

    @property
    def is_match(self) -> bool:
        return self.match.is_match

    @property
    def similarity(self) -> float:
        return self.match.similarity

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "similarity": round(self.similarity, 6),
            "threshold": self.match.threshold,
            "is_match": self.is_match,
            "image_sha256": self.image_sha256,
            "image_url_used": self.image_url_used,
            "image_bytes": self.image_bytes,
            "faces_found": self.faces_found,
        }


@dataclass
class SelectionReport:
    """Everything the selector learned, including the rejections."""

    checked: list[VerifiedCandidate]
    best: VerifiedCandidate | None
    fetch_failures: int
    no_face: int

    @property
    def matches(self) -> list[VerifiedCandidate]:
        return [c for c in self.checked if c.is_match]


class CandidateSelector:
    """Downloads candidate images and verifies them against a reference face."""

    def __init__(
        self,
        encoder: FaceEncoder,
        threshold: float,
        download_timeout: int = 20,
        max_download_bytes: int = 12_000_000,
        max_checks: int = 12,
        prefer_platform: str | None = None,
    ) -> None:
        self.encoder = encoder
        self.threshold = threshold
        self.prefer_platform = prefer_platform
        self.download_timeout = download_timeout
        self.max_download_bytes = max_download_bytes
        self.max_checks = max_checks
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": BROWSER_UA})

    # -- image fetching ----------------------------------------------------

    def _download(self, url: str) -> bytes | None:
        """Fetch a URL, returning bytes only if they decode as an image.

        Social platforms commonly answer their own ``image`` link with an HTML
        page for non-crawler clients, so the decode check — not the HTTP
        status — is what decides whether this succeeded.
        """
        try:
            response = self.session.get(url, timeout=self.download_timeout, stream=True)
            if response.status_code != 200:
                return None

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(65536):
                chunks.append(chunk)
                total += len(chunk)
                if total > self.max_download_bytes:
                    return None
            data = b"".join(chunks)
        except requests.RequestException:
            return None

        if cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) is None:
            return None
        return data

    def fetch_candidate_image(self, candidate: Candidate) -> tuple[bytes, str] | None:
        """Try the full image, then the thumbnail. None if neither works."""
        for url in (candidate.image_url, candidate.thumbnail_url):
            if not url:
                continue
            data = self._download(url)
            if data:
                return data, url
        return None

    # -- verification ------------------------------------------------------

    def _encode_candidate(self, data: bytes) -> tuple[DetectedFace | None, int]:
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None, 0

        height, width = image.shape[:2]
        if max(height, width) < MIN_DETECTION_EDGE:
            scale = 640 / max(height, width)
            image = cv2.resize(
                image,
                (int(width * scale), int(height * scale)),
                interpolation=cv2.INTER_CUBIC,
            )

        faces = self.encoder.detector.detect(image)
        return (faces[0] if faces else None), len(faces)

    def verify_candidates(
        self,
        candidates: list[Candidate],
        reference: np.ndarray,
        on_progress: Callable[[Candidate, VerifiedCandidate | None, str], None] | None = None,
    ) -> SelectionReport:
        """Check candidates in rank order until the budget is spent.

        ``on_progress`` is called once per candidate with the outcome so the
        CLI can narrate the search live.
        """
        checked: list[VerifiedCandidate] = []
        fetch_failures = 0
        no_face = 0

        for candidate in rank_candidates(candidates)[: self.max_checks]:
            fetched = self.fetch_candidate_image(candidate)
            if fetched is None:
                fetch_failures += 1
                if on_progress:
                    on_progress(candidate, None, "image unavailable")
                continue

            data, url_used = fetched
            face, faces_found = self._encode_candidate(data)
            if face is None:
                no_face += 1
                if on_progress:
                    on_progress(candidate, None, "no face in image")
                continue

            verified = VerifiedCandidate(
                candidate=candidate,
                match=compare(reference, face.embedding, self.threshold),
                image_sha256=hashlib.sha256(data).hexdigest(),
                image_url_used=url_used,
                image_bytes=len(data),
                faces_found=faces_found,
            )
            checked.append(verified)
            if on_progress:
                on_progress(candidate, verified, "match" if verified.is_match else "below threshold")

        return SelectionReport(
            checked=checked,
            best=self.select_best(checked, self.prefer_platform),
            fetch_failures=fetch_failures,
            no_face=no_face,
        )

    @staticmethod
    def matches_preference(candidate: Candidate, preference: str | None) -> bool:
        """Whether a candidate satisfies a resolved platform preference.

        ``PREFERENCE_WEB`` matches any Web-tier page rather than one named
        site, so ``--prefer-platform web`` covers news, blogs and institutional
        pages alike.
        """
        if not preference:
            return False
        if preference == PREFERENCE_WEB:
            return candidate.tier == TIER_WEB
        return candidate.platform.lower() == preference.lower()

    @staticmethod
    def select_best(
        checked: list[VerifiedCandidate],
        prefer_platform: str | None = None,
    ) -> VerifiedCandidate | None:
        """Pick the strongest verified candidate, or None if none passed.

        Ordering, in priority order:

        1. ``prefer_platform``, when given and something from it passed.
           Accepts aliases — ``X``, ``Twitter`` and ``X (Twitter)`` are the
           same request, and ``Web`` matches any Web-tier article.
        2. Platform tier — X (Twitter), then Web articles, then other social
           platforms, then low-signal sources. See
           :func:`search.result_parser.platform_tier`.
        3. Similarity.

        All of this only *orders candidates that already passed the face
        check*. Nothing here can turn a non-matching page into a match: if no
        candidate clears the threshold, this returns ``None`` regardless of
        platform preference.
        """
        passing = [c for c in checked if c.is_match]
        if not passing:
            return None

        preference = resolve_preference(prefer_platform)

        def sort_key(item: VerifiedCandidate):
            preferred = CandidateSelector.matches_preference(item.candidate, preference)
            return (not preferred, item.candidate.tier, -item.similarity)

        return min(passing, key=sort_key)
