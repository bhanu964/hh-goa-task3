"""Normalise a raw Google Lens payload into ranked :class:`Candidate` records.

SerpApi returns several result arrays with the same broad shape. This module
flattens them into one list, tags each entry with the platform it came from,
and removes duplicates — without deciding anything about face identity. That
judgement belongs to :mod:`search.candidate_selector`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Result arrays worth mining, in descending order of evidential strength.
# ``exact_matches`` are pages hosting the very same image, so they come first.
RESULT_SECTIONS = ("exact_matches", "visual_matches", "organic_results")

# domain fragment -> human-readable platform name
SOCIAL_PLATFORMS: dict[str, str] = {
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "fb.com": "Facebook",
    "fb.watch": "Facebook",
    "twitter.com": "X (Twitter)",
    "x.com": "X (Twitter)",
    "linkedin.com": "LinkedIn",
    "pinterest.": "Pinterest",
    "reddit.com": "Reddit",
    "redd.it": "Reddit",
    "tiktok.com": "TikTok",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "threads.net": "Threads",
    "threads.com": "Threads",
    "tumblr.com": "Tumblr",
    "flickr.com": "Flickr",
    "vk.com": "VK",
    "weibo.com": "Weibo",
    "bsky.app": "Bluesky",
    "mastodon.": "Mastodon",
    "snapchat.com": "Snapchat",
}

# Search-engine plumbing rather than discoverable pages: redirect hops, cached
# copies and image CDNs. They are not evidence and must never be anchored.
EXCLUDED_HOSTS = (
    "google.com/goto",
    "google.com/url",
    "googleusercontent.com",
    "gstatic.com",
    "googleapis.com",
    "webcache.googleusercontent.com",
    "translate.google.",
)


#: Locale, tracking and share parameters that do not change the page. Stripping
#: them collapses ``…/status/123`` and ``…/status/123?lang=en`` into one result.
TRACKING_PARAMS = {
    "lang", "ref", "ref_src", "ref_url", "referrer", "s", "t",
    "fbclid", "igshid", "gclid", "mc_cid", "mc_eid", "spm", "share_id",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
}


def normalise_link(url: str) -> str:
    """Canonical form of a page URL, for de-duplication only.

    Lowercases the host, drops ``www.``, the fragment and tracking/locale
    parameters, and normalises the trailing slash. The original URL is what
    gets stored in the evidence record — this form is never shown or hashed.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    host = parsed.netloc.lower()
    host = host[4:] if host.startswith("www.") else host

    query = sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    )

    return urlunparse(
        (parsed.scheme.lower(), host, parsed.path.rstrip("/") or "/", "", urlencode(query), "")
    )


def is_excluded(url: str) -> bool:
    """True for search-engine internals that aren't real result pages."""
    lowered = (url or "").lower()
    if not lowered.startswith(("http://", "https://")):
        return True
    return any(fragment in lowered for fragment in EXCLUDED_HOSTS)


# Selection priority.
#
# Tier 0 — X (Twitter): the designated social-media target for this pipeline.
# Tier 1 — Web: news articles, interviews, institutional and personal sites.
#          These are first-class evidence: they serve full-resolution images
#          and their pages carry real context about the person.
# Tier 2 — other social platforms.
# Tier 3 — low-signal sources. Instagram sits here because it exposes only a
#          ~250 px crawler thumbnail to non-Instagram clients, and its Lens
#          hits are frequently reels or aggregator reposts rather than a clear
#          face image. Aggregators, video sites and merchandise listings share
#          the tier for the same reason: the page is not evidence of the
#          person's own presence on the web.
TIER_TARGET_SOCIAL = 0
TIER_WEB = 1
TIER_OTHER_SOCIAL = 2
TIER_LOW_SIGNAL = 3

TIER_NAMES = {
    TIER_TARGET_SOCIAL: "X (Twitter)",
    TIER_WEB: "Web",
    TIER_OTHER_SOCIAL: "other social",
    TIER_LOW_SIGNAL: "low signal",
}

