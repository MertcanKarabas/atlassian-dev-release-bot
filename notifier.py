"""Telegram delivery."""

import sys

import requests

import config


def split_messages(blocks, header):
    """Pack blocks into Telegram-sized messages, repeating the header on overflow."""
    messages = []
    lines = [header, ""]
    for block in blocks:
        if sum(len(line) + 1 for line in lines) + len(block) > config.TELEGRAM_MAX_CHARS:
            messages.append("\n".join(lines))
            lines = [f"{header} (cont.)", ""]
        lines.append(block)
    messages.append("\n".join(lines))
    return messages


def send(text):
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.CHAT_ID,
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
