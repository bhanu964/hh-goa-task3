"""Parsing, platform tagging and filtering of Google Lens results."""

import pytest

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


def test_the_target_platform_is_ranked_before_other_sites():
    payload = {
        "visual_matches": [
            entry(1, "https://news.example.com/a"),
            entry(2, "https://x.com/a/status/1"),
        ]
    }
    ranked = rank_candidates(parse_lens_response(payload))
    assert ranked[0].platform == "X (Twitter)"


def test_ranking_does_not_drop_candidates():
    payload = {
        "visual_matches": [entry(i, f"https://example.com/{i}") for i in range(1, 6)]
    }
    parsed = parse_lens_response(payload)
    assert len(rank_candidates(parsed)) == len(parsed)


def test_x_is_the_top_tier_platform():
    from search.result_parser import TIER_TARGET_SOCIAL, platform_tier

    assert platform_tier("X (Twitter)", True) == TIER_TARGET_SOCIAL


def test_web_pages_sit_in_the_active_web_tier():
    from search.result_parser import TIER_WEB, platform_tier

    for domain in ("bbc.co.uk", "nytimes.com", "someuniversity.edu", "blog.example.org"):
        assert platform_tier(domain, False) == TIER_WEB


def test_other_social_platforms_rank_below_web():
    from search.result_parser import TIER_OTHER_SOCIAL, TIER_WEB, platform_tier

    for name in ("Facebook", "LinkedIn", "TikTok", "Threads"):
        assert platform_tier(name, True) == TIER_OTHER_SOCIAL
    assert TIER_WEB < TIER_OTHER_SOCIAL


def test_instagram_is_deprioritised_to_the_low_signal_tier():
    from search.result_parser import TIER_LOW_SIGNAL, platform_tier

    assert platform_tier("Instagram", True) == TIER_LOW_SIGNAL


def test_aggregators_and_video_sites_are_low_signal():
    from search.result_parser import TIER_LOW_SIGNAL, platform_tier

    for name in ("Reddit", "YouTube", "Pinterest"):
        assert platform_tier(name, True) == TIER_LOW_SIGNAL


def test_merchandise_and_stock_photo_hosts_are_low_signal():
    from search.result_parser import TIER_LOW_SIGNAL, platform_tier

    for domain in ("amazon.com", "ebay.com", "etsy.com", "alamy.com", "gettyimages.com"):
        assert platform_tier(domain, False) == TIER_LOW_SIGNAL


def test_tiers_are_strictly_ordered():
    from search.result_parser import (
        TIER_LOW_SIGNAL,
        TIER_OTHER_SOCIAL,
        TIER_TARGET_SOCIAL,
        TIER_WEB,
    )

    assert TIER_TARGET_SOCIAL < TIER_WEB < TIER_OTHER_SOCIAL < TIER_LOW_SIGNAL


def test_x_is_inspected_before_a_web_article():
    payload = {
        "visual_matches": [
            entry(1, "https://news.example.com/a"),
            entry(2, "https://x.com/a/status/1"),
        ]
    }
    ranked = rank_candidates(parse_lens_response(payload))
    assert ranked[0].platform == "X (Twitter)"


def test_a_web_article_is_inspected_before_instagram():
    payload = {
        "visual_matches": [
            entry(1, "https://www.instagram.com/p/ABC/"),
            entry(2, "https://news.example.com/a"),
        ]
    }
    ranked = rank_candidates(parse_lens_response(payload))
    assert ranked[0].platform == "news.example.com"


# --- preference resolution --------------------------------------------------


@pytest.mark.parametrize(
    "text", ["X", "x", "  x  ", "Twitter", "twitter.com", "X (Twitter)", "x.com", "tweet"]
)
def test_x_aliases_resolve_to_the_canonical_name(text):
    from search.result_parser import resolve_preference

    assert resolve_preference(text) == "X (Twitter)"


@pytest.mark.parametrize(
    "text", ["web", "Web", "WEB SEARCH", "news", "article", "articles", "blog", "website"]
)
def test_web_aliases_resolve_to_the_web_sentinel(text):
    from search.result_parser import PREFERENCE_WEB, resolve_preference

    assert resolve_preference(text) == PREFERENCE_WEB


@pytest.mark.parametrize("text", [None, "", "   "])
def test_blank_preference_resolves_to_none(text):
    from search.result_parser import resolve_preference

    assert resolve_preference(text) is None


def test_unrecognised_preference_passes_through_for_exact_matching():
    from search.result_parser import resolve_preference

    assert resolve_preference("bbc.co.uk") == "bbc.co.uk"


def test_preference_description_is_readable():
    from search.result_parser import PREFERENCE_WEB, describe_preference

    assert describe_preference(PREFERENCE_WEB) == "Web results"
    assert describe_preference("X (Twitter)") == "X (Twitter)"
    assert describe_preference(None) == "none"


# --- de-duplication ---------------------------------------------------------


def test_tracking_and_locale_params_are_stripped_for_dedup():
    from search.result_parser import normalise_link

    base = "https://x.com/a/status/123"
    for variant in (
        "https://x.com/a/status/123?lang=en",
        "https://www.x.com/a/status/123",
        "https://x.com/a/status/123/",
        "https://x.com/a/status/123#anchor",
        "https://x.com/a/status/123?utm_source=google&ref_src=twsrc",
    ):
        assert normalise_link(variant) == normalise_link(base)


