# @mhjoyleechdc_bot Live Customizations Runbook

**Last updated:** 2026-10-01
**Container:** `serene_maxwell` (bot `@mhjoyleechdc_bot`), files under `/srv/bot-storage/serene_maxwell/`.

This bot runs a separate deployment of the codebase. Several changes were applied **inside the running container** (not in this repo). If the container is recreated from its image, re-apply them from `/srv/bot-storage/serene_maxwell/patches/`.

## Summary of changes

| Area | Change | Where |
| :--- | :--- | :--- |
| Drive auth | New OAuth `token.pickle` (file and MongoDB copy) | see [Drive Authentication Runbook](../storage/GDRIVE_OAUTH_SETUP.md) |
| Global thumbnail | Cine Motion image used for every leech and every user | `/app/global_thumb.jpg`, `users.THUMBNAIL` in MongoDB |
| Universal prefix | `MOTION PICTURE-@mhjoybots` on all uploaded names, including split parts | `config.py`, `settings.config`, `settings.deployConfig`, every user |
| Queue limit | `QUEUE_DOWNLOAD=2`, `QUEUE_UPLOAD=2` | `config.py`, both MongoDB config docs |
| Status API | Read-only `GET /api/status` for the HDHub4u pipeline | `status_export.py` plus host service `leech-status-api` |
| Drive auto-backup allowlist | Automatic Drive backup after a leech only for Mr. Nobody | `bot/helper/common.py` |
| Slow-task watchdog | Auto-cancels downloads under 100 KB/s or active uploads under 200 KB/s for 10 min (after 3 min grace) | `bot/helper/ext_utils/slow_task_watchdog.py` |
| Non-Premium TDLib uploads | Uploads of 500 MB or more go through the TDLib account pool (native threads) instead of CPU-bound Pyrogram; 2 GB parts. Off switch: `touch /app/tdlib_free_off` | `bot/helper/common.py` (`TDLIB_ALLOW_FREE`) |

**Source of truth (full details, IDs and rules live there, not here):** the bot's own checkout `/srv/bot-storage/serene_maxwell/app` (its own private repo). As of 2026-10-01 every change above is synced there and verified identical to the live container. Its `AGENTS.md` makes syncing mandatory for every future change.

Config values live in **three** places (`config.py` and the MongoDB documents `settings.config` and `settings.deployConfig`). Change all three or a restart reverts the value.

## Global thumbnail

- Fallback order: `-t` on the command, the user's own thumbnail, `/app/global_thumb.jpg`, then the auto-extracted video frame.
- `thumbnails/` is wiped and rebuilt from MongoDB on every start, so the image is also stored in `users.THUMBNAIL` for all existing users (backups of old thumbnails: `thumb_backup_20261001/`).
- Patched `telegram_uploader.py` and `tdlib_uploader.py` (`_user_settings`).
- Split parts get the thumbnail too (verified in Telegram Web).
- To change the image: replace `/app/global_thumb.jpg` (new users) and update `users.THUMBNAIL` (existing users).

## Universal filename prefix

`LEECH_FILENAME_PREFIX = "MOTION PICTURE-@mhjoybots"` is set globally and per user. Previous per-user values are in `patches/prefix_backup_20261001.json`.

## Queue limit

Two concurrent downloads and two concurrent uploads; extra tasks queue. Without it, concurrency was unlimited on a shared disk.

## Status API (HDHub4u integration)

- `status_export.py` (in `bot/helper/ext_utils/`, started from `bot/__main__.py`) writes `/tmp/leech_status.json` every 5 s.
- Host service `leech-status-api` (systemd, `/usr/local/bin/leech-status-api.py`) serves `GET /api/status` on localhost. Auth: header `X-API-Key`, key stored in a root-only env file on the host (never commit it).
- Response: `active`, `queued`, `busy`, `free_gb` (host disk), `limits`, `stale`, `tasks[]` (`id`, `name`, `state`, `progress` 0 to 1, `eta_s`).
- Expose it externally only through a TLS reverse proxy.

## Limits to know

- Max upload ~2 GB per file (`MAX_SPLIT_SIZE` = 2,097,152,000, upload sessions are not Premium); larger files are split into parts.
- **No FUSE** on this bot: extracting an archive (`-e`) needs about 2x the archive size on disk. The zero-double-storage engine exists only on `@mhjoyleech1bot` (`anasty-rss-mhjoybots-fuse-app-1`).
- Shared partition `/srv/bot-storage`: keep free space above the largest planned archive times 2.5.

## Drive auto-backup allowlist

Automatic Google Drive backup after a leech runs only for user IDs in `DRIVE_AUTO_BACKUP_USERS` (`bot/helper/common.py`), currently one user (Mr. Nobody). Everyone else gets a Telegram-only leech with no Drive line on the status card. Decided by the Telegram user who sent the command; group chat IDs are separate users. Edit the set and restart when idle to change it.

## Slow-task watchdog

Checks every 30 s and cancels through the task's normal cancel path (same as `/c`), then posts the reason in the chat. It judges only tasks in Download or Upload state, only after 3 min in that state, and uploads only once bytes are flowing, so queued tasks and uploads waiting for a slot are never cancelled. Any fast sample resets the 10 min clock. Kill switches inside the container: `/app/watchdog_off` disables it, `/app/watchdog_dry_run` only logs. Typical trigger: HDHub4u `pub-….r2.dev` links, which Cloudflare rate-limits (measured about 32 KB/s versus about 95 MB/s for `r2.cloudflarestorage.com` links).

## Re-applying after a container rebuild

Backups in `/srv/bot-storage/serene_maxwell/patches/`: `status_export.py`, `__main__.py.{before,after}-status`, `common.py.{before,after}-drive-gate`. The thumbnail patch (global fallback in both uploaders) and the config edits must be redone by hand. Always restart only when `/api/status` shows `active` and `queued` at 0.