#: The social platform this pipeline targets.
TARGET_SOCIAL = {"X (Twitter)"}

#: Social, but not the target platform.
OTHER_SOCIAL = {
    "Facebook",
    "LinkedIn",
    "TikTok",
    "Threads",
    "Snapchat",
    "Bluesky",
    "Mastodon",
    "VK",
    "Weibo",
}

#: Social platforms that reliably yield poor evidence — see the tier comment.
LOW_SIGNAL_SOCIAL = {"Instagram", "Reddit", "YouTube", "Pinterest", "Tumblr", "Flickr"}

#: Merchandise, stock-photo and print-on-demand hosts. The image is often a
#: genuine photo of the person, but a product listing is not evidence of their
#: presence on the web, so these never outrank an article.
LOW_SIGNAL_DOMAINS = (
    "amazon.",
    "ebay.",
    "etsy.",
    "alamy.",
    "gettyimages.",
    "shutterstock.",
    "istockphoto.",
    "dreamstime.",
    "posterlounge.",
    "fineartamerica.",
    "redbubble.",
    "zazzle.",
    "walmart.",
    "aliexpress.",
    "pixels.com",
    "poster",
    "printerval.",
)


def platform_tier(platform: str, is_social: bool) -> int:
    """Rank a platform for selection purposes. Lower wins."""
    if platform in TARGET_SOCIAL:
        return TIER_TARGET_SOCIAL

    if is_social:
        return TIER_LOW_SIGNAL if platform in LOW_SIGNAL_SOCIAL else TIER_OTHER_SOCIAL

    # Non-social: the platform label is the bare domain.
    lowered = platform.lower()
    if any(fragment in lowered for fragment in LOW_SIGNAL_DOMAINS):
        return TIER_LOW_SIGNAL
    return TIER_WEB


# --- --prefer-platform resolution -------------------------------------------

#: Sentinel meaning "any Web-tier result", rather than one named platform.
PREFERENCE_WEB = "__web__"

#: Spellings a user might reasonably type for a platform.
PLATFORM_ALIASES = {
    "x": "X (Twitter)",
    "x.com": "X (Twitter)",
    "twitter": "X (Twitter)",
    "twitter.com": "X (Twitter)",
    "x (twitter)": "X (Twitter)",
    "tweet": "X (Twitter)",
    "fb": "Facebook",
    "facebook": "Facebook",
    "ig": "Instagram",
    "insta": "Instagram",
    "instagram": "Instagram",
    "li": "LinkedIn",
    "linkedin": "LinkedIn",
    "tiktok": "TikTok",
    "threads": "Threads",
    "reddit": "Reddit",
    "yt": "YouTube",
    "youtube": "YouTube",
    "pinterest": "Pinterest",
    "bluesky": "Bluesky",
    "mastodon": "Mastodon",
}

#: Spellings that mean "a Web-tier page" rather than a specific site.
WEB_ALIASES = {
    "web",
    "web search",
    "websearch",
    "website",
    "site",
    "news",
    "article",
    "articles",
    "blog",
    "blogs",
}


def resolve_preference(text: str | None) -> str | None:
    """Normalise a ``--prefer-platform`` value.

    Returns a canonical platform name, the :data:`PREFERENCE_WEB` sentinel, or
    ``None``. An unrecognised value is passed through so it can still match a
    platform label exactly (e.g. a bare domain like ``bbc.co.uk``).
    """
    if not text or not text.strip():
        return None

    key = " ".join(text.strip().lower().split())
    if key in WEB_ALIASES:
        return PREFERENCE_WEB
    return PLATFORM_ALIASES.get(key, text.strip())


def describe_preference(preference: str | None) -> str:
    """Human-readable form of a resolved preference, for terminal output."""
    if preference is None:
        return "none"
    return "Web results" if preference == PREFERENCE_WEB else preference


