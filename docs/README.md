# 📚 mirror-leech-telegram-bot-fuse Documentation Hub

Welcome to the comprehensive documentation index for **mirror-leech-telegram-bot-fuse** (`MHJoy99/mirror-leech-telegram-bot-fuse`). This index organizes all technical specifications, architecture blueprints, deployment runbooks, and subsystem guides into structured categories.

---

## 📑 Documentation Index

### 1. 🏗️ Architecture & Core Subsystems (`docs/architecture/`)
* [**FUSE Zero-Double-Storage & ZIP Picker Master Bible**](architecture/FUSE_ZERO_DOUBLE_STORAGE.md)
  * Complete 700+ line technical specification of the FUSE virtual mounting pipeline (`archivemount readonly,nosave`), interactive Telegram inline ZIP picker GUI, streaming split & upload pipeline, and anti-choke sequential upload mechanics.
* [**System Architecture & Topology**](architecture/SYSTEM_ARCHITECTURE.md)
  * Overview of the container architecture, task listener lifecycle, volume mount mappings, and runtime components.
* [**Upstream Comparison & Repository Differences**](architecture/UPSTREAM_COMPARISON.md)
  * In-depth comparison matrix against upstream `mirror-leech-telegram-bot`, detailing code modifications, performance benefits, and new modules.
* [**Dual Telegram Leech & Google Drive Backup**](architecture/DUAL_LEECH_GDRIVE_BACKUP.md)
  * Resilient dual-destination pipeline architecture enabling automatic secondary Google Drive backup with independent failure boundaries.

---

### 2. ⚡ TDLib Multi-Session Concurrency Pool (`docs/tdlib/`)
* [**TDLib Pool Setup Guide**](tdlib/TDLIB_POOL_SETUP.md)
  * Interactive CLI walkthrough and architectural blueprint for initializing and authenticating high-speed TDLib userbot sessions.
* [**TDLib Pool Expansion Runbook**](tdlib/TDLIB_POOL_EXPANSION.md)
  * Operational guide for scaling upload concurrency, memory sizing calculations, and collision-free session database indexing.
* [**One-Click TDLib Pool Automation**](tdlib/TDLIB_POOL_ONE_CLICK.md)
  * Specification for the automated one-click database cloning and configuration generator (`clone_tdlib_pool.py`).
* [**TDLib Upload Parallelism Specification**](tdlib/TDLIB_UPLOAD_PARALLELISM.md)
  * Deep dive into bounded semaphore worker pooling, thread safety locks, and multi-part split upload distribution.

---

### 3. 🚀 Deployment & Operations (`docs/deployment/`)
* [**Production Deployment Guide**](deployment/PRODUCTION_DEPLOYMENT.md)
  * Complete guide for production deployment using Docker Compose with `SYS_ADMIN` and `/dev/fuse` bindings, systemd service units, and resource limits.

---

### 4. 💽 Storage & Cloud Integrations (`docs/storage/`)
* [**Storage Partition Setup & Bind Layout**](storage/STORAGE_PARTITION_SETUP.md)
  * Dedicated disk partition layout, mount point permissions, and persistent volume directory structure.
* [**Google Drive OAuth & Service Account Setup**](storage/GDRIVE_OAUTH_SETUP.md)
  * Guide for Google Drive API v3 OAuth token generation, Service Account rotation, and quota management.

---

## 🗺️ Visual Documentation Map

```
docs/
├── README.md                                # Central Documentation Hub (This File)
├── architecture/
│   ├── FUSE_ZERO_DOUBLE_STORAGE.md          # Master FUSE & ZIP Picker Specification
│   ├── SYSTEM_ARCHITECTURE.md               # Container & Runtime Topology
│   ├── UPSTREAM_COMPARISON.md               # Diff Matrix vs Upstream MLTB
│   └── DUAL_LEECH_GDRIVE_BACKUP.md          # Dual Destination Leech Pipeline
├── tdlib/
│   ├── TDLIB_POOL_SETUP.md                  # Interactive Pool Initialization
│   ├── TDLIB_POOL_EXPANSION.md              # Zero-Collision Scaling Runbook
│   ├── TDLIB_POOL_ONE_CLICK.md              # One-Click Session Cloning
│   └── TDLIB_UPLOAD_PARALLELISM.md          # Multi-Part Concurrency Architecture
├── deployment/
│   └── PRODUCTION_DEPLOYMENT.md             # Docker Compose & Systemd Runbook
└── storage/
    ├── STORAGE_PARTITION_SETUP.md           # Dedicated VFS Partition & Bindings
    └── GDRIVE_OAUTH_SETUP.md                # Google Drive API v3 Auth & Quotas
```
