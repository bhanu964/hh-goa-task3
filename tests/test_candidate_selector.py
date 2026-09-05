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
