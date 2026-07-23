"""Fetch and classify entries from the Atlassian developer changelog feed."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from time import mktime

import feedparser
import requests

import config

# Feed categories that describe a change capable of breaking existing code.
BREAKING_CATEGORIES = {
    "removed",
    "deprecation notice",
    "deprecation",
    "changed",
    "security",
    "security advisory",
    "action required",
}

# Wording that signals a breaking change even under a mild category.
BREAKING_PHRASES = (
    "breaking change",
    "will be removed",
    "no longer",
    "must migrate",
    "action required",
    "end of life",
    "end-of-life",
    "deprecat",
    "removal",
    "sunset",
    "stop working",
    "cease",
)


@dataclass
class Entry:
    uid: str
    title: str
    link: str
    category: str
    text: str
    raw_html: str
    published: datetime

    @property
    def is_breaking(self):
        if self.category.lower() in BREAKING_CATEGORIES:
            return True
        haystack = f"{self.title}\n{self.text}".lower()
        return any(phrase in haystack for phrase in BREAKING_PHRASES)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def strip_html(markup):
    """Flatten an HTML fragment to readable plain text."""
    parser = _TextExtractor()
    parser.feed(unescape(markup or ""))
    text = " ".join(" ".join(parser.parts).split())
    return text


def fetch_recent_entries():
    """Return changelog entries published within the lookback window."""
    response = requests.get(
        config.RSS_URL,
        timeout=30,
        headers={"User-Agent": "atlassian-dev-release-bot"},
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)
    if feed.bozo:
        print(f"Warning: feed did not parse cleanly: {feed.bozo_exception}")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.LOOKBACK_HOURS)

    recent = []
    for raw in feed.entries:
        published = raw.get("published_parsed") or raw.get("updated_parsed")
        if not published:
            continue
        published_at = datetime.fromtimestamp(mktime(published), tz=timezone.utc)
        if published_at <= cutoff:
            continue

        tags = raw.get("tags") or []
        category = tags[0].get("term", "") if tags else ""
        recent.append(
            Entry(
                uid=raw.get("id") or raw.get("link", ""),
                title=re.sub(r"^\[[^\]]+\]\s*", "", raw.get("title", "(untitled)")),
                link=raw.get("link", ""),
                category=category,
                text=strip_html(raw.get("summary", "")),
                raw_html=unescape(raw.get("summary", "")),
                published=published_at,
            )
        )

    breaking = sum(1 for entry in recent if entry.is_breaking)
    print(
        f"Feed entries: {len(feed.entries)}, "
        f"within last {config.LOOKBACK_HOURS}h: {len(recent)}, breaking: {breaking}"
    )
    return recent
