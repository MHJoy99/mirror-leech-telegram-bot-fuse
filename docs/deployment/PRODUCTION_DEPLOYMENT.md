# Anasy-RSS-MHJoyBots-FUSE Deployment & Operations Guide

Comprehensive production deployment, configuration, resource allocation, and troubleshooting guide for **Anasy-RSS-MHJoyBots-FUSE** running on Linux VPS host environments with Docker, FUSE (`archivemount`), and Systemd management.

---

## Table of Contents

1. [Architectural Overview](#1-architectural-overview)
2. [Section 1: Docker Compose Setup & FUSE Capabilities](#section-1-docker-compose-setup--fuse-capabilities)
   - [1.1 Why SYS_ADMIN & /dev/fuse Are Required](#11-why-sys_admin--devfuse-are-required)
   - [1.2 AppArmor Security Profile](#12-apparmor-security-profile)
   - [1.3 Complete Production docker-compose.yml](#13-complete-production-docker-composeyml)
   - [1.4 Dockerfile Structure & FUSE Packages](#14-dockerfile-structure--fuse-packages)
3. [Section 2: VPS Host Storage & Volume Permissions](#section-2-vps-host-storage--volume-permissions)
   - [2.1 Dedicated Disk Partition Layout (/dev/vda4 -> /srv/bot-storage)](#21-dedicated-disk-partition-layout-devvda4---srvbot-storage)
   - [2.2 Directory Hierarchy & Purpose](#22-directory-hierarchy--purpose)
   - [2.3 Permission Matrix & Ownership (UID/GID)](#23-permission-matrix--ownership-uidgid)
   - [2.4 Host Storage Provisioning Script](#24-host-storage-provisioning-script)
4. [Section 3: Systemd Service for Container Automation](#section-3-systemd-service-for-container-automation)
   - [3.1 Systemd Unit File Configuration](#31-systemd-unit-file-configuration)
   - [3.2 Service Lifecycle & Auto-Restart Policies](#32-service-lifecycle--auto-restart-policies)
   - [3.3 Enabling, Starting, and Managing the Service](#33-enabling-starting-and-managing-the-service)
5. [Section 4: Resource Limits, iptables & Port Allocation](#section-4-resource-limits-iptables--port-allocation)
   - [4.1 Container Resource Limits (CPU & Memory Ceilings)](#41-container-resource-limits-cpu--memory-ceilings)
   - [4.2 VPS Port Allocation & Conflict Prevention](#42-vps-port-allocation--conflict-prevention)
   - [4.3 iptables & UFW Firewall Rules](#43-iptables--ufw-firewall-rules)
6. [Section 5: Step-by-Step First-Time Deployment Runbook](#section-5-step-by-step-first-time-deployment-runbook)
   - [5.1 Phase 1: Host Preparation & Kernel Module Verification](#51-phase-1-host-preparation--kernel-module-verification)
   - [5.2 Phase 2: Environment Variables & Secrets Configuration](#52-phase-2-environment-variables--secrets-configuration)
   - [5.3 Phase 3: Building and Starting the Container](#53-phase-3-building-and-starting-the-container)
   - [5.4 Phase 4: Full Verification Matrix (FUSE, Mounts, Storage, Logs)](#54-phase-4-full-verification-matrix-fuse-mounts-storage-logs)
   - [5.5 Phase 5: Systemd Service Integration Verification](#55-phase-5-systemd-service-integration-verification)
7. [Section 6: Day-2 Operations, Updates & Troubleshooting](#section-6-day-2-operations-updates--troubleshooting)
   - [6.1 Safe Update Workflow (Code Sync vs Container Recreation)](#61-safe-update-workflow-code-sync-vs-container-recreation)
   - [6.2 Cleaning Stale FUSE Mounts](#62-cleaning-stale-fuse-mounts)
   - [6.3 Disaster Recovery & Rollback Procedure](#63-disaster-recovery--rollback-procedure)

---

## 1. Architectural Overview

The **Anasy-RSS-MHJoyBots-FUSE** service is a high-throughput Telegram Mirror/Leech bot built on top of Python 3, Pyrogram/Telethon, aria2c, qBittorrent, and SABnzbd.

```
+-----------------------------------------------------------------------------------+
| Linux Host VPS (Dedicated ext4 partition mounted at /srv/bot-storage or custom)   |
|                                                                                   |
|  /srv/bot-storage/fuse_bot/ (or /path/to/storage/fuse_bot/)                       |
|    |-- downloads/ <==================== bind mount ====================\          |
|    |-- accounts/, tokens/, rclone/                                     |          |
|    +-- cookies.txt, credentials.json, token.pickle                     |          |
|                                                                        |          |
|  +---------------------------------------------------------------------+-------+  |
|  | Docker Container: anasy-fuse-bot (or mltb-container)                         |  |
|  | (Capabilities: CAP_SYS_ADMIN, Device: /dev/fuse, AppArmor: unconfined)       |  |
|  |                                                                             |  |
|  |  /app/downloads/ <----------------------------------------------------------+  |
|  |    |-- <task_id>/<archive.zip> (Downloaded archive, e.g. 33GB)               |  |
|  |    |                                                                        |  |
|  |    +-- .mnt_<archive>_zip_<pid>/ <--- archivemount (FUSE VFS)               |  |
|  |          |-- E01.mkv (2.5GB) ---> streamed & split on-the-fly -> Telegram   |  |
|  |          |-- E02.mkv (2.5GB)                                                |  |
|  |          +-- E03.mkv (1.8GB) ---> direct upload single file                 |  |
|  |                                                                             |  |
|  |  Peak Disk Usage = Size(ZIP) + Size(Single Split Part ~2.4GB)               |  |
|  |  Eliminates the 2x full extraction disk footprint entirely.                |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## Section 1: Docker Compose Setup & FUSE Capabilities

### 1.1 Why SYS_ADMIN & /dev/fuse Are Required

FUSE (Filesystem in Userspace) allows non-privileged programs to implement virtual filesystems. When mounting archives via `archivemount`:
1. The kernel delegates filesystem operations (`stat`, `read`, `open`) to the `archivemount` process via the `/dev/fuse` character device.
2. Inside Docker, container processes cannot access host character devices unless explicitly permitted via the `devices:` directive.
3. Invoking the `mount()` system call inside a Linux mount namespace requires the `CAP_SYS_ADMIN` Linux capability.

Without both flags:
- `archivemount` fails with: `fuse: device not found, try 'modprobe fuse'` or `fusermount: mount failed: Operation not permitted`.

### 1.2 AppArmor Security Profile

Modern Linux distributions (Ubuntu, Debian) enforce default AppArmor profiles on Docker containers (`docker-default`). This default profile explicitly blocks the `mount` syscall family inside containers even if `CAP_SYS_ADMIN` is passed.

Setting `security_opt: ["apparmor:unconfined"]` disables this restriction for the container, enabling clean mount/unmount operations without running in full `--privileged` mode.

### 1.3 Complete Production docker-compose.yml

Save the following file to `/root/Anasy-RSS-MHJoyBots-FUSE/docker-compose.yml`:

```yaml
version: "3.8"

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: anasy-rss-mhjoybots-fuse-app-1
    command: bash start.sh
    restart: on-failure:5
    
    # 1. Privileges & Devices for FUSE
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse:/dev/fuse
    security_opt:
      - apparmor:unconfined

    # 2. Resource Constraints
    deploy:
      resources:
        limits:
          cpus: "4.0"
          memory: 4096M
        reservations:
          cpus: "0.5"
          memory: 512M

    # 3. Environment Configuration
    env_file:
      - config.env

    # 4. Host Storage Bind Mounts
    volumes:
      # Data & Working Directories
      - /srv/bot-storage/fuse_bot/downloads:/app/downloads
      - /srv/bot-storage/fuse_bot/accounts:/app/accounts
      - /srv/bot-storage/fuse_bot/thumbnails:/app/thumbnails
      - /srv/bot-storage/fuse_bot/tokens:/app/tokens
      - /srv/bot-storage/fuse_bot/rclone:/app/rclone
      - /srv/bot-storage/fuse_bot/qBittorrent:/app/qBittorrent
      - /srv/bot-storage/fuse_bot/sabnzbd:/app/sabnzbd
      
      # Authentication & State Files
      - /srv/bot-storage/fuse_bot/token.pickle:/app/token.pickle
      - /srv/bot-storage/fuse_bot/credentials.json:/app/credentials.json
      - /srv/bot-storage/fuse_bot/cookies.txt:/app/cookies.txt
      - /srv/bot-storage/fuse_bot/.netrc:/app/.netrc

    # 5. Logging Configuration (Prevent disk exhaustion from stdout)
    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"

    # 6. Networking
    network_mode: bridge
```

### 1.4 Dockerfile Structure & FUSE Packages

The container image must include `archivemount` and `fuse` packages along with the Python runtime dependencies.

Location: `/root/Anasy-RSS-MHJoyBots-FUSE/Dockerfile`

```dockerfile
FROM anasty17/mltb:latest

WORKDIR /app
RUN chmod 777 /app

# Create virtual environment
RUN python3 -m venv mltbenv

# Install Python dependencies
COPY requirements.txt .
RUN mltbenv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Fix line endings
RUN sed -i 's/\r$//' *.sh

# Install FUSE and archivemount binaries
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    archivemount \
    fuse \
    libfuse2 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

CMD ["bash", "start.sh"]
```

---

## Section 2: VPS Host Storage & Volume Permissions

### 2.1 Dedicated Disk Partition Layout (e.g. `/dev/vda4` -> `/srv/bot-storage` or `/path/to/storage`)

To prevent Telegram downloads from consuming root partition (`/`) disk space and causing VPS crashes, a dedicated storage volume is mounted:

- **Block Device:** `/dev/vda4` (ext4) or dedicated disk partition
- **Mount Point:** `/srv/bot-storage` (or custom path like `/path/to/storage`)
- **Total Capacity:** Dedicated partition sizing (e.g. 84 GiB+)
- **fstab Entry Example (`/etc/fstab`):**
  ```fstab
  UUID=your-partition-uuid-here /srv/bot-storage ext4 defaults,nofail,noatime 0 2
  ```

### 2.2 Directory Hierarchy & Purpose

The bot root directory on host storage is `/srv/bot-storage/fuse_bot/` (or `/path/to/storage/fuse_bot/`).

```
/srv/bot-storage/fuse_bot/
|-- accounts/          # Service Account JSONs for Google Drive team drives
|-- cookies.txt        # Netscape format cookies for aria2/yt-dlp
|-- credentials.json   # Google OAuth client ID & client secret
|-- downloads/         # Working directory for downloads, FUSE mounts, and splits
|-- .netrc             # Credentials for authenticated HTTP/FTP endpoints
|-- qBittorrent/       # qBittorrent session state and torrent fastresume files
|-- rclone/            # rclone.conf configuration file
|-- sabnzbd/           # SABnzbd Usenet download state and configuration
|-- thumbnails/        # Custom video/document thumbnail images
|-- token.pickle       # User Google Drive OAuth token serialization
+-- tokens/            # Multiple OAuth token store
```

### 2.3 Permission Matrix & Ownership (UID/GID)

The container executes as root (`UID=0, GID=0`) inside the container by default, but downloader engines (e.g., aria2c, qBittorrent) and FUSE sub-processes require broad read/write access.

| Path | Required Perms | Recommended Owner | Purpose |
|---|---|---|---|
| `/srv/bot-storage/fuse_bot` | `0755` | `root:root` | Storage container root |
| `fuse_bot/downloads` | `0777` (`rwxrwxrwx`) | `root:root` | Write-heavy downloads & mount targets |
| `fuse_bot/accounts` | `0777` | `root:root` | Multi-SA JSON pool directory |
| `fuse_bot/thumbnails` | `0755` | `root:root` | Persistent thumbnail store |
| `fuse_bot/tokens` | `0755` | `root:root` | Persistent token store |
| `fuse_bot/rclone` | `0755` | `root:root` | rclone config directory |
| `fuse_bot/qBittorrent` | `0755` | `root:root` | qBittorrent database |
| `fuse_bot/sabnzbd` | `0755` | `root:root` | SABnzbd database |
| `fuse_bot/token.pickle` | `0644` | `root:root` | OAuth pickle |
| `fuse_bot/credentials.json` | `0644` | `root:root` | OAuth credentials |
| `fuse_bot/cookies.txt` | `0644` | `root:root` | Netscape cookies |
| `fuse_bot/.netrc` | `0600` (`rw-------`) | `root:root` | Private authentication |

### 2.4 Host Storage Provisioning Script

Run this bash snippet on the host before launching the container for the first time:

```bash
#!/usr/bin/env bash
set -euo pipefail

STORAGE_ROOT="/srv/bot-storage/fuse_bot"

echo "[1/4] Verifying /srv/bot-storage mount..."
if ! mountpoint -q /srv/bot-storage; then
    echo "WARNING: /srv/bot-storage is not mounted as a separate mountpoint. Creating directory locally..."
fi

echo "[2/4] Creating directory structure at ${STORAGE_ROOT}..."
mkdir -p "${STORAGE_ROOT}/downloads"
mkdir -p "${STORAGE_ROOT}/accounts"
mkdir -p "${STORAGE_ROOT}/thumbnails"
mkdir -p "${STORAGE_ROOT}/tokens"
mkdir -p "${STORAGE_ROOT}/rclone"
mkdir -p "${STORAGE_ROOT}/qBittorrent"
mkdir -p "${STORAGE_ROOT}/sabnzbd"

echo "[3/4] Initializing required placeholder files..."
touch "${STORAGE_ROOT}/cookies.txt"
touch "${STORAGE_ROOT}/credentials.json"
touch "${STORAGE_ROOT}/token.pickle"
touch "${STORAGE_ROOT}/.netrc"

echo "[4/4] Setting permissions..."
chmod -R 755 "${STORAGE_ROOT}"
chmod 777 "${STORAGE_ROOT}/downloads"
chmod 777 "${STORAGE_ROOT}/accounts"
chmod 600 "${STORAGE_ROOT}/.netrc"
chmod 644 "${STORAGE_ROOT}/cookies.txt" "${STORAGE_ROOT}/credentials.json" "${STORAGE_ROOT}/token.pickle"

echo "Host storage structure successfully verified and provisioned."
```

---

## Section 3: Systemd Service for Container Automation

To guarantee automatic recovery across host reboots, kernel updates, or unexpected container exits, manage the Docker Compose project with a dedicated systemd unit.

### 3.1 Systemd Unit File Configuration

Create `/etc/systemd/system/anasy-rss-mhjoybots-fuse.service`:

```ini
[Unit]
Description=Anasy RSS MHJoyBots FUSE Docker Compose Service
Requires=docker.service
After=docker.service network-online.target local-fs.target
Wants=network-online.target
ConditionPathIsMountPoint=/srv/bot-storage

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/root/Anasy-RSS-MHJoyBots-FUSE

# Ensure kernel module is loaded
ExecStartPre=/usr/sbin/modprobe fuse

# Verify mount point is accessible
ExecStartPre=/usr/bin/findmnt /srv/bot-storage

# Start containers
ExecStart=/usr/bin/docker compose up -d --remove-orphans

# Stop containers gracefully on shutdown
ExecStop=/usr/bin/docker compose down --timeout 30

# Reload / Restart
ExecReload=/usr/bin/docker compose restart

# Process Management
TimeoutStartSec=180
TimeoutStopSec=60
Restart=no

[Install]
WantedBy=multi-user.target
```

### 3.2 Service Lifecycle & Auto-Restart Policies

1. **`ConditionPathIsMountPoint=/srv/bot-storage`**: Prevents the service from starting if the secondary storage disk failed to mount, avoiding accidental writes to the host root partition.
2. **`ExecStartPre=/usr/sbin/modprobe fuse`**: Ensures `/dev/fuse` is registered in the host kernel before Docker attempts to bind-mount the device.
3. **`Restart=on-failure:5` in compose**: Handles transient Python crashes internally. Systemd handles host-level reboots.

### 3.3 Enabling, Starting, and Managing the Service

```bash
# 1. Reload systemd daemon
systemctl daemon-reload

# 2. Enable service on boot
systemctl enable anasy-rss-mhjoybots-fuse.service

# 3. Start service
systemctl start anasy-rss-mhjoybots-fuse.service

# 4. Check status
systemctl status anasy-rss-mhjoybots-fuse.service

# 5. View service logs
journalctl -u anasy-rss-mhjoybots-fuse.service -f
```

---

## Section 4: Resource Limits, iptables & Port Allocation

### 4.1 Container Resource Limits (CPU & Memory Ceilings)

FUSE archiving and ffmpeg video splitting are CPU and I/O intensive. Setting limits prevents the bot from starving other VPS services (Chatwoot, Search, Reverse Proxy).

```yaml
deploy:
  resources:
    limits:
      cpus: "4.0"           # Max 4 CPU cores
      memory: 4096M         # Max 4GB RAM (FUSE uses kernel buffers ~50MB)
    reservations:
      cpus: "0.5"           # Minimum 0.5 CPU core
      memory: 512M          # Minimum 512MB RAM
```

*Note on RAM behavior:* `archivemount` does **not** decompress the entire archive into RAM. It parses the central directory headers and streams bytes through kernel FUSE buffers on demand. 4GB is more than sufficient for high-speed multi-part uploads.

### 4.2 VPS Port Allocation & Conflict Prevention

The host runs multiple services. Verify port allocations to avoid collisions:

| Port / Protocol | Service | Bound To | Scope / Conflict Risk |
|---|---|---|---|
| `71/tcp` | Production Bot (`mltb-container`) | `0.0.0.0:71` | Host port used by legacy prod bot (if any). |
| `8071/tcp` | Production Bot Web (`mltb-container`) | `0.0.0.0:8071` | Host port used by legacy prod bot (if any). |
| `3000/tcp` | Chatwoot Rails App | `0.0.0.0:3000` | Public Webhook/UI |
| `5050/tcp` | Facebook Chatbot | `0.0.0.0:5050` | Public Webhook |
| `8080/tcp` | Sub2API / SearXNG | Internal Bridge | Container-to-container |
| `8086/tcp` | Sub2API Host Bridge | `127.0.0.1:8086` | Loopback only |
| `8087/tcp` | Reasoning Proxy | `127.0.0.1:8087` | Loopback only |
| `8090/tcp` | SearXNG Host Bridge | `127.0.0.1:8090` | Loopback only |
| `3001/tcp` | Uptime Kuma | `127.0.0.1:3001` | Loopback only |
| **No Host Ports** | **Anasy FUSE Bot** | **Docker Bridge** | **Uses Telegram Long Polling (MTProto outgoing). Does not require inbound published host ports.** |

*Important Rule:* If enabling web search or web dashboard inside `Anasy-RSS-MHJoyBots-FUSE` in the future:
- Map internal port `80` to an unassigned port like `127.0.0.1:8072:80` or `0.0.0.0:8072:80`.
- **Never** bind host port `71` or `8071` if another bot or service is already using those ports.

### 4.3 iptables & UFW Firewall Rules

Because the FUSE bot relies on outgoing HTTPS/WSS connections to Telegram MTProto data centers (`149.154.167.x:443`) and Google Drive APIs, standard Docker bridge egress is permitted.

#### Checking Docker & UFW Forwarding
```bash
# Verify UFW is active and default outgoing is allow
ufw status verbose

# Ensure Docker inter-bridge traffic is tracked
iptables -L FORWARD -n -v | grep DOCKER
```

#### Restricting Inbound Traffic (If Web UI Is Exposed Later)
```bash
# Example: Allow port 8072 only from Cloudflare IP ranges or local loopback
ufw allow from 127.0.0.1 to any port 8072 proto tcp
```

---

## Section 5: Step-by-Step First-Time Deployment Runbook

Follow these exact steps when provisioning the bot on a new host or migrating to a new VPS.

### 5.1 Phase 1: Host Preparation & Kernel Module Verification

```bash
# 1. Update package index and install host FUSE utilities
apt-get update
apt-get install -y fuse libfuse2 docker-compose-plugin

# 2. Check if the FUSE kernel module is active
lsmod | grep fuse

# If not loaded, load it:
modprobe fuse

# 3. Ensure the module loads automatically on boot
echo "fuse" | tee -a /etc/modules-load.d/fuse.conf

# 4. Verify /dev/fuse permissions
ls -la /dev/fuse
# Expected output: crw-rw-rw- 1 root fuse 10, 229 ... /dev/fuse
```

### 5.2 Phase 2: Environment Variables & Secrets Configuration

1. Navigate to the repository root:
   ```bash
   cd /root/Anasy-RSS-MHJoyBots-FUSE
   ```

2. Populate `config.env` with required variables:
   ```bash
   cat << 'EOF' > /root/Anasy-RSS-MHJoyBots-FUSE/config.env
   BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
   TELEGRAM_API = "1234567"
   TELEGRAM_HASH = "0123456789abcdef0123456789abcdef"
   OWNER_ID = "123456789"
   DATABASE_URL = "mongodb+srv://user:pass@cluster.mongodb.net/?appName=Cluster0"
   DOWNLOAD_DIR = "/app/downloads/"
   TORRENT_TIMEOUT = "300"
   AS_DOCUMENT = "False"
   EQUAL_SPLITS = "False"
   LEECH_SPLIT_SIZE = "2097152000"
   EXTENSION_FILTER = ""
   CMD_SUFFIX = ""
   EOF
   ```

3. Sync authentication credentials to host storage:
   ```bash
   cp /root/Anasy-RSS-MHJoyBots-FUSE/token.pickle /srv/bot-storage/fuse_bot/token.pickle
   cp /root/Anasy-RSS-MHJoyBots-FUSE/credentials.json /srv/bot-storage/fuse_bot/credentials.json
   cp /root/Anasy-RSS-MHJoyBots-FUSE/cookies.txt /srv/bot-storage/fuse_bot/cookies.txt
   cp /root/Anasy-RSS-MHJoyBots-FUSE/.netrc /srv/bot-storage/fuse_bot/.netrc
   ```

### 5.3 Phase 3: Building and Starting the Container

```bash
cd /root/Anasy-RSS-MHJoyBots-FUSE

# Build image without cache to guarantee fresh binary dependencies
docker compose build --no-cache

# Start container in detached mode
docker compose up -d
```

### 5.4 Phase 4: Full Verification Matrix (FUSE, Mounts, Storage, Logs)

Execute the following verification commands to certify operational readiness:

#### Verification 1: Container Status & Health
```bash
docker ps --filter name=anasy-rss-mhjoybots-fuse-app-1 --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}"
```
*Expected: Status is `Up ...`.*

#### Verification 2: Storage Volume Mounts
```bash
docker inspect anasy-rss-mhjoybots-fuse-app-1 --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```
*Expected: `/srv/bot-storage/fuse_bot/downloads -> /app/downloads` and related volumes appear.*

#### Verification 3: Disk Space & In-Container Mount Checks
```bash
docker exec anasy-rss-mhjoybots-fuse-app-1 df -h /app/downloads
```
*Expected: Shows `/dev/vda4` mounted with ~84G size and ~47G available.*

#### Verification 4: In-Container FUSE Capability Test
```bash
docker exec -it anasy-rss-mhjoybots-fuse-app-1 bash -c "which archivemount && ls -la /dev/fuse"
```
*Expected: `/usr/bin/archivemount` exists and `/dev/fuse` is accessible.*

#### Verification 5: Live Bot Startup Logs
```bash
docker logs anasy-rss-mhjoybots-fuse-app-1 --tail 50
```
*Expected logs:*
```text
Creating client from BOT_TOKEN
Cleaning Download Directory rm: cannot remove '/app/downloads/': Device or resource busy
Bot Started!
```

---

## Section 6: Day-2 Operations, Updates & Troubleshooting

### 6.1 Safe Update Workflow (Code Sync vs Container Recreation)

Because `/app/downloads` and configuration files are mounted from host directories, updating Python code can be performed with zero rebuild overhead or through clean image rebuilds:

#### Method A: Rapid Hot-Reload (Direct File Sync)
```bash
cd /root/Anasy-RSS-MHJoyBots-FUSE

# 1. Compile modified files on host
python3 -m py_compile bot/modules/zip_selector.py bot/helper/common.py

# 2. Copy updated files into running container
docker cp bot/modules/zip_selector.py anasy-rss-mhjoybots-fuse-app-1:/app/bot/modules/zip_selector.py
docker cp bot/helper/common.py anasy-rss-mhjoybots-fuse-app-1:/app/bot/helper/common.py
docker cp bot/helper/listeners/task_listener.py anasy-rss-mhjoybots-fuse-app-1:/app/bot/helper/listeners/task_listener.py
docker cp bot/core/handlers.py anasy-rss-mhjoybots-fuse-app-1:/app/bot/core/handlers.py

# 3. Clean in-container bytecode caches
docker exec anasy-rss-mhjoybots-fuse-app-1 rm -rf /app/bot/__pycache__ /app/bot/helper/__pycache__

# 4. Restart container
docker restart anasy-rss-mhjoybots-fuse-app-1
```

#### Method B: Full Clean Rebuild
```bash
cd /root/Anasy-RSS-MHJoyBots-FUSE
docker compose build
docker compose up -d --force-recreate
```

### 6.2 Cleaning Stale FUSE Mounts

If a download task crashes or is forcibly terminated while an archive is mounted:
1. `archivemount` might leave an orphaned mount point in `/app/downloads/<mid>/.mnt_<name>`.
2. Attempts to remove the directory will error with `Device or resource busy`.

#### Resolution Command
```bash
# Find and unmount any orphaned FUSE points inside container
docker exec anasy-rss-mhjoybots-fuse-app-1 bash -c '
for mnt in $(mount | grep archivemount | awk "{print \$3}"); do
    echo "Unmounting stale mount: $mnt"
    fusermount -u -z "$mnt" || umount -l "$mnt"
done
'

# Clean orphaned working directories
docker exec anasy-rss-mhjoybots-fuse-app-1 bash -c '
find /app/downloads -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} + 2>/dev/null || true
'
```

### 6.3 Disaster Recovery & Rollback Procedure

If the FUSE bot container encounters an unrecoverable failure:

```bash
# 1. Stop FUSE bot
docker compose -f /root/Anasy-RSS-MHJoyBots-FUSE/docker-compose.yml down

# 2. Verify previous container or host services are unaffected
docker ps

# If needed to restart a previous container:
docker start mltb-container

# 3. Verify disk space on /srv/bot-storage (or your storage partition)
df -h /srv/bot-storage
```

---

## 7. Operational Summary & Verification Checklist

- [x] Host `/dev/fuse` permissions verified (`crw-rw-rw-`).
- [x] Host partition mounted at `/srv/bot-storage` (or custom path) via `/etc/fstab`.
- [x] Volume permissions set to `0777` on `/srv/bot-storage/fuse_bot/downloads`.
- [x] Docker Compose configured with `SYS_ADMIN`, `/dev/fuse`, and `apparmor:unconfined`.
- [x] No port collisions with other host services.
- [x] Systemd service configured with `ConditionPathIsMountPoint=/srv/bot-storage` (if using dedicated mount).
- [x] Telegram zip picker (`/leech -e -s`) validated with peak storage equal to `ZIP + 1 Split Chunk`.
