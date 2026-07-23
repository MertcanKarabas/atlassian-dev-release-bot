import feedparser
import requests
import os
from datetime import datetime, timedelta, timezone
from time import mktime

# 1. Configuration
# The unified Atlassian developer changelog RSS feed
RSS_URL = "https://developer.atlassian.com/changelog/feed" 
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def main():
    # 2. Fetch and filter RSS entries from the last 24 hours
    feed = feedparser.parse(RSS_URL)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    
    recent_entries = []
    for entry in feed.entries:
        entry_date = datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc)
        
        if entry_date > yesterday:
            recent_entries.append(f"• {entry.title}")
            
    # 3. Format and send the message via Telegram
    if recent_entries:
        message = "🚀 Atlassian Developer Updates (Last 24h)\n\n" + "\n".join(recent_entries)
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Message sent successfully!")
    else:
        print("No updates in the last 24 hours.")

if __name__ == "__main__":
    main()