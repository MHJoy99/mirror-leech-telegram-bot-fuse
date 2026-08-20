# System Architecture & Live-Ops Reference

**Updated:** 2026-08-20  
**Project:** `Anasy-RSS-MHJoyBots-FUSE` (Production Telegram Mirror/Leech Bot Fork based on `python-aria-mirror-bot`)  
**Host Environment:** Ubuntu Linux 6.8.0-138-generic x64 (`/srv/bot-storage` on `/dev/vda4 84G`, 47G free baseline)

---

## 1. Quick Navigation & Live System Mapping

This file is the primary reference for the container architecture, live bot operations, directory bind-mounts, and recent architectural enhancements.

### 1.1 Live Container Topology

| Container Name | Purpose | Base Image / Port Bindings | Host Mount Directory | Container Target |
|---|---|---|---|---|
| `anasy-fuse-bot` | **FUSE Zero-Storage & Telegram ZIP Picker Bot** | Docker Image / Isolated (No port conflicts) | `/srv/bot-storage/fuse_bot/` | `/app/` |
| `mltb-container` | Production Mirror Bot | `mltb-container-image` / Isolated ports | `/srv/bot-storage/fuse_bot/app` | `/app` |
| `facebook-chatbot` | Facebook Messenger Webhook Service | Python Gunicorn / `0.0.0.0:5050->5050` | Standalone Docker Volume | `/app` |
| `support-ticket-app` | Customer Support & Ticketing Engine | Support App Stack / `0.0.0.0:3000` | Postgres + Redis Stack | `/app` |

---

## 2. Core Architectural Pillars (Recent Live-Ops Fixes)

### 2.1 FUSE Zero-Double-Storage Engine (`archivemount readonly,nosave`)
- **Location:** `bot/helper/ext_utils/files_utils.py` (L421–L551) and `bot/helper/listeners/task_listener.py`.
- **Functionality:** Instead of executing `7z x` (which extracts 35 GB of uncompressed video onto the 84 GB SSD), the bot mounts the archive via `archivemount -o readonly,nosave <zip_path> <mount_point>`.
- **Storage Impact:** Peak disk usage drops from 200%+ (~88 GB peak) to `Archive Size + Single Active File Split` (~35 GB peak), maintaining ~14 GB free space throughout large transfers.
- **Teardown Protocol:** `clean_download` (`files_utils.py:123-150`) dynamically parses `/proc/mounts` and executes `fusermount -uz <mount>` before unlinking directories, preventing zombie open-descriptor leaks.

### 2.2 Native Inline Telegram ZIP GUI Picker (`zip_selector.py`)
- **Location:** `bot/modules/zip_selector.py` (L1–L240), `bot/core/handlers.py` (L3, L316), and `task_listener.py` (L448–L460).
- **Trigger:** Initiated automatically when a user passes the `-s` (select) flag with extraction: e.g. `/leech <url> -e -s`.
- **UI Design:**
  - Interactive ButtonMaker paginated menu (8 items per page).
  - Visual status indicators (`✅` selected, `⬜` unselected).
  - Navigation: `◀ Prev`, `Next ▶`, `Select All`, `Deselect All`, `✅ Done`, `❌ Cancel`.
  - Callback payload size strictly formatted under Telegram's 64-byte limit: `zipsel <mid> <action> [args]`.
  - 60-second asynchronous countdown timer with auto-Done fallback on timeout.
  - Multi-tier authorization: `OWNER_ID`, task owner `user_id`, or `SUDO` users.

### 2.3 Leech vs Mirror Drive Leak Guard (`is_leech` Isolation)
- **Location:** `bot/helper/common.py` (L596–L601) and `bot/helper/listeners/task_listener.py` (L598–L602).
- **Root Cause & Fix:** User profiles previously populated `GDRIVE_ID` by default, triggering unwanted secondary Drive uploads during `/leech` tasks. 
- **Code Guard:**
  ```python
  if not self.is_leech:
      await self.resolve_secondary_gdrive_dest()
  else:
      LOGGER.info("Leech mode - skipping secondary GDrive backup (mirror only)")
  ```
- Guarantees that `/leech` commands upload exclusively to Telegram, eliminating quota depletion and false multi-GB transfers.

### 2.4 Small-File-Only Pipeline & Anti-Choke Sequential Upload
- **Location:** `bot/helper/common.py` (L1413–L1614).
- **Small-File Engine (`_picker_small_only`):** When cherry-picking only sub-2GB episodes from an archive, `files_to_proceed` (which filters files $> \text{split\_size}$) becomes empty `{}`. The engine sets `_picker_small_only = True`, bypasses the large-file splitter, and enters the small-file pipeline without resetting the task path.
- **Anti-Choke Sequential Dispatch:** Multi-file parallel uploads against virtual `archivemount` endpoints cause FUSE daemon lockups. Small files are symlinked into isolated `_small_N` temporary sub-folders and uploaded strictly one-by-one, deleting symlink structures immediately after completion.

