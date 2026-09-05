"""Genuine programmatic reverse-image search via SerpApi's Google Lens engine."""

from .serpapi_client import (
    LensSearchResult,
    SearchError,
    SerpApiLensClient,
    prepare_upload_copy,
)
from .result_parser import Candidate, parse_lens_response, platform_for_url
from .candidate_selector import CandidateSelector, VerifiedCandidate

__all__ = [
    "LensSearchResult",
    "SearchError",
    "SerpApiLensClient",
    "prepare_upload_copy",
    "Candidate",
    "parse_lens_response",
    "platform_for_url",
    "CandidateSelector",
    "VerifiedCandidate",
]
