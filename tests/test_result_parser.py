"""Parsing, platform tagging and filtering of Google Lens results."""

from search.result_parser import (
    is_excluded,
    parse_lens_response,
    platform_for_url,
    rank_candidates,
)


def entry(position, link, title="t", source="s", image=None, thumbnail=None):
    return {
        "position": position,
        "link": link,
        "title": title,
        "source": source,
        "image": image,
        "thumbnail": thumbnail,
    }


def test_known_social_domains_are_recognised():
    assert platform_for_url("https://www.instagram.com/p/ABC/") == ("Instagram", True)
    assert platform_for_url("https://x.com/user/status/1") == ("X (Twitter)", True)
    assert platform_for_url("https://www.facebook.com/x/posts/1") == ("Facebook", True)
    assert platform_for_url("https://uk.linkedin.com/in/someone") == ("LinkedIn", True)


def test_non_social_sites_fall_back_to_their_domain():
    assert platform_for_url("https://www.bbc.co.uk/news/1") == ("bbc.co.uk", False)


def test_empty_url_is_handled():
    assert platform_for_url("") == ("Unknown", False)


def test_search_engine_internals_are_excluded():
    assert is_excluded("https://www.google.com/goto?url=abc")
    assert is_excluded("https://encrypted-tbn0.gstatic.com/images?q=x")
    assert is_excluded("not-a-url")
    assert not is_excluded("https://www.instagram.com/p/ABC/")


def test_excluded_links_never_become_candidates():
    payload = {
        "visual_matches": [
            entry(1, "https://www.google.com/goto?url=abc"),
            entry(2, "https://www.instagram.com/p/ABC/"),
        ]
    }
    links = [c.link for c in parse_lens_response(payload)]
    assert links == ["https://www.instagram.com/p/ABC/"]


def test_duplicate_links_are_collapsed():
    payload = {
        "exact_matches": [entry(1, "https://example.com/a")],
        "visual_matches": [entry(1, "https://example.com/a"), entry(2, "https://example.com/b")],
    }
    assert len(parse_lens_response(payload)) == 2


def test_exact_matches_are_kept_ahead_of_visual_matches():
    payload = {
        "exact_matches": [entry(1, "https://example.com/exact")],
        "visual_matches": [entry(1, "https://example.com/visual")],
    }
    sections = [c.section for c in parse_lens_response(payload)]
    assert sections == ["exact_matches", "visual_matches"]


def test_missing_sections_are_tolerated():
    assert parse_lens_response({}) == []
    assert parse_lens_response({"visual_matches": None}) == []


def test_malformed_entries_are_skipped():
    payload = {"visual_matches": ["nonsense", None, entry(1, "https://example.com/a")]}
    assert len(parse_lens_response(payload)) == 1


def test_non_integer_position_does_not_crash():
    payload = {"visual_matches": [entry("odd", "https://example.com/a")]}
    assert parse_lens_response(payload)[0].position == 1


def test_thumbnail_is_the_fallback_when_no_full_image():
    payload = {"visual_matches": [entry(1, "https://example.com/a", thumbnail="https://t/1.jpg")]}
    assert parse_lens_response(payload)[0].best_image_url == "https://t/1.jpg"


def test_full_image_is_preferred_over_thumbnail():
    payload = {
        "visual_matches": [
            entry(1, "https://example.com/a", image="https://i/1.jpg", thumbnail="https://t/1.jpg")
        ]
    }
    assert parse_lens_response(payload)[0].best_image_url == "https://i/1.jpg"


def test_social_pages_are_ranked_before_other_sites():
    payload = {
        "visual_matches": [
            entry(1, "https://news.example.com/a"),
            entry(2, "https://www.instagram.com/p/ABC/"),
        ]
    }
    ranked = rank_candidates(parse_lens_response(payload))
    assert ranked[0].platform == "Instagram"


def test_ranking_does_not_drop_candidates():
    payload = {
        "visual_matches": [entry(i, f"https://example.com/{i}") for i in range(1, 6)]
    }
    parsed = parse_lens_response(payload)
    assert len(rank_candidates(parsed)) == len(parsed)
