"""
Cron script — runs watchlist check and sends Telegram alerts for matches.
Schedule: every hour (alongside news sync).
"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from data.watchlist import check_watchlist, format_alert_message
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

def send_telegram(chat_id: str, text: str):
    if not BOT_TOKEN or chat_id == "guest":
        print(f"[DRY RUN] Would send to {chat_id}:\n{text}\n")
        return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=10,
    )

def main():
    print("Running watchlist check...")
    alerts = check_watchlist()
    if not alerts:
        print("No new alerts.")
        return

    print(f"{len(alerts)} alert(s) to send.")
    sent = 0
    for alert in alerts:
        msg = format_alert_message(alert)
        try:
            send_telegram(alert["user_id"], msg)
            sent += 1
            print(f"  → Sent to {alert['user_id']}: {alert['town']} {alert['flat_type']} SGD {alert['price_sgd']:,.0f}")
        except Exception as e:
            print(f"  ✗ Failed to send: {e}")

    print(f"Done. {sent}/{len(alerts)} sent.")

if __name__ == "__main__":
    main()
