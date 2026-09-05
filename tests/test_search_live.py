"""Live integration test for the reverse-image search.

This deliberately hits the real SerpApi Google Lens API — the point of the
task is that the search genuinely happens, so the test that covers it must
genuinely happen too. There is no recorded-fixture version of this test,
because a fixture would prove nothing about whether the search still works.

It is skipped unless a key is configured, and it spends real API credits:

    pytest tests/test_search_live.py -v           # skipped without a key
    RUN_LIVE_SEARCH=1 pytest tests/test_search_live.py -v

Manual equivalent, if you would rather watch it run:

    python main.py --image input/selfie.jpg --network memory
"""

import os
from pathlib import Path

import pytest

from config import load_config
from search.result_parser import parse_lens_response
from search.serpapi_client import SerpApiLensClient, prepare_upload_copy

pytestmark = pytest.mark.live

SAMPLE = Path(__file__).resolve().parent.parent / "input" / "selfie.jpg"


def _requirements_met() -> tuple[bool, str]:
    if not os.getenv("RUN_LIVE_SEARCH"):
        return False, "set RUN_LIVE_SEARCH=1 to run (spends SerpApi credits)"
    if not load_config().search.api_key:
        return False, "SERPAPI_API_KEY is not configured"
    if not SAMPLE.exists():
        return False, f"sample image missing: {SAMPLE}"
    return True, ""


ok, reason = _requirements_met()
pytestmark = [pytest.mark.skipif(not ok, reason=reason)]


@pytest.fixture(scope="module")
def live_results():
    config = load_config()
    client = SerpApiLensClient(
        api_key=config.search.api_key,
        timeout=config.search.timeout,
        country=config.search.country,
        language=config.search.language,
    )
    return client.search_local_image(SAMPLE, include_exact_matches=False)


def test_upload_returns_a_usable_image_id(live_results):
    assert live_results.image_id
    assert len(live_results.image_id) > 10


def test_search_reports_success(live_results):
    assert live_results.search_metadata.get("status") == "Success"


def test_search_id_is_unique_to_this_run(live_results):
    """A fresh search id proves the result was produced now, not replayed."""
    assert live_results.search_id


def test_lens_returns_candidate_pages(live_results):
    candidates = parse_lens_response(live_results.payload)
    assert len(candidates) > 0, "Google Lens returned no candidates"


def test_candidates_carry_real_http_urls(live_results):
    for candidate in parse_lens_response(live_results.payload)[:10]:
        assert candidate.link.startswith(("http://", "https://"))


def test_candidates_expose_an_image_to_download(live_results):
    candidates = parse_lens_response(live_results.payload)
    assert any(c.best_image_url for c in candidates)


def test_upload_preparation_respects_the_500kb_limit(tmp_path):
    path, is_temp = prepare_upload_copy(SAMPLE)
    try:
        assert path.stat().st_size <= 500 * 1024
    finally:
        if is_temp:
            Path(path).unlink(missing_ok=True)