def test_meaningful_query_params_are_kept():
    from search.result_parser import normalise_link

    assert normalise_link("https://e.com/p?id=7") != normalise_link("https://e.com/p?id=8")


def test_the_same_post_with_a_lang_param_is_collapsed():
    payload = {
        "visual_matches": [
            entry(1, "https://x.com/a/status/123", image="https://i/1.jpg"),
            entry(2, "https://x.com/a/status/123?lang=en", image="https://i/1.jpg"),
        ]
    }
    assert len(parse_lens_response(payload)) == 1


def test_pages_sharing_one_thumbnail_are_collapsed():
    """Re-checking an identical image cannot produce new evidence."""
    payload = {
        "visual_matches": [
            entry(1, "https://news.example.com/a", thumbnail="https://tbn/same.jpg"),
            entry(2, "https://news.example.com/b", thumbnail="https://tbn/same.jpg"),
            entry(3, "https://news.example.com/c", thumbnail="https://tbn/same.jpg"),
        ]
    }
    candidates = parse_lens_response(payload)
    assert len(candidates) == 1
    assert candidates[0].link == "https://news.example.com/a"


def test_the_highest_ranked_page_survives_image_dedup():
    payload = {
        "exact_matches": [entry(1, "https://news.example.com/exact", thumbnail="https://t/x.jpg")],
        "visual_matches": [entry(1, "https://news.example.com/visual", thumbnail="https://t/x.jpg")],
    }
    assert parse_lens_response(payload)[0].link.endswith("/exact")


def test_distinct_images_are_all_kept():
    payload = {
        "visual_matches": [
            entry(1, "https://news.example.com/a", thumbnail="https://tbn/1.jpg"),
            entry(2, "https://news.example.com/b", thumbnail="https://tbn/2.jpg"),
        ]
    }
    assert len(parse_lens_response(payload)) == 2


def test_candidates_without_images_are_not_collapsed_together():
    payload = {
        "visual_matches": [
            entry(1, "https://news.example.com/a"),
            entry(2, "https://news.example.com/b"),
        ]
    }
    assert len(parse_lens_response(payload)) == 2


def test_malformed_url_does_not_break_normalisation():
    from search.result_parser import normalise_link

    assert normalise_link("http://[bad") == "http://[bad"


# --- domain matching must respect boundaries --------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.peakpx.com/en/hd-wallpaper",
        "https://www.netflix.com/title/1",
        "https://www.vox.com/article",
        "https://www.dropbox.com/s/abc",
        "https://www.xbox.com/games",
        "https://notx.com/page",
        "https://myinstagram-fan.com/p",
        "https://facebook-clone.net/post",
    ],
)
def test_lookalike_domains_are_not_mistaken_for_social_platforms(url):
    """Substring matching reported netflix.com and peakpx.com as X posts."""
    platform, is_social = platform_for_url(url)
    assert not is_social
    assert platform != "X (Twitter)"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/user/status/1", "X (Twitter)"),
        ("https://www.x.com/user", "X (Twitter)"),
        ("https://twitter.com/user", "X (Twitter)"),
        ("https://mobile.twitter.com/user", "X (Twitter)"),
        ("https://www.instagram.com/p/A/", "Instagram"),
        ("https://m.facebook.com/x/posts/1", "Facebook"),
        ("https://uk.linkedin.com/in/someone", "LinkedIn"),
        ("https://old.reddit.com/r/x/1", "Reddit"),
    ],
)
def test_real_platform_domains_and_subdomains_are_recognised(url, expected):
    platform, is_social = platform_for_url(url)
    assert (platform, is_social) == (expected, True)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.pinterest.co.uk/pin/1", "Pinterest"),
        ("https://www.pinterest.fr/pin/1", "Pinterest"),
        ("https://mastodon.social/@someone", "Mastodon"),
        ("https://social.mastodon.xyz/@a", "Mastodon"),
    ],
)
def test_country_tld_platforms_match_on_a_whole_label(url, expected):
    assert platform_for_url(url)[0] == expected


def test_a_hyphenated_lookalike_is_not_a_country_tld_match():
    assert platform_for_url("https://pinterest-clone.com/x")[1] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://www.peakpx.com/wallpaper",
        "https://wallpaperflare.com/x",
        "https://www.amazon.com/dp/B01",
        "https://www.gettyimages.com/photo/1",
        "https://www.alamy.com/stock-photo",
    ],
)
def test_stock_and_wallpaper_hosts_are_low_signal(url):
    from search.result_parser import TIER_LOW_SIGNAL, platform_tier

    platform, is_social = platform_for_url(url)
    assert platform_tier(platform, is_social) == TIER_LOW_SIGNAL


def test_a_news_site_is_not_swept_into_low_signal():
    from search.result_parser import TIER_WEB, platform_tier

    platform, is_social = platform_for_url("https://www.theposterpost.com/story")
    assert platform_tier(platform, is_social) == TIER_WEB


def test_host_matches_helper_is_boundary_aware():
    from search.result_parser import host_matches

    assert host_matches("x.com", "x.com")
    assert host_matches("mobile.x.com", "x.com")
    assert not host_matches("peakpx.com", "x.com")
    assert not host_matches("notx.com", "x.com")
    assert not host_matches("", "x.com")


def test_port_and_userinfo_in_host_are_ignored():
    assert platform_for_url("https://user@x.com:443/a/status/1")[0] == "X (Twitter)"
