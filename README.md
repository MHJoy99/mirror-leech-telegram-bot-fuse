# ⚡ Anasy-RSS-MHJoyBots-FUSE

```
   █████╗ ███╗   ██╗ █████╗ ███████╗██╗   ██╗     ███████╗██╗   ██╗███████╗███████╗
  ██╔══██╗████╗  ██║██╔══██╗██╔════╝╚██╗ ██╔╝     ██╔════╝██║   ██║██╔════╝██╔════╝
  ███████║██╔██╗ ██║███████║███████╗ ╚████╔╝█████╗█████╗  ██║   ██║███████╗█████╗  
  ██╔══██║██║╚██╗██║██╔══██║╚════██║  ╚██╔╝ ╚════╝██╔══╝  ██║   ██║╚════██║██╔══╝  
  ██║  ██║██║ ╚████║██║  ██║███████║   ██║        ██║     ╚██████╔╝███████║███████╗
  ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝   ╚═╝        ╚═╝      ╚═════╝ ╚══════╝╚══════╝
                                                      
              🚀 High-Performance Cloud Mirror, Leech & FUSE Engine
                   Zero-Double-Storage • TDLib Pool • WZML Media
```

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Engine-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![FUSE](https://img.shields.io/badge/FUSE-archivemount-FF6B6B?style=for-the-badge&logo=linux&logoColor=white)](https://en.wikipedia.org/wiki/Filesystem_in_Userspace)
[![AsyncIO](https://img.shields.io/badge/AsyncIO-Concurrency-4EBA6F?style=for-the-badge&logo=fastapi&logoColor=white)](https://docs.python.org/3/library/asyncio.html)
[![Telegram](https://img.shields.io/badge/Telegram-Pyrogram%20v2-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://telegram.org/)
[![TDLib Pool](https://img.shields.io/badge/TDLib-Multi--Session%20Pool-0088CC?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/tdlib)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge&logo=gnu&logoColor=white)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active%20Production-success?style=for-the-badge&logo=statuspage&logoColor=white)](https://github.com/MHJoy99/Anasy-motion-new)

*Next-generation Telegram mirror & leech platform powered by Linux FUSE virtual filesystems, on-the-fly streaming extractors, multi-session TDLib upload concurrency, and automated secondary Google Drive replication.*

[Features](#-key-features) • [Architecture](#-architecture--dataflow) • [Feature Matrix](#-feature-matrix) • [Quickstart](#-quickstart--deployment) • [Configuration](#-configuration) • [Runbook & Operations](#-operational-runbook) • [FAQ](#-frequently-asked-questions)

---

</div>

## 🌟 Overview

**Anasy-RSS-MHJoyBots-FUSE** is an advanced fork of the `python-aria-mirror-bot` / `mirror-leech-telegram-bot` ecosystem, re-architected to solve the classic **"Double-Storage Bottleneck"** on constrained VPS storage. 

Instead of downloading an archive (e.g., a 35GB `.zip` / `.tar` / `.7z`) and fully decompressing it to disk—requiring 70GB+ peak space—the bot mounts archives dynamically into the Linux VFS using `archivemount` (`readonly,nosave`). Combined with an **interactive Telegram inline ZIP picker** and **per-file streaming upload pipelines**, archives are inspected and dispatched directly to Telegram or Google Drive with near-zero disk overhead.

---

## ✨ Key Features

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                                                                  │
│   💽 FUSE Zero-Double-Storage Engine      🎛️ Inline Telegram ZIP Picker GUI     │
│   Mounts multi-GB archives directly       Interactive UI with checkboxes,        │
│   via Linux VFS (readonly,nosave).        pagination, selective file download.   │
│                                                                                  │
│   ⚡ TDLib Multi-Session Pool Concurrency 🔄 Dual Telegram Leech + GDrive Backup│
│   Round-robin account pooling with        Leech directly to Telegram and auto-   │
│   parallel part-upload acceleration.      backup completed artifacts to Drive.   │
│                                                                                  │
│   🎬 Smart WZML Dynamic Captioning        🔌 Universal Protocol Engines          │
│   Instant ffprobe metadata, audio &       aria2c, qBittorrent, Sabnzbd (NZB),    │
│   subtitle audio tag deduction.           JDownloader2, yt-dlp, Mega & Rclone.   │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

- **💽 FUSE Zero-Double-Storage Engine**: Utilizes Linux FUSE `archivemount` daemon mode to expose archive contents in milliseconds without physical disk extraction.
- **🎛️ Telegram Inline ZIP Picker GUI**: Run `/leech <link> -e -s` to get an interactive Telegram button menu showing all contained files, sizes, multi-page pagination, and fast toggle controls.
- **⚡ TDLib Multi-Session Pool**: Overcomes Telegram client rate limits by distributing multi-part split uploads across a scalable cluster of authenticated TDLib user accounts.
- **🔄 Dual Telegram Leech + GDrive Backup**: Dispatches your primary leech to Telegram chats/channels while concurrently replicating the final post-processed artifacts into Google Drive in the background.
- **🎬 Smart WZML Media Captioning**: Auto-probes video/audio codecs, audio language tracks, and embedded/external subtitle streams via `ffprobe` and `langcodes` with fallback heuristics.
- **🌐 5+ Download Backends**: Full native integration with `aria2c`, `qBittorrent` (with search plugins and web UI sync), `Sabnzbd` (Usenet / NZB), `JDownloader`, and `yt-dlp`.
- **☁️ Comprehensive Cloud Sync**: Rclone remotes, Google Drive service account cycling, Team Drive support, and custom upload destinations.

---

## 🏗️ Architecture & Dataflow

### FUSE Virtual Mount & Streaming Upload Pipeline

```
  [ User Command: /leech <url> -e -s ]
                   │
                   ▼
     ┌───────────────────────────┐
     │   aria2c / qBittorrent    │ ───▶ Downloads archive (e.g. 33GB ZIP)
     └───────────────────────────┘
                   │
                   ▼
     ┌───────────────────────────┐
     │   FUSE `archivemount`     │ ───▶ Virtual VFS Mount (.mnt_xxx)
     │   (readonly, nosave)      │      [ZERO disk extraction penalty]
     └───────────────────────────┘
                   │
                   ▼
     ┌───────────────────────────┐
     │  Inline Telegram Picker   │ ◀─── Interactive TG Button Interface
     │  (zip_selector.py)        │      User picks: Ep 01, Ep 02, Ep 03...
     └───────────────────────────┘
                   │
                   ▼
     ┌───────────────────────────────────────────────────────────┐
     │         Per-File Streaming Split & Upload Engine          │
     │                                                           │
     │   For each selected file in FUSE mount:                   │
     │   1. Read stream from VFS                                 │
     │   2. If size > 2GB (or 4GB Premium), split on-the-fly     │
     │   3. TDLib Session Pool / Pyrogram Multi-Worker Upload    │
     │   4. Generate WZML ffprobe metadata captions              │
     │   5. Transmit file to Telegram Destination Channel        │
     │   6. Immediately delete temporary split chunk             │
     └───────────────────────────────────────────────────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
┌──────────────────┐ ┌───────────────────────────────────────┐
│ Telegram Primary │ │ Secondary Google Drive Backup (Async) │
└──────────────────┘ └───────────────────────────────────────┘
         │                   │
         └─────────┬─────────┘
                   ▼
     ┌───────────────────────────┐
     │   `fusermount -uz` &      │ ───▶ Complete Disk Cleanup
     │   Clean Workspace         │      [Disk usage returns to baseline]
     └───────────────────────────┘
```

---

## 📊 Feature Matrix

| Feature | Upstream MLTB | Anasy-RSS-MHJoyBots-FUSE | Performance / Benefit |
| :--- | :---: | :---: | :--- |
| **Archive Handling** | Full Extraction (`7z x`) | **Linux FUSE (`archivemount`)** | **50% Disk Savings**, Zero double-storage |
| **Archive Selection** | CLI flags / all-or-nothing | **Native Telegram Inline GUI** | Multi-page pagination, file toggle, size previews |
| **Large File Splitting** | Extract all ➡️ Split all | **Per-file Streaming Split & Delete** | Minimal transient disk spikes (<2.5GB) |
| **Telegram Upload Core** | Single Client (Pyrogram/TDLib) | **TDLib Multi-Session Pool** | Round-robin load balancing & high throughput |
| **Leech Destinations** | Telegram OR Cloud | **Dual Telegram + GDrive Backup** | Redundant storage with independent failure safety |
| **Media Captions** | Static text templates | **Smart WZML ffprobe Engine** | Codecs, duration, audio language, subtitles |
| **Download Engines** | aria2, qBit, Sabnzbd | **aria2, qBit, Sabnzbd, JD2, yt-dlp** | Total web/torrent/usenet/stream coverage |
| **Cloud Integration** | GDrive / Rclone | **GDrive OAuth + SA + Rclone** | Automated token rotation & duplicate guards |

---

## 🎛️ Interactive ZIP Picker GUI

When triggering an extraction leech task with the selective flag `-s` (`/leech <archive_url> -e -s`), the bot mounts the archive and generates an interactive Telegram button grid:

```
┌────────────────────────────────────────────────────────┐
│ <b>Select files from ZIP</b>                                │
│ Selected: 3/16 (5.8 GB / 33.2 GB)                      │
│ Page 1/2                                               │
│ Tap to toggle. Done to continue (auto Done in 60s).    │
│                                                        │
│ [x] The.K2.S01E01.1080p.NF.WEB-DL.mkv (1.9 GB)         │
│ [x] The.K2.S01E02.1080p.NF.WEB-DL.mkv (1.9 GB)         │
│ [x] The.K2.S01E03.1080p.NF.WEB-DL.mkv (2.0 GB)         │
│ [ ] The.K2.S01E04.1080p.NF.WEB-DL.mkv (1.9 GB)         │
├────────────────────────────────────────────────────────┤
│  [ ✅ Ep 01 (1.9 GB) ]     [ ✅ Ep 02 (1.9 GB) ]       │
│  [ ✅ Ep 03 (2.0 GB) ]     [ ⬜ Ep 04 (1.9 GB) ]       │
│  [ ◀ Prev Page ]           [ Next Page ▶ ]             │
│  [ 🔘 Select All ]         [ ⚪ Deselect All ]          │
│  [ ✅ Done (Start Leech) ] [ ❌ Cancel Task ]          │
└────────────────────────────────────────────────────────┘
```

---

## 🎬 Smart WZML Dynamic Captioning

The integrated media probe automatically parses stream information with `ffprobe`, resolves standard language tags to clean localized names using `langcodes`, and renders elegant captions for Telegram video cards and documents:

```
{filename}
{size}
🕒 {duration} | 🔊 {languages}
📄 SUBTITLES : {subtitles}
```

#### Real-World Example:
```text
The.K2.S01E01.1080p.NF.WEB-DL.DDP2.0.H.264.mkv
1.94 GB
🕒 01:04:12 | 🔊 Korean [Original], English
📄 SUBTITLES : English, Spanish, French, Bengali
```

---

## 🚀 Quickstart & Deployment

### Prerequisites
- Host OS: Linux (Ubuntu 22.04 / 24.04 LTS or Debian 12 recommended)
- Docker & Docker Compose v2 installed
- Kernel FUSE support enabled (`/dev/fuse`)

### 1. Clone Repository & Setup Structure

```bash
git clone https://github.com/MHJoy99/Anasy-motion-new.git /root/Anasy-RSS-MHJoyBots-FUSE
cd /root/Anasy-RSS-MHJoyBots-FUSE
```

### 2. Configure Environment Variables

Copy the sample configuration file and populate your credentials:

```bash
cp config_sample.py config.py
nano config.py
```

Essential parameters in `config.py` / `config.env`:

```python
# Required Bot Identity
BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
OWNER_ID = 987654321
TELEGRAM_API = 1234567
TELEGRAM_HASH = "0123456789abcdef0123456789abcdef"

# TDLib High-Speed Upload Settings
TDLIB_API_ID = 1234567
TDLIB_API_HASH = "0123456789abcdef0123456789abcdef"
TDLIB_USER_DB_PATH = "tdlib_user"
TDLIB_USER_DB_PATHS = ["tdlib_user_2", "tdlib_user_3"]
TDLIB_USER_UPLOAD = True

# Storage & Concurrency Optimization
TG_FILE_UPLOAD_CONCURRENCY = 8
TG_SPLIT_UPLOAD_CONCURRENCY = 4
TG_UPLOAD_WORKERS = 16
LEECH_SPLIT_SIZE = 2097152000  # 2GB standard (or 4GB for Telegram Premium)
```

### 3. Setup TDLib Multi-Session Pool (Optional but Recommended)

To maximize upload throughput and avoid account-level flood waits, initialize secondary TDLib session databases:

```bash
python3 setup_tdlib_pool.py 3 /root/Anasy-RSS-MHJoyBots-FUSE/tdlib_user
```

### 4. Docker Compose Launch

Ensure `/dev/fuse` and `SYS_ADMIN` capabilities are enabled in `docker-compose.yml`:

```yaml
services:
  app:
    build: .
    command: bash start.sh
    restart: on-failure
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined
    volumes:
      - /srv/bot-storage/fuse_bot/downloads:/app/downloads
      - /srv/bot-storage/fuse_bot/accounts:/app/accounts
      - /srv/bot-storage/fuse_bot/thumbnails:/app/thumbnails
      - /srv/bot-storage/fuse_bot/tokens:/app/tokens
      - /srv/bot-storage/fuse_bot/rclone:/app/rclone
      - /srv/bot-storage/fuse_bot/qBittorrent:/app/qBittorrent
      - /srv/bot-storage/fuse_bot/sabnzbd:/app/sabnzbd
      - /srv/bot-storage/fuse_bot/token.pickle:/app/token.pickle
      - /srv/bot-storage/fuse_bot/credentials.json:/app/credentials.json
      - /srv/bot-storage/fuse_bot/cookies.txt:/app/cookies.txt
      - /srv/bot-storage/fuse_bot/.netrc:/app/.netrc
```

Build and run:

```bash
docker compose up -d --build
```

---

## 🔧 Operational Runbook

### Core Service Control

```bash
# View live container logs
docker compose logs -f app

# Follow upload stream events
docker compose logs --tail=100 -f | grep -E "FUSE|archivemount|Upload|Leech"

# Restart bot instance
docker compose restart app

# Stop bot instance
docker compose down
```

### FUSE Diagnostic & Unmount Helpers

If an abnormal process abort leaves lingering FUSE mountpoints, inspect and release them:

```bash
# Check active FUSE mounts
grep "archivemount" /proc/mounts

# Force unmount a stuck mountpoint
fusermount -uz /app/downloads/*/.mnt_*

# Verify available disk headroom
df -h /
```

### Bot Commands Reference

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/leech` | `<link>` | Standard download and upload to Telegram |
| `/leech` | `<link> -e` | Download, extract archive via FUSE, and leech all files |
| `/leech` | `<link> -e -s` | Download, FUSE mount, and display **Inline ZIP Picker** |
| `/mirror` | `<link>` | Download and upload to Google Drive or Rclone remote |
| `/ytdl` | `<link>` | Download video/audio via `yt-dlp` and leech/mirror |
| `/status` | — | Display real-time progress, speed, ETA, and active engines |
| `/cancel` | `<gid>` or `all` | Cancel specific tasks or terminate all active transfers |
| `/bsettings` | — | Open global bot settings and engine parameter configurations |
| `/usettings` | — | Open user-level preferences (custom captions, split sizes, prefixes) |

---

## ❓ Frequently Asked Questions

<details>
<summary><b>Q: How does FUSE prevent double storage on large ZIPs?</b></summary>
<br>
Standard bots decompress the entire archive to disk using <code>7z x</code>, duplicating the space required (e.g., 30GB ZIP + 30GB uncompressed = 60GB). FUSE mounts the archive directly to a virtual directory in read-only mode. Files are read on-the-fly and uploaded sequentially, capping disk usage at just the ZIP file size plus one active split chunk (~2GB).
</details>

<details>
<summary><b>Q: What happens if a file inside the archive is larger than 2GB?</b></summary>
<br>
The streaming engine reads the file from the FUSE mount, generates parts into a temporary directory (<code>&lt;archive&gt;_splits/</code>), uploads the parts in parallel via the TDLib pool, and immediately purges each chunk to keep disk usage flat.
</details>

<details>
<summary><b>Q: How does Dual Leech + Google Drive Backup work?</b></summary>
<br>
When configured, after the Telegram upload completes successfully, the bot automatically uploads the processed files to your configured Google Drive folder. If Google Drive encounters quota issues or fails, the primary Telegram upload remains unaffected and marked as successful.
</details>

<details>
<summary><b>Q: Why use a TDLib multi-session pool instead of Pyrogram?</b></summary>
<br>
Telegram enforces strict per-account upload concurrency and floodwait limits. By distributing chunk uploads across a pool of authenticated user sessions via TDLib, total upload throughput scales linearly and eliminates bottlenecks.
</details>

---

## 📜 License & Credits

- **License**: GNU General Public License v3.0 ([GPL-3.0](LICENSE))
- **Base Project**: [python-aria-mirror-bot](https://github.com/lzzy12/python-aria-mirror-bot) / [mirror-leech-telegram-bot](https://github.com/anasty17/mirror-leech-telegram-bot)
- **FUSE Architecture & Enhancements**: Maintained by [MHJoy99](https://github.com/MHJoy99) & the **MHJoyBots** engineering team.
