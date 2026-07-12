"""Failure alerting: an ingest problem must never stay silent.

Every alert is appended to data/logs/alerts.log; when ALERT_WEBHOOK_URL is
set (e.g. an ntfy.sh topic URL) the message is POSTed there too.

CLI: python alerting.py "message"   (useful to test the webhook from cron)
"""
import os
import sys
from datetime import datetime, timezone

import requests

from config import ISO_UTC, LOG_DIR


def send_alert(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime(ISO_UTC)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "alerts.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {message}\n")

    webhook = os.environ.get("ALERT_WEBHOOK_URL")
    if not webhook:
        return
    try:
        requests.post(webhook, data=message.encode("utf-8"), timeout=30)
    except requests.RequestException as exc:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{stamp} webhook delivery failed: {exc}\n")


if __name__ == "__main__":
    send_alert(" ".join(sys.argv[1:]) or "manual test alert")