### 2.5 TDLib Multi-Session Concurrency Pool
- **Location:** `bot/core/tdlib_manager.py` (L1–L350), `setup_tdlib_pool.py`, and `clone_tdlib_pool.py`.
- **Pool Scaling:** Manages multiple independent Telegram client sessions across SQLite databases:
  ```python
  TDLIB_USER_DB_PATHS = [
      "tdlib_user_2", "tdlib_user_3", "tdlib_user_4", "tdlib_user_5",
      "tdlib_user_6_2", "tdlib_user_7", "tdlib_user_8", "tdlib_user_9", "tdlib_user_11"
  ]
  ```
- **Round-Robin Execution:** Upload jobs acquire `_pool_lock` and round-robin through active, authenticated TDLib clients to bypass per-connection Telegram bandwidth throttling and support up to 4 GB per file upload.
- **TDJson Compatibility:** Includes runtime C-FFI wrapper `_patch_tdjson_binding()` to normalize string and bytes signatures across varied `libtdjson.so` builds.

---

## 3. Storage & Partition Topology

```
/dev/vda4 (Dedicated partition) -> Mounted on /srv/bot-storage (or /path/to/storage)
├── docker/                                # Docker rootfs and overlay volumes
├── backups/                               # System and database snapshots
└── fuse_bot/                              # Bind-mounted host root for FUSE container
    ├── downloads/                         # Active task working directories (/app/downloads)
    ├── accounts/                          # Google Drive Service Account JSON keys (0.json .. 30.json)
    ├── thumbnails/                        # Leech custom thumbnail storage
    ├── tokens/                            # User-specific OAuth tokens
    ├── qBittorrent/                       # Torrent state, resume files & session config
    ├── sabnzbd/                           # Usenet NZB temporary & completed downloads
    ├── token.pickle                       # Google Drive API v3 OAuth token
    ├── credentials.json                   # Google Cloud Project client credentials
    ├── cookies.txt                        # Netscape cookie jar for premium index downloads
    └── .netrc                             # Authentication tokens for external HTTP resolvers
```

---

## 4. Key Operational Runbooks

### 4.1 Synchronizing Code & Restarting the FUSE Bot
```bash
# 1. Verify syntax of modified source files
python3 -m py_compile /root/Anasy-RSS-MHJoyBots-FUSE/bot/modules/zip_selector.py \
                      /root/Anasy-RSS-MHJoyBots-FUSE/bot/helper/listeners/task_listener.py \
                      /root/Anasy-RSS-MHJoyBots-FUSE/bot/helper/common.py \
                      /root/Anasy-RSS-MHJoyBots-FUSE/bot/core/handlers.py

# 2. Synchronize files into running container
docker cp /root/Anasy-RSS-MHJoyBots-FUSE/bot/modules/zip_selector.py anasy-rss-mhjoybots-fuse-app-1:/app/bot/modules/zip_selector.py
docker cp /root/Anasy-RSS-MHJoyBots-FUSE/bot/helper/listeners/task_listener.py anasy-rss-mhjoybots-fuse-app-1:/app/bot/helper/listeners/task_listener.py
docker cp /root/Anasy-RSS-MHJoyBots-FUSE/bot/helper/common.py anasy-rss-mhjoybots-fuse-app-1:/app/bot/helper/common.py
docker cp /root/Anasy-RSS-MHJoyBots-FUSE/bot/core/handlers.py anasy-rss-mhjoybots-fuse-app-1:/app/bot/core/handlers.py

# 3. Purge bytecode caches and restart container
docker exec anasy-rss-mhjoybots-fuse-app-1 find /app/bot -name "__pycache__" -exec rm -rf {} +
docker restart anasy-rss-mhjoybots-fuse-app-1

# 4. Verify clean boot in logs
sleep 4
docker logs anasy-rss-mhjoybots-fuse-app-1 --tail 30 | grep "Bot Started"
```

### 4.2 Tailing Live Logs
```bash
docker logs anasy-rss-mhjoybots-fuse-app-1 --tail 100 --follow | grep -E "Aria2Download|onDownloadComplete|FUSE extract|Zip picker|Streaming split|Telegram upload|Leech Completed|Leech mode"
```

### 4.3 Emergency FUSE Unmount & Space Recovery
```bash
# Unmount all active archivemount points
docker exec anasy-fuse-bot bash -c 'for m in $(grep archivemount /proc/mounts | awk "{print \$2}"); do fusermount -uz "$m"; done'

# Clean host task downloads directory
rm -rf /srv/bot-storage/fuse_bot/downloads/* # or /path/to/storage/fuse_bot/downloads/*

# Verify free disk space
df -h /srv/bot-storage
```
