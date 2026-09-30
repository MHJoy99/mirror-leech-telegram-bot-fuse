#!/usr/bin/env python3
"""Daily Google Drive OAuth token keep-alive + alert.

Refreshes each bot's token.pickle (a refresh counts as "use", which resets
Google's 6-month inactivity expiry) and sends a Telegram alert to the bot
owner if Google rejects it (invalid_grant / revoked).

Usage: gdrive-token-watch.py [--file PATH ...]   (default: the two bot tokens)
"""
import json
import pickle
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from google.auth.transport.requests import Request

DEFAULT_FILES = [
    "/srv/bot-storage/serene_maxwell/app/token.pickle",
    "/srv/bot-storage/fuse_bot/token.pickle",
]
ALERT_CONTAINER = "serene_maxwell"  # bot used to send the alert; config read at runtime
LOG = "/var/log/gdrive-token-watch.log"


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def check(path):
    try:
        creds = pickle.load(open(path, "rb"))
        if not getattr(creds, "refresh_token", None):
            return False, "no refresh_token in file"
        creds.refresh(Request())
        return True, f"ok, access token valid until {creds.expiry} UTC"
    except Exception as e:  # RefreshError, unpickle errors, network
        return False, f"{type(e).__name__}: {str(e)[:200]}"


def telegram_alert(text):
    cfg = subprocess.run(
        ["docker", "exec", ALERT_CONTAINER, "cat", "/app/config.py"],
        capture_output=True, text=True, timeout=30,
    ).stdout
    token = re.search(r'^BOT_TOKEN\s*=\s*"([^"]+)"', cfg, re.M).group(1)
    owner = re.search(r"^OWNER_ID\s*=\s*(\d+)", cfg, re.M).group(1)
    data = urllib.parse.urlencode({"chat_id": owner, "text": text}).encode()
    with urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=30
    ) as r:
        return json.load(r).get("ok")


def main():
    files = DEFAULT_FILES
    if "--file" in sys.argv:
        files = sys.argv[sys.argv.index("--file") + 1:]
    failed = []
    for p in files:
        ok, detail = check(p)
        log(f"{'OK  ' if ok else 'FAIL'} {p}: {detail}")
        if not ok:
            failed.append((p, detail))
    if failed:
        body = "\n".join(f"- {p}\n  {d}" for p, d in failed)
        text = (
            "Google Drive token problem: uploads to Drive will fail until fixed.\n"
            f"{body}\n\n"
            "Fix: regenerate token.pickle for the Drive account, replace the file "
            "in /srv/bot-storage/<bot>/ AND the token__pickle field in MongoDB "
            "(settings.files), then no restart is needed."
        )
        try:
            log(f"alert sent: {telegram_alert(text)}")
        except Exception as e:
            log(f"ALERT FAILED: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
