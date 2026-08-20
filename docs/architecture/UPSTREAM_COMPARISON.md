# Upstream Architectural Differences & Modifications

<div align="center">

[![Upstream Fork](https://img.shields.io/badge/Fork%20Of-anasty17%2Fmirror--leech--telegram--bot-26A5E4?style=for-the-badge&logo=github&logoColor=white)](https://github.com/anasty17/mirror-leech-telegram-bot)
[![Maintained By](https://img.shields.io/badge/Maintained%20By-MHJoy99%20%2F%20MHJoyBots-orange?style=for-the-badge&logo=telegram&logoColor=white)](https://github.com/MHJoy99/mirror-leech-telegram-bot-fuse)
[![Architecture](https://img.shields.io/badge/Architecture-FUSE%20%2B%20TDLib%20Pool-success?style=for-the-badge&logo=linux&logoColor=white)](docs/FUSE_ZERO_DOUBLE_STORAGE_AND_ZIP_PICKER.md)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge&logo=gnu&logoColor=white)](LICENSE)

*Comprehensive technical specification detailing architectural divergency, runtime patches, new subsystem modules, and operational behavior between upstream `mirror-leech-telegram-bot` and `mirror-leech-telegram-bot-fuse`.*

</div>

---

## 1. Executive Summary

**mirror-leech-telegram-bot-fuse** is a high-performance production fork of `anasty17/mirror-leech-telegram-bot` (MLTB). While upstream MLTB serves as a versatile multi-protocol mirror/leech engine, standard deployments suffer from severe storage amplification (the "double-storage penalty" on archives) and strict per-account Telegram upload concurrency ceilings.

This fork introduces five primary architectural innovations:
1. **Linux FUSE Virtual Mounting (`archivemount`)**: Eliminates the 2x physical disk extraction penalty on multi-GB archives by mounting them directly into the Linux VFS.
2. **Interactive Inline Telegram ZIP GUI Picker**: A paginated Telegram inline keyboard interface allowing cherry-picking of specific files/episodes from archives before transmission.
3. **TDLib Multi-Session Concurrency Pool**: Scalable round-robin userbot upload cluster distributing multi-part split workloads across multiple authenticated Telegram sessions.
4. **Dual-Destination Leech + Asynchronous Cloud Backup**: Independent, non-blocking secondary replication of leech artifacts to Google Drive upon Telegram transmission completion.
5. **Dynamic WZML Media Captioning**: Codec, duration, language track, and embedded/external subtitle stream deduction via `ffprobe` and `langcodes`.

---

## 2. High-Level Comparison Matrix

| Subsystem / Feature | Upstream MLTB (`anasty17`) | mirror-leech-telegram-bot-fuse | Operational Impact |
| :--- | :--- | :--- | :--- |
| **Archive Decompression** | Physical `7z x` extraction to disk | **Linux FUSE (`archivemount -o readonly,nosave`)** | **50% Disk Space Savings**; Zero raw extraction overhead |
| **Archive Selection** | CLI flags / all-or-nothing | **Interactive Inline ZIP GUI Picker** | Interactive UI with checkboxes, pagination, and size totals |
| **Split File Storage** | All splits created upfront before upload | **Streaming Per-File Split & Purge** | Peak disk capped at `Archive + 1 Split Part` (<2.5GB) |
| **Telegram Upload Engine** | Single client (Pyrogram or TDLib single DB) | **Multi-Session TDLib Worker Pool** | Round-robin load balancing across independent Telegram accounts |
| **Upload Parallelism** | Serial folder-by-folder dispatch | **Concurrent global batch dispatch** | Independent worker parallelism on splits and individual files |
| **Leech Secondary Destination** | Mutual exclusivity (Telegram OR Cloud) | **Dual Leech + Google Drive Backup** | Primary Telegram leech followed by background Drive backup |
| **Media Metadata Extraction** | Basic file metadata | **Smart WZML `ffprobe` Engine** | Auto-resolution of audio language codes and subtitle tracks |
| **Session Generation Tools** | Manual CLI / external scripts | **Automated CLI Helpers & One-Click Cloner** | Built-in tooling for pool initialization, expansion, and cloning |

---

## 3. Core Architectural Subsystems

### 3.1 FUSE Zero-Double-Storage & Selective Streaming Pipeline

```
+---------------------------------------------------------------------------------------------------+
| Upstream MLTB Pipeline:                                                                           |
| [Download 33GB ZIP] ──▶ [Extract 35GB Uncompressed] ──▶ [Pre-Split all files] ──▶ Total: ~88GB   |
+---------------------------------------------------------------------------------------------------+

+---------------------------------------------------------------------------------------------------+
| mirror-leech-telegram-bot-fuse Pipeline:                                                          |
| [Download 33GB ZIP] ──▶ [FUSE VFS Mount (.mnt_*)] ──▶ [Stream Single File Split] ──▶ Total: ~35GB |
|                                │                                                                  |
|                                ├──▶ [Inline Telegram ZIP Picker GUI]                             |
|                                └──▶ [Immediate split chunk removal on upload]                     |
+---------------------------------------------------------------------------------------------------+
```

- **Upstream Behavior**: Archives are decompressed via `7z` directly into `DOWNLOAD_DIR`. On large season archives (e.g. 33GB), this requires 68GB+ disk space, causing `ENOSPC` failures on standard 80GB VPS instances.
- **Fork Implementation**: Mounts archives into a local virtual path (`.mnt_<archive>_zip_<id>`). If selective mode (`-s`) is passed, the bot pauses and presents the inline GUI. During upload, only the active file being processed is split into a temporary staging folder (`<archive>_splits/`), and parts are deleted immediately upon successful upload.

---

### 3.2 TDLib Multi-Session Concurrency Pool

```
                               ┌────────────────────────────────┐
                               │       Task Dispatcher          │
                               └───────────────┬────────────────┘
                                               │
                                       (Acquires Slot)
                                               │
                                               ▼
                              ┌──────────────────────────────────┐
                              │  TdlibManager.get_upload_client()│
                              └────────────────┬─────────────────┘
                                               │
                                 ┌─────────────┴─────────────┐
                                 ▼ (Round-Robin Selection)   ▼
                    ┌────────────────────────┐  ┌────────────────────────┐
                    │ TDLib Client #1 (DB 2) │  │ TDLib Client #2 (DB 3) │ ...
                    └────────────────────────┘  └────────────────────────┘
```

- **Upstream Behavior**: Single TDLib database path (`TDLIB_USER_DB_PATH`) supporting only one authenticated user session.
- **Fork Implementation**: `TdlibManager` orchestrates an array of session databases (`TDLIB_USER_DB_PATHS`). Upload tasks rotate across available authenticated clients with thread-safe locks (`_pool_lock`), preventing account-level throughput throttling.

---

### 3.3 Dual Leech + Google Drive Replication

```
  [ Task Execution: /leech <url> ]
                 │
                 ▼
     ┌───────────────────────┐
     │ Telegram Upload Stage │ ──▶ Dispatched to User / Target Channel
     └───────────┬───────────┘
                 │ (Success)
                 ▼
     ┌───────────────────────┐
     │ Google Drive Backup   │ ──▶ Asynchronous Secondary Upload
     └───────────┬───────────┘
                 │
                 ▼
     ┌───────────────────────┐
     │ Aggregate Status Card │ ──▶ Reports TG Status + GDrive Cloud Link
     └───────────────────────┘
```

- **Upstream Behavior**: Tasks are either `is_leech=True` (upload to Telegram) or `is_leech=False` (upload to Drive/Rclone).
- **Fork Implementation**: Leech tasks retain the processed payload in staging until Telegram finishes, then automatically initiate a secondary backup to Google Drive if `GDRIVE_ID` is defined. Failure in the Drive stage does not invalidate the Telegram delivery.

---

## 4. Repository Modification Inventory

```
/root/mirror-leech-telegram-bot-fuse/
├── bot/
│   ├── core/
│   │   ├── config_manager.py        # Added LEECH_CAPTION template loader & alternate module support
│   │   ├── handlers.py              # Hooked inline ZIP selector callback router (^zipsel)
│   │   ├── startup.py               # Startup concurrency applicator & TDLib pool logger
│   │   └── tdlib_manager.py         # Multi-session TDLib client pool & C-FFI string/bytes shims
│   ├── helper/
│   │   ├── common.py                # FUSE streaming engine, _picker_small_only & anti-choke dispatcher
│   │   ├── ext_utils/
│   │   │   ├── files_utils.py       # archivemount executor, VFS polling & fusermount unmount safety
│   │   │   └── media_utils.py       # ffprobe WZML metadata parser & langcodes normalizer
│   │   ├── listeners/
│   │   │   └── task_listener.py     # ZIP picker trigger (-s), Drive isolation & upload aggregation
│   │   └── mirror_leech_utils/
│   │       └── tdlib_uploader.py    # Pool-aware uploader with session logging and batch dispatch
│   └── modules/
│       ├── users_settings.py        # Per-user custom LEECH_CAPTION override interface
│       └── zip_selector.py          # Native Telegram inline ZIP picker GUI engine
├── clone_tdlib_pool.py              # Automated 1-click TDLib database cloner
├── generate_tdlib_user_database.py  # TDLib authentication session generator
├── setup_tdlib_pool.py              # Multi-account TDLib pool setup CLI
└── bench_pytdbot_login.py           # TDLib authentication benchmark utility
```

---

## 5. Summary of New Configuration Directives

The following configuration parameters are introduced or modified in this fork:

```python
# TDLib Multi-Session Concurrency Pool
TDLIB_USER_DB_PATH = "tdlib_user"             # Primary base session path
TDLIB_USER_DB_PATHS = [                       # Array of secondary session databases
    "tdlib_user_2",
    "tdlib_user_3",
    "tdlib_user_4"
]
TDLIB_USER_UPLOAD = True                      # Enable TDLib userbot upload backend

# Concurrency & Worker Tuning
TG_FILE_UPLOAD_CONCURRENCY = 8               # Parallel active file upload limit
TG_SPLIT_UPLOAD_CONCURRENCY = 4              # Parallel split part upload limit
TG_UPLOAD_WORKERS = 16                       # Worker threads per upload task

# Leech Caption Formatting
LEECH_CAPTION = "{filename}\n{size}\n🕒 {duration} | 🔊 {languages}\n📄 SUBTITLES : {subtitles}"
```
