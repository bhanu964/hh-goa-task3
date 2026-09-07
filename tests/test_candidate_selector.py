"""Candidate selection policy: evidence decides, never search rank."""

from unittest.mock import Mock

import pytest

from face.matcher import FaceMatch
from search.candidate_selector import CandidateSelector, VerifiedCandidate
from search.result_parser import Candidate


def candidate(link, platform, is_social, position=1, section="visual_matches"):
    return Candidate(
        position=position,
        title="t",
        link=link,
        source=platform,
        platform=platform,
        is_social=is_social,
        section=section,
        image_url=None,
        thumbnail_url="https://t/x.jpg",
    )


def verified(link, platform, is_social, similarity, threshold=0.45):
    return VerifiedCandidate(
        candidate=candidate(link, platform, is_social),
        match=FaceMatch(similarity=similarity, threshold=threshold),
        image_sha256="ab" * 32,
        image_url_used="https://t/x.jpg",
        image_bytes=1234,
        faces_found=1,
    )


def test_nothing_is_selected_when_no_candidate_passes():
    checked = [
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.20),
        verified("https://x.com/a/status/1", "X (Twitter)", True, 0.44),
    ]
    assert CandidateSelector.select_best(checked) is None


def test_empty_input_selects_nothing():
    assert CandidateSelector.select_best([]) is None


def test_a_high_ranked_result_that_fails_the_face_check_is_not_selected():
    """The whole point: search rank alone never makes something a match."""
    checked = [
        verified("https://www.instagram.com/p/FIRST/", "Instagram", True, 0.10),
        verified("https://www.facebook.com/x/posts/2/", "Facebook", True, 0.80),
    ]
    assert CandidateSelector.select_best(checked).candidate.link.endswith("/posts/2/")


def test_fetch_falls_back_from_full_image_to_thumbnail():
    selector = CandidateSelector(encoder=Mock(), threshold=0.45)
    selector._download = Mock(side_effect=[None, b"thumbnail-bytes"])

    target = Candidate(
        position=1, title="t", link="https://www.instagram.com/p/A/", source="Instagram",
        platform="Instagram", is_social=True, section="visual_matches",
        image_url="https://lookaside.fbsbx.com/x", thumbnail_url="https://tbn/x.jpg",
    )
    data, url = selector.fetch_candidate_image(target)
    assert data == b"thumbnail-bytes"
    assert url == "https://tbn/x.jpg"


def test_fetch_returns_none_when_every_url_fails():
    selector = CandidateSelector(encoder=Mock(), threshold=0.45)
    selector._download = Mock(return_value=None)
    target = candidate("https://www.instagram.com/p/A/", "Instagram", True)
    assert selector.fetch_candidate_image(target) is None


def test_candidates_without_any_image_url_are_not_fetched():
    selector = CandidateSelector(encoder=Mock(), threshold=0.45)
    selector._download = Mock()
    target = Candidate(
        position=1, title="t", link="https://example.com/a", source="s", platform="example.com",
        is_social=False, section="visual_matches", image_url=None, thumbnail_url=None,
    )
    assert selector.fetch_candidate_image(target) is None
    selector._download.assert_not_called()


def test_verified_candidate_serialises_its_evidence():
    payload = verified("https://www.instagram.com/p/A/", "Instagram", True, 0.77).to_dict()
    assert payload["is_match"] is True
    assert payload["similarity"] == 0.77
    assert payload["threshold"] == 0.45
    assert payload["candidate"]["platform"] == "Instagram"


def test_x_outranks_every_other_platform():
    """X (Twitter) is the designated social target and wins on tier alone."""
    checked = [
        verified("https://www.facebook.com/a/posts/1/", "Facebook", True, 0.95),
        verified("https://news.example.com/a", "news.example.com", False, 0.93),
        verified("https://x.com/a/status/1", "X (Twitter)", True, 0.58),
    ]
    assert CandidateSelector.select_best(checked).candidate.platform == "X (Twitter)"


def test_web_article_wins_when_no_x_post_passes():
    """Web results are first-class evidence, not a last resort."""
    checked = [
        verified("https://www.facebook.com/a/posts/1/", "Facebook", True, 0.91),
        verified("https://news.example.com/story", "news.example.com", False, 0.72),
    ]
    best = CandidateSelector.select_best(checked)
    assert best.candidate.platform == "news.example.com"


def test_web_article_outranks_instagram():
    checked = [
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.94),
        verified("https://news.example.com/story", "news.example.com", False, 0.61),
    ]
    assert CandidateSelector.select_best(checked).candidate.platform == "news.example.com"


def test_instagram_is_deprioritised_below_other_social():
    checked = [
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.96),
        verified("https://www.linkedin.com/in/a", "LinkedIn", True, 0.55),
    ]
    assert CandidateSelector.select_best(checked).candidate.platform == "LinkedIn"


