import json
import os
import re
from urllib.request import urlopen

from dotenv import load_dotenv


def private_senders(updates):
    users = {}
    for update in updates:
        message = update.get("message", {})
        sender = message.get("from", {})
        user_id = sender.get("id")
        if (
            message.get("chat", {}).get("type") == "private"
            and isinstance(user_id, int)
            and user_id > 0
            and not sender.get("is_bot")
        ):
            users[user_id] = {
                "id": user_id,
                "username": sender.get("username", ""),
                "name": sender.get("first_name", ""),
            }
    return [users[key] for key in sorted(users)]


def main():
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
        print("Set your real BOT_TOKEN in .env first.")
        return 1
    try:
        with urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20) as response:
            result = json.load(response)
        if result.get("ok") is not True:
            raise ValueError("Telegram rejected the request")
        users = private_senders(result.get("result", []))
    except Exception:
        print(
            "Could not read bot updates. Check BOT_TOKEN, network access, and that this is a fresh bot without a webhook."
        )
        return 1
    if not users:
        print(
            "Send /start to your bot from your own Telegram account, then run this command again."
        )
        return 1
    print(
        "Choose YOUR account's id below and put it in OWNER_ID. No access has been granted by this helper."
    )
    for user in users:
        print(json.dumps(user, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
