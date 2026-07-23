import html
import os
import sys
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
import requests

# 1. Configuration
# The changelog landing page is a JavaScript app, not a feed. This is the real
# RSS endpoint, generated from the changelog page's "Generate feed" dialog with
# no filters applied (all types, all components).
RSS_URL = "https://developer.atlassian.com/changelog/rss/a/f859a215-65f3-4ebc-b7dd-10007cfd7f60"
BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

LOOKBACK_HOURS = 24
TELEGRAM_MAX_CHARS = 4096


def fetch_recent_entries():
    """Return the changelog entries published within the lookback window."""
    response = requests.get(
        RSS_URL,
        timeout=30,
        headers={"User-Agent": "atlassian-dev-release-bot"},
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)
    if feed.bozo:
        print(f"Warning: feed did not parse cleanly: {feed.bozo_exception}")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    recent = []
    for entry in feed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if not published:
            continue
        if datetime.fromtimestamp(mktime(published), tz=timezone.utc) > cutoff:
            title = html.escape(entry.get("title", "(untitled)"))
            link = html.escape(entry.get("link", ""), quote=True)
            recent.append(f"• <a href=\"{link}\">{title}</a>")

    print(f"Feed entries: {len(feed.entries)}, within last {LOOKBACK_HOURS}h: {len(recent)}")
    return recent


def build_messages(recent_entries):
    """Build the message text, split into Telegram-sized chunks."""
    header = "<b>🚀 Atlassian Developer Updates (Last 24h)</b>"

    if not recent_entries:
        return [
            "<b>🚀 Atlassian Developer Updates</b>\n\n"
            "No new release notes published in the last 24 hours. 💤"
        ]

    messages = []
    lines = [header, ""]
    for entry in recent_entries:
        if sum(len(l) + 1 for l in lines) + len(entry) > TELEGRAM_MAX_CHARS:
            messages.append("\n".join(lines))
            lines = [header + " (cont.)", ""]
        lines.append(entry)
    messages.append("\n".join(lines))
    return messages


def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    response = requests.post(url, json=payload, timeout=30)

    if not response.ok:
        # Telegram explains every 400 in the response body; the raised HTTPError does not.
        print(f"Telegram API error {response.status_code}: {response.text}", file=sys.stderr)
        try:
            description = response.json().get("description", "")
        except ValueError:
            description = ""
        if "chat not found" in description.lower():
            print(
                "Hint: TELEGRAM_CHAT_ID is wrong or the bot is not a member of that chat. "
                "Supergroup and channel IDs start with -100. Send a message in the chat, then read "
                "the id from https://api.telegram.org/bot<TOKEN>/getUpdates.",
                file=sys.stderr,
            )
        elif "parse entities" in description.lower():
            print("Hint: message contains HTML that Telegram rejected.", file=sys.stderr)
        response.raise_for_status()

    print("Message sent successfully!")


def main():
    if not BOT_TOKEN or not CHAT_ID:
        sys.exit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set.")

    for message in build_messages(fetch_recent_entries()):
        send_message(message)


if __name__ == "__main__":
    main()