def test_merchandise_listings_never_outrank_an_article():
    """A poster shop hosting the photo is not evidence of web presence."""
    checked = [
        verified("https://www.amazon.com/clp/B01", "amazon.com", False, 0.99),
        verified("https://news.example.com/story", "news.example.com", False, 0.55),
    ]
    assert CandidateSelector.select_best(checked).candidate.platform == "news.example.com"


def test_similarity_decides_between_two_web_articles():
    checked = [
        verified("https://news.example.com/a", "news.example.com", False, 0.61),
        verified("https://blog.example.org/b", "blog.example.org", False, 0.88),
    ]
    assert CandidateSelector.select_best(checked).similarity == 0.88


def test_low_signal_source_is_still_selected_when_nothing_better_passes():
    checked = [
        verified("https://news.example.com/a", "news.example.com", False, 0.12),
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.87),
    ]
    assert CandidateSelector.select_best(checked).candidate.platform == "Instagram"


def test_full_tier_order_is_x_then_web_then_social_then_low_signal():
    checked = [
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.99),
        verified("https://www.facebook.com/a/posts/1/", "Facebook", True, 0.97),
        verified("https://news.example.com/a", "news.example.com", False, 0.95),
        verified("https://x.com/a/status/1", "X (Twitter)", True, 0.50),
    ]
    order = []
    remaining = list(checked)
    while remaining:
        best = CandidateSelector.select_best(remaining)
        order.append(best.candidate.platform)
        remaining.remove(best)
    assert order == ["X (Twitter)", "news.example.com", "Facebook", "Instagram"]


# --- --prefer-platform ------------------------------------------------------


def test_preferred_platform_wins_over_a_higher_score():
    checked = [
        verified("https://news.example.com/a", "news.example.com", False, 0.90),
        verified("https://www.facebook.com/a/posts/1/", "Facebook", True, 0.66),
    ]
    best = CandidateSelector.select_best(checked, prefer_platform="Facebook")
    assert best.candidate.platform == "Facebook"


@pytest.mark.parametrize("alias", ["X", "x", "Twitter", "twitter", "X (Twitter)", "x.com"])
def test_x_aliases_all_resolve_to_the_same_platform(alias):
    checked = [
        verified("https://news.example.com/a", "news.example.com", False, 0.95),
        verified("https://x.com/a/status/1", "X (Twitter)", True, 0.52),
    ]
    best = CandidateSelector.select_best(checked, prefer_platform=alias)
    assert best.candidate.platform == "X (Twitter)"


@pytest.mark.parametrize("alias", ["Web", "web", "news", "article", "Web Search"])
def test_web_aliases_select_any_web_tier_article(alias):
    checked = [
        verified("https://x.com/a/status/1", "X (Twitter)", True, 0.95),
        verified("https://news.example.com/a", "news.example.com", False, 0.55),
    ]
    best = CandidateSelector.select_best(checked, prefer_platform=alias)
    assert best.candidate.platform == "news.example.com"


def test_web_preference_does_not_match_a_merchandise_page():
    """amazon.com is low-signal, so "web" must not select it over an article."""
    checked = [
        verified("https://www.amazon.com/clp/B01", "amazon.com", False, 0.99),
        verified("https://news.example.com/a", "news.example.com", False, 0.51),
    ]
    best = CandidateSelector.select_best(checked, prefer_platform="web")
    assert best.candidate.platform == "news.example.com"


def test_an_exact_domain_can_be_preferred():
    checked = [
        verified("https://x.com/a/status/1", "X (Twitter)", True, 0.95),
        verified("https://bbc.co.uk/news/1", "bbc.co.uk", False, 0.55),
    ]
    best = CandidateSelector.select_best(checked, prefer_platform="bbc.co.uk")
    assert best.candidate.platform == "bbc.co.uk"


def test_preference_falls_back_when_that_platform_has_no_passing_match():
    checked = [
        verified("https://news.example.com/a", "news.example.com", False, 0.90),
        verified("https://x.com/a/status/1", "X (Twitter)", True, 0.11),
    ]
    best = CandidateSelector.select_best(checked, prefer_platform="X")
    assert best.candidate.platform == "news.example.com"


def test_preference_cannot_promote_a_failing_candidate():
    """The preference reorders verified matches; it never creates one."""
    checked = [verified("https://x.com/a/status/1", "X (Twitter)", True, 0.10)]
    assert CandidateSelector.select_best(checked, prefer_platform="X") is None


def test_unknown_preference_is_ignored_rather_than_crashing():
    checked = [verified("https://x.com/a/status/1", "X (Twitter)", True, 0.80)]
    best = CandidateSelector.select_best(checked, prefer_platform="MySpace")
    assert best.candidate.platform == "X (Twitter)"


def test_blank_preference_is_treated_as_no_preference():
    checked = [
        verified("https://news.example.com/a", "news.example.com", False, 0.90),
        verified("https://x.com/a/status/1", "X (Twitter)", True, 0.55),
    ]
    assert CandidateSelector.select_best(checked, "   ").candidate.platform == "X (Twitter)"
