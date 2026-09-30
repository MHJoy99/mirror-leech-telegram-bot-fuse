# Google Drive Authentication Runbook

**Last verified:** 2026-09-30

How the bot authenticates to Google Drive, how to regenerate the token when Google revokes it, and how to get an alert before uploads start failing.

## TL;DR

- Drive uploads use an **OAuth user token** (`token.pickle`) for the Google account that owns the storage (for example a 5 TB plan).
- When Telegram shows `Google Drive: Failed (('invalid_grant: Token has been expired or revoked.', ...))`, the refresh token is dead. Regenerate it (section 4), replace **both** the file and the MongoDB copy (section 3), and verify (section 5). No restart is required.
- A daily watchdog (section 7) keeps the token alive and sends a Telegram alert if Google rejects it.

## 1. Why OAuth and not Service Accounts

| | OAuth user token | Service Accounts (`accounts/*.json`) |
| :--- | :--- | :--- |
| Expires | Only when revoked, unused 6 months, or over the token cap | Never |
| Storage quota | The Google account's own quota (e.g. 5 TB) | **None.** Cannot own files in My Drive (`storageQuotaExceeded: Service Accounts do not have storage quota`) |
| Works with a personal `@gmail.com` My Drive | Yes | No. Only Shared Drives, which require a Google Workspace (work or school) account |

If the destination is a personal My Drive folder, OAuth is the only workable method. Keep `USE_SERVICE_ACCOUNTS = False` and `IS_TEAM_DRIVE = False` in `config.py`. Service accounts only make sense with a Workspace Shared Drive.

