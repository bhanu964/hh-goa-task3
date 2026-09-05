"""Candidate selection policy: evidence decides, never search rank."""

from unittest.mock import Mock

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


def test_highest_similarity_wins_among_social_results():
    checked = [
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.55),
        verified("https://www.facebook.com/b/posts/1/", "Facebook", True, 0.91),
        verified("https://x.com/c/status/1", "X (Twitter)", True, 0.62),
    ]
    assert CandidateSelector.select_best(checked).similarity == 0.91


def test_social_results_are_preferred_over_stronger_non_social_ones():
    checked = [
        verified("https://news.example.com/a", "news.example.com", False, 0.99),
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.60),
    ]
    best = CandidateSelector.select_best(checked)
    assert best.candidate.is_social and best.similarity == 0.60


def test_a_non_social_match_is_still_returned_when_nothing_social_passes():
    checked = [
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.10),
        verified("https://news.example.com/a", "news.example.com", False, 0.88),
    ]
    best = CandidateSelector.select_best(checked)
    assert best is not None and not best.candidate.is_social


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


def test_instagram_is_preferred_over_a_higher_scoring_reddit_result():
    """A personal post outranks an aggregator even on a lower score.

    Reddit serves full-resolution images while Instagram only exposes a ~250px
    thumbnail, so Reddit reliably scores higher. Tier ordering stops that
    resolution artefact from deciding what the pipeline reports.
    """
    checked = [
        verified("https://www.reddit.com/r/x/comments/1/", "Reddit", True, 0.98),
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.71),
    ]
    best = CandidateSelector.select_best(checked)
    assert best.candidate.platform == "Instagram"


def test_youtube_does_not_outrank_facebook():
    checked = [
        verified("https://www.youtube.com/watch?v=1", "YouTube", True, 0.95),
        verified("https://www.facebook.com/a/posts/1/", "Facebook", True, 0.66),
    ]
    assert CandidateSelector.select_best(checked).candidate.platform == "Facebook"


def test_similarity_still_decides_within_the_primary_tier():
    checked = [
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.61),
        verified("https://www.facebook.com/a/posts/1/", "Facebook", True, 0.88),
        verified("https://x.com/a/status/1", "X (Twitter)", True, 0.74),
    ]
    assert CandidateSelector.select_best(checked).similarity == 0.88


def test_reddit_is_still_selected_when_no_primary_social_passes():
    checked = [
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.20),
        verified("https://www.reddit.com/r/x/comments/1/", "Reddit", True, 0.91),
    ]
    assert CandidateSelector.select_best(checked).candidate.platform == "Reddit"


def test_tier_order_is_primary_then_other_social_then_the_rest():
    checked = [
        verified("https://news.example.com/a", "news.example.com", False, 0.99),
        verified("https://www.reddit.com/r/x/comments/1/", "Reddit", True, 0.97),
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.55),
    ]
    assert CandidateSelector.select_best(checked).candidate.platform == "Instagram"


def test_preferred_platform_wins_over_a_higher_score():
    checked = [
        verified("https://www.facebook.com/a/posts/1/", "Facebook", True, 0.90),
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.66),
    ]
    best = CandidateSelector.select_best(checked, prefer_platform="Instagram")
    assert best.candidate.platform == "Instagram"


def test_platform_preference_is_case_insensitive():
    checked = [
        verified("https://www.facebook.com/a/posts/1/", "Facebook", True, 0.90),
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.66),
    ]
    assert (
        CandidateSelector.select_best(checked, prefer_platform="instagram")
        .candidate.platform
        == "Instagram"
    )


def test_preference_falls_back_when_that_platform_has_no_passing_match():
    checked = [
        verified("https://www.facebook.com/a/posts/1/", "Facebook", True, 0.90),
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.11),
    ]
    best = CandidateSelector.select_best(checked, prefer_platform="Instagram")
    assert best.candidate.platform == "Facebook"


def test_preference_cannot_promote_a_failing_candidate():
    """The preference reorders verified matches; it never creates one."""
    checked = [verified("https://www.instagram.com/p/A/", "Instagram", True, 0.10)]
    assert CandidateSelector.select_best(checked, prefer_platform="Instagram") is None


def test_no_preference_keeps_the_default_tier_ordering():
    checked = [
        verified("https://www.reddit.com/r/x/comments/1/", "Reddit", True, 0.98),
        verified("https://www.instagram.com/p/A/", "Instagram", True, 0.71),
    ]
    assert CandidateSelector.select_best(checked, None).candidate.platform == "Instagram"