def platform_for_url(url: str) -> tuple[str, bool]:
    """Map a URL to ``(platform_name, is_social_media)``.

    Non-social sites fall back to their bare domain, so a news page still gets
    a meaningful label in the evidence record.
    """
    if not url:
        return "Unknown", False

    host = (urlparse(url).netloc or "").lower()
    host = host[4:] if host.startswith("www.") else host

    for fragment, name in SOCIAL_PLATFORMS.items():
        if fragment in host:
            return name, True

    return host or "Unknown", False


@dataclass(frozen=True)
class Candidate:
    """One page discovered by the reverse-image search."""

    position: int
    title: str
    link: str
    source: str
    platform: str
    is_social: bool
    section: str
    image_url: str | None = None
    thumbnail_url: str | None = None

    @property
    def tier(self) -> int:
        """Selection priority — lower wins. See :func:`platform_tier`."""
        return platform_tier(self.platform, self.is_social)

    @property
    def best_image_url(self) -> str | None:
        """Full image first; the thumbnail is the fallback.

        Social platforms often serve their ``image`` link only to their own
        crawler and hand everyone else an HTML page, in which case the
        Google-hosted thumbnail is what actually downloads.
        """
        return self.image_url or self.thumbnail_url

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "title": self.title,
            "link": self.link,
            "source": self.source,
            "platform": self.platform,
            "is_social": self.is_social,
            "tier": self.tier,
            "section": self.section,
            "image_url": self.image_url,
            "thumbnail_url": self.thumbnail_url,
        }


def _clean(value: Any) -> str:
    return " ".join(str(value).split()) if value else ""


def _entries(payload: dict[str, Any], section: str) -> Iterable[dict[str, Any]]:
    items = payload.get(section)
    return items if isinstance(items, list) else []


def parse_lens_response(payload: dict[str, Any]) -> list[Candidate]:
    """Flatten a Lens payload into de-duplicated candidates.

    Ordering is stable and evidence-driven: exact matches, then visual
    matches, then organic results; original Lens position breaks ties.
    """
    candidates: list[Candidate] = []
    seen_links: set[str] = set()
    seen_images: set[str] = set()

    for section in RESULT_SECTIONS:
        for entry in _entries(payload, section):
            if not isinstance(entry, dict):
                continue

            link = _clean(entry.get("link"))
            if not link or is_excluded(link):
                continue

            canonical = normalise_link(link)
            if canonical in seen_links:
                continue

            # Lens frequently returns one thumbnail for many pages on the same
            # site. Face-checking that image again cannot produce new evidence,
            # and each repeat costs a download and an inference from the
            # candidate budget — so keep only the highest-ranked page per image.
            image_key = _clean(entry.get("image")) or _clean(entry.get("thumbnail"))
            if image_key and image_key in seen_images:
                continue

            seen_links.add(canonical)
            if image_key:
                seen_images.add(image_key)

            platform, is_social = platform_for_url(link)
            raw_position = entry.get("position")
            try:
                position = int(raw_position)
            except (TypeError, ValueError):
                position = len(candidates) + 1

            candidates.append(
                Candidate(
                    position=position,
                    title=_clean(entry.get("title")) or "(untitled)",
                    link=link,
                    source=_clean(entry.get("source")) or platform,
                    platform=platform,
                    is_social=is_social,
                    section=section,
                    image_url=_clean(entry.get("image")) or None,
                    thumbnail_url=_clean(entry.get("thumbnail")) or None,
                )
            )

    return candidates


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Order candidates by how promising they are to check first.

    Primary social platforms lead because personal posts are what the task
    asks for, then other social sites, then everything else; exact matches
    outrank visual ones and Lens position breaks the tie. This only sets
    inspection *order* — nothing here decides a match.
    """
    section_rank = {name: i for i, name in enumerate(RESULT_SECTIONS)}
    return sorted(
        candidates,
        key=lambda c: (
            c.tier,
            section_rank.get(c.section, len(RESULT_SECTIONS)),
            c.position,
        ),
    )
