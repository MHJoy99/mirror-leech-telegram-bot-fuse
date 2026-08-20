# Google Drive OAuth Switch to 5 TB Owner Account

**Date:** 2026-08-08

## Overview

Successfully updated the Google Drive API v3 authentication token (`token.pickle`) and configuration defaults for the live Telegram mirror/leech bot (`mltb-container` / `anasy-fuse-bot`).

The upload identity was switched from a free 15 GB account (`old_service_account@example.com`) to the target folder owner's personal 5 TB Google Account (`user@example.com` / `OwnerAccount`).

## Root Cause of Prior Upload Failures

When uploading to a personal **My Drive** folder shared by another user:
- Google Drive API v3 charges the uploader's Google Account quota, NOT the folder owner's quota.
- The bot was previously authenticating via `token.pickle` belonging to `old_service_account@example.com` (15 GB limit, 14.65 GB used, ~358 MB remaining).
- Any upload larger than ~358 MB failed with `HTTP 403 storageQuotaExceeded`.
- Additionally, `IS_TEAM_DRIVE` was initially enabled in config/settings, which attempted Team Drive authorization routines for standard My Drive folders.

## Changes Made

1. **Backup:** Backed up original `token.pickle` at `/srv/bot-storage/fuse_bot/app/token.pickle.bak_20260808` (or `/path/to/storage/token.pickle.bak`).
2. **OAuth Token Exchange:** Completed standard Google OAuth2 PKCE/Direct authorization flow for `user@example.com`.
3. **Live Deployment:** Installed verified `token.pickle` and matching `credentials.json` into the live bind-mounted application path `/srv/bot-storage/fuse_bot/app/` (or `/path/to/storage/fuse_bot/app/`) and credentials directories.
4. **Permissions:** Set permissions to `0644` (owner: `root:root`).
5. **Config Alignment:** Verified `USE_SERVICE_ACCOUNTS = False` and `IS_TEAM_DRIVE = False` in `config.py` so standard Google Drive API calls default to the global 5 TB `token.pickle`.
6. **User Settings / Bot Defaults:** User re-uploaded/configured `token.pickle` via Telegram bot settings (`/bsettings` / `/usettings`), setting default upload routing so all user tasks default to the 5 TB account.
7. **Git Hygiene:** Updated `.gitignore` to ignore private credentials/secret directories (`"git ignore this please "`, `secrets use git ignore please`).

## Verification & Proof

- **Authenticated Principal:** `user@example.com` (`OwnerAccount`)
- **Observed Quota:** `5,120.00 GB` (5.00 TB limit), ~6.99 GB used (~4.99 TB free)
- **Target Destination:** `1A2B3C4D5E6F7G8H9I0J_EXAMPLE` (`Motion Picture` folder, owned by `user@example.com`)
- **Live Mirror Upload Test:** Telegram `/mirror` download completed, uploaded successfully to G-Drive (`Uploaded To G-Drive`), deleted cleanly via `/del`, and verified working without storage quota errors.
- **Bot Restart:** `mltb-container` restarted cleanly and logged `Bot Started!`.

## Rollback Procedure

If needed, restore the previous token backup:
```bash
cp /srv/bot-storage/fuse_bot/app/token.pickle.bak_20260808 /srv/bot-storage/fuse_bot/app/token.pickle
docker restart mltb-container
```