Sources: [Google OAuth 2.0 overview (refresh token expiration)](https://developers.google.com/identity/protocols/oauth2#expiration), [Create a shared drive (Workspace Learning Center)](https://support.google.com/a/users/answer/9310249).

## 2. Why a refresh token dies

Per Google's documentation, a refresh token stops working when:

1. The user revoked the app's access in their Google Account.
2. It was not used for 6 months.
3. The user changed their password **and** the token has Gmail scopes (the Drive-only scope used here is not affected).
4. The account exceeded the live refresh token limit: 100 per account per OAuth client, plus a larger limit across all clients. The oldest token is **silently** invalidated.
5. The OAuth consent screen is in **Testing** status (External user type): tokens expire after 7 days. Publish the app (Google Cloud Console, Google Auth Platform, Audience, Publishing status = In production).

Practical rules: keep the consent screen **In production**, do not mint new tokens unnecessarily (every `prompt=consent` adds one toward the cap), and keep the token in use (the watchdog does this).

## 3. Where the token lives (important)

The bot keeps private files in **two** places, and restores the database copy on startup:

| Location | Used for |
| :--- | :--- |
| `/srv/bot-storage/<bot>/token.pickle` (bind-mounted to `/app/token.pickle`) | Read on every Drive upload |
| MongoDB `<DATABASE_NAME>.settings.files`, document `_id` = bot id (the numeric part of `BOT_TOKEN`, stored as a **string**), field `token__pickle` | Written back to `token.pickle` at container startup |

If you only replace the file, the next restart silently brings the old dead token back. Always update both. Each bot deployment has its own file and its own database document.

Update the database copy from inside the bot container (uses the bot's virtualenv and its own `config.py`):

```python
# run with: docker exec <container> bash -c 'cd /app && source mltbenv/bin/activate && python3 /tmp/dbfix.py'
import re
from pymongo import MongoClient
src = open('/app/config.py').read()
url = re.search(r'^DATABASE_URL\s*=\s*"([^"]+)"', src, re.M).group(1)
name = re.search(r'^DATABASE_NAME\s*=\s*"([^"]+)"', src, re.M).group(1)  # default "mltb"
bot_id = re.search(r'^BOT_TOKEN\s*=\s*"([^"]+)"', src, re.M).group(1).split(":")[0]
db = MongoClient(url)[name]
assert db.settings.files.find_one({"_id": bot_id}), "no document for this bot id"
db.settings.files.update_one({"_id": bot_id},
    {"$set": {"token__pickle": open('/app/token.pickle', 'rb').read()}})
```

Back up the old value first (`find_one(...)["token__pickle"]`).

## 4. Regenerating the token (headless VPS)

`generate_drive_token.py` assumes a local browser and crashes if an existing token is revoked. On a headless VPS, run the flow with a fixed port and relay the redirect:

1. Put `credentials.json` (the OAuth **Desktop app** client) in a scratch directory and run:
   ```python
   import pickle
   from google_auth_oauthlib.flow import InstalledAppFlow
   flow = InstalledAppFlow.from_client_secrets_file(
       "credentials.json", ["https://www.googleapis.com/auth/drive"])
   creds = flow.run_local_server(host="localhost", port=8765, open_browser=False,
       authorization_prompt_message="AUTHURL: {url}", access_type="offline", prompt="consent")
   pickle.dump(creds, open("token.pickle.new", "wb"))
   ```
2. Open the printed `AUTHURL` in a browser signed in to the Drive account, click through the consent screen (**Advanced, Go to app (unsafe)** if the app is unverified), and approve the Drive scope.
3. The browser is redirected to `http://localhost:8765/?state=...&code=...`, which fails on your own machine because the listener runs on the VPS. Copy that full URL and request it from the VPS: `curl "<that URL>"`. The script then writes `token.pickle.new`.
4. Back up the old `token.pickle`, copy the new file into place (`chmod 644`), then update the MongoDB copy (section 3).

## 5. Verify

Run inside the bot container (virtualenv active) and check that the refresh succeeds, the account is the expected one, and the destination folder is writable:

```python
import pickle
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
t = pickle.load(open('/app/token.pickle', 'rb'))
t.refresh(Request())
s = build('drive', 'v3', credentials=t, cache_discovery=False)
print(s.about().get(fields='user(emailAddress),storageQuota(limit,usage)').execute())
print(s.files().get(fileId='<DESTINATION_FOLDER_ID>', fields='id,name,capabilities/canAddChildren',
                    supportsAllDrives=True).execute())
```

The token file is read per upload, so no restart is needed. Then run a real `/leech` and look for `Authorize with token.pickle | User: <account>` in the logs.

## 6. Destination folder

Uploads go to the folder ID the task resolves to (user setting, `-up` argument, or the dual-leech secondary destination in the logs as `dest=...`), which may differ from `GDRIVE_ID` in `config.py`. A 404 when checking `GDRIVE_ID` does not mean the token is bad. Check the ID shown in the upload log line. See [Dual Leech & Google Drive Backup](../architecture/DUAL_LEECH_GDRIVE_BACKUP.md).

## 7. Monitoring and keep-alive

[`scripts/oauth_keepalive_watch.py`](../../scripts/oauth_keepalive_watch.py) refreshes each configured `token.pickle` (a refresh counts as use, which resets the 6-month inactivity clock). If Google rejects a token, it sends a Telegram message to `OWNER_ID` using the bot token read from the bot's `config.py`.

Install on the host (needs `google-auth`; edit `DEFAULT_FILES` and `ALERT_CONTAINER` at the top of the script for your layout):

```bash
install -m 755 scripts/oauth_keepalive_watch.py /usr/local/bin/oauth-keepalive-watch.py
( crontab -l 2>/dev/null; echo '11 6 * * * /usr/bin/python3 /usr/local/bin/oauth-keepalive-watch.py >/dev/null 2>&1' ) | crontab -
```

Logs go to `/var/log/gdrive-token-watch.log`. Test the alert path against a known-bad file with `oauth-keepalive-watch.py --file /path/to/dead/token.pickle` (this sends one real alert).

## 8. Incident history

| Date | Symptom | Cause | Fix |
| :--- | :--- | :--- | :--- |
| 2026-08-08 | `403 storageQuotaExceeded` on large uploads | Token belonged to a 15 GB account; uploads are charged to the uploader's quota | Switched `token.pickle` to the 5 TB account, `IS_TEAM_DRIVE = False` |
| 2026-09-30 | `invalid_grant: Token has been expired or revoked` | Refresh token revoked by Google (consent screen was already In production; exact trigger unknown) | Regenerated token, updated file **and** MongoDB copy, added the watchdog |
