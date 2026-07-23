import feedparser
import requests
import os
from datetime import datetime, timedelta, timezone
from time import mktime

# 1. Configuration
RSS_URL = "https://developer.atlassian.com/changelog/" 
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
            recent_entries.append(f"• <a href='{entry.link}'>{entry.title}</a>")
            
    # 3. Format the message depending on whether there are updates
    if recent_entries:
        message = "<b>🚀 Atlassian Developer Updates (Last 24h)</b>\n\n" + "\n".join(recent_entries)
    else:
        message = "<b>🚀 Atlassian Developer Updates</b>\n\nNo new release notes published in the last 24 hours. 💤"
        
    # 4. Send the message via Telegram (this now runs every time)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    response = requests.post(url, json=payload)
    response = requests.post(url, json=payload)
    
    # Add this line to reveal the specific Telegram error:
    print(f"Telegram API Response: {response.text}") 
    
    response.raise_for_status()
    print("Message sent successfully!")
    response.raise_for_status()
    print("Message sent successfully!")

if __name__ == "__main__":
    main()