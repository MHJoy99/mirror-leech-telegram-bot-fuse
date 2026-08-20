# Dual Leech + Google Drive Replication Architecture

<div align="center">

[![Storage](https://img.shields.io/badge/Dual--Storage-Telegram%20%2B%20Google%20Drive-orange?style=for-the-badge&logo=google-drive&logoColor=white)](https://www.google.com/drive/)
[![Resilience](https://img.shields.io/badge/Fault--Tolerance-Non--Blocking%20Backup-success?style=for-the-badge&logo=shield&logoColor=white)](docs/FUSE_ZERO_DOUBLE_STORAGE_AND_ZIP_PICKER.md)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge&logo=gnu&logoColor=white)](LICENSE)

*Comprehensive specification covering dual-destination execution pipelines, fault-tolerant secondary Google Drive replication, quota protection safeguards, and combined status reporting.*

</div>

---

## 1. Executive Summary

Standard mirror bots operate in mutually exclusive modes: a task is either a **Telegram Leech** (`is_leech=True`) or a **Cloud Mirror** (`is_leech=False`).

**mirror-leech-telegram-bot-fuse** implements a hybrid **Dual Leech + Google Drive Backup** architecture. A leech task first transmits the prepared media payload to Telegram. Once the primary Telegram delivery succeeds, the engine automatically replicates the final post-processed artifacts into Google Drive in the background.

```
                          [ User Task: /leech <url> ]
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │   Download & Media Pipeline   │
                       │   - FUSE mount / Aria2 / qBit │
                       │   - ffprobe metadata probe    │
                       │   - Chunk splitting (if >2GB) │
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │  STAGE 1: Telegram Leech      │
                       │  - TDLib Pool / Pyrogram      │
                       │  - Direct Chat/Channel Ingress│
                       └───────────────┬───────────────┘
                                       │
                         ┌─────────────┴─────────────┐
                         ▼ (TG Upload Succeeded)     ▼ (TG Upload Failed)
        ┌──────────────────────────────────┐      ┌─────────────────────────┐
        │ STAGE 2: Secondary Drive Backup  │      │ Task Terminated Early   │
        │ - Non-blocking async upload      │      │ Error returned to user  │
        │ - Duplicate check & SA rotation  │      └─────────────────────────┘
        └────────────────┬─────────────────┘
                         │
        ┌────────────────┴────────────────┐
        ▼ (Drive Success)                 ▼ (Drive Failed / Quota Exceeded)
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│ Combined Leech Success Card     │   │ Partial Success Card            │
│ - TG Links + Cloud Drive Button │   │ - TG Links + Drive Warning Note │
└────────────────┬────────────────┘   └────────────────┬────────────────┘
                 │                                     │
                 └──────────────────┬──────────────────┘
                                    │
                                    ▼
                     ┌───────────────────────────────┐
                     │ Atomic Workspace Teardown     │
                     │ - Local artifact purge        │
                     │ - fusermount -uz unmount      │
                     └───────────────────────────────┘
```

---

## 2. Destination Resolution Hierarchy

When a leech command is executed, the bot determines the secondary Google Drive destination using the following precedence rules:

```
                  ┌─────────────────────────────────┐
                  │ User-Specific GDRIVE_ID Config? │
                  └────────────────┬────────────────┘
                                  / \
                            YES  /   \  NO
                                /     \
                               v       v
         ┌────────────────────────┐  ┌────────────────────────┐
         │ Use user_dict[GDRIVE_ID│  │ Use Global Config.GDRIVE│
         └───────────┬────────────┘  └───────────┬────────────┘
                     │                           │
                     └─────────────┬─────────────┘
                                   │
                                   v
                   ┌───────────────────────────────┐
                   │ Destination Folder ID Bound   │
                   └───────────────────────────────┘
```

If neither is configured, the secondary backup stage is silently skipped and the task operates as a standard Telegram-only leech.

---

## 3. Resilience & Fault-Tolerance Boundaries

The dual-destination pipeline enforces strict isolation boundaries to guarantee that cloud-side failures never degrade the primary Telegram delivery:

| Failure / Edge Case Scenario | Engine Reaction | User Impact |
| :--- | :--- | :--- |
| **Telegram Upload Fails** | Task halts immediately; Drive stage cancelled. | Standard Telegram error message returned. |
| **Google Drive Token Expired / Invalid** | Logs warning, skips Drive stage, marks TG success. | Task succeeds on Telegram; Drive skipped in summary. |
| **Google Drive Quota Exceeded (`403 / 507`)** | Logs warning, completes Telegram task cleanly. | File is delivered on Telegram with partial success note. |
| **Duplicate File on Drive** | Drive upload skipped according to duplicate policy. | Leech succeeds; Drive reported as `Duplicate - Skipped`. |
| **Interactive ZIP Picker (`-s`) Active** | Secondary Drive backup automatically disabled. | Selective leech delivers chosen files without cloud mirror. |

---

## 4. Combined Status Card Specification

Upon task completion, the bot synthesizes an aggregated Telegram message card presenting both delivery channels:

```
┌────────────────────────────────────────────────────────┐
│ <b>Leech Completed!</b>                                   │
│                                                        │
│ <b>File Name:</b> <code>The.K2.S01E01.1080p.NF.WEB-DL.mkv</code>     │
│ <b>Size:</b> 1.94 GB                                    │
│ <b>Duration:</b> 01:04:12                               │
│ <b>Languages:</b> Korean [Original], English             │
│ <b>Subtitles:</b> English, Spanish, French               │
│                                                        │
│ ⚡ <b>Telegram Delivery:</b> 1 File (100% Sent)          │
│ ☁️ <b>Google Drive Backup:</b> Upload Complete           │
├────────────────────────────────────────────────────────┤
│ [ 📁 View in Google Drive ] [ 🔗 Channel Post Link ]   │
└────────────────────────────────────────────────────────┘
```

---

## 5. Production Log Verification

To confirm active dual leech execution in running containers:

```bash
docker compose logs --tail=100 -f app | grep -E "Leech Completed|Starting secondary Google Drive|Uploaded To G-Drive"
```

### Expected Log Output:
```text
2026-08-20 10:14:22 INFO  bot.helper.mirror_leech_utils.tdlib_uploader: TDLib leech completed: The.K2.S01E01.mkv
2026-08-20 10:14:22 INFO  bot.helper.listeners.task_listener: Starting secondary Google Drive upload: source=/app/downloads/31642/The.K2.S01E01.mkv
2026-08-20 10:14:28 INFO  bot.helper.mirror_leech_utils.gdrive_uploader: Uploaded To G-Drive: The.K2.S01E01.mkv (1.94 GB)
2026-08-20 10:14:29 INFO  bot.helper.listeners.task_listener: Combined leech result dispatched successfully
```
