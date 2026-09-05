"""Normalise a raw Google Lens payload into ranked :class:`Candidate` records.

SerpApi returns several result arrays with the same broad shape. This module
flattens them into one list, tags each entry with the platform it came from,
and removes duplicates — without deciding anything about face identity. That
judgement belongs to :mod:`search.candidate_selector`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse

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


def is_excluded(url: str) -> bool:
    """True for search-engine internals that aren't real result pages."""
    lowered = (url or "").lower()
    if not lowered.startswith(("http://", "https://")):
        return True
    return any(fragment in lowered for fragment in EXCLUDED_HOSTS)


# Selection priority. Tier 0 is what the task actually asks for — personal
# social-media posts. Tier 1 platforms are social but are aggregators or
# video sites, where a "match" is more often a news still or a reaction video
# than a post about the person. Tier 2 is everything else.
PRIMARY_SOCIAL = {
    "Instagram",
    "Facebook",
    "X (Twitter)",
    "LinkedIn",
    "TikTok",
    "Threads",
    "Snapchat",
    "Bluesky",
    "Mastodon",
}

TIER_PRIMARY_SOCIAL = 0
TIER_OTHER_SOCIAL = 1
TIER_NON_SOCIAL = 2


def platform_tier(platform: str, is_social: bool) -> int:
    """Rank a platform for selection purposes."""
    if platform in PRIMARY_SOCIAL:
        return TIER_PRIMARY_SOCIAL
    return TIER_OTHER_SOCIAL if is_social else TIER_NON_SOCIAL


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

    for section in RESULT_SECTIONS:
        for entry in _entries(payload, section):
            if not isinstance(entry, dict):
                continue

            link = _clean(entry.get("link"))
            if not link or link in seen_links or is_excluded(link):
                continue
            seen_links.add(link)

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
