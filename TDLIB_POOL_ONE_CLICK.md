# TDLib Automated One-Click Pool Cloner

<div align="center">

[![TDLib](https://img.shields.io/badge/TDLib-One--Click%20Cloner-0088CC?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/tdlib)
[![Automation](https://img.shields.io/badge/Automation-Auto--Config%20Patching-success?style=for-the-badge&logo=gnu-bash&logoColor=white)](clone_tdlib_pool.py)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge&logo=gnu&logoColor=white)](LICENSE)

*Automated utility to replicate authorized TDLib session databases into incremental pool instances and patch runtime configurations in a single command.*

</div>

---

## 1. Overview & Use Cases

When setting up multiple concurrency queues or testing parallel upload stability using an existing authorized Telegram user session, re-authenticating and typing SMS/2FA codes repeatedly is inefficient.

The `clone_tdlib_pool.py` tool provides zero-interaction replication of an already-authorized base TDLib SQLite database (`tdlib_user`). It automatically:
1. Detects existing database directories in `/app`.
2. Clones the base database structure into incremental slots (`tdlib_user_2`, `tdlib_user_3`, etc.).
3. Directly updates `TDLIB_USER_DB_PATHS` in `config.py` / `config_local.py` using AST regex matching.

```
+-----------------------------------------------------------------------------------+
| Host Container Execution: clone_tdlib_pool.py 4 /app/tdlib_user                   |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
            ┌────────────────────────────────────────────────────────┐
            │ Scans /app/tdlib_user (Authorized Master SQLite DB)    │
            └────────────────────────────┬───────────────────────────┘
                                         │
                 ┌───────────────────────┼───────────────────────┐
                 ▼                       ▼                       ▼
      ┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
      │  /app/tdlib_user_2  │ │  /app/tdlib_user_3  │ │  /app/tdlib_user_4  │
      │  (Cloned DB Slot 2) │ │  (Cloned DB Slot 3) │ │  (Cloned DB Slot 4) │
      └─────────────────────┘ └─────────────────────┘ └─────────────────────┘
                                         │
                                         ▼
            ┌────────────────────────────────────────────────────────┐
            │ Automatically patches TDLIB_USER_DB_PATHS in config.py │
            └────────────────────────────────────────────────────────┘
```

---

## 2. Command Reference & Options

### 2.1 Basic Usage

```bash
docker exec -it anasy-rss-mhjoybots-fuse-app-1 python3 clone_tdlib_pool.py [COUNT] [BASE_DIR] [--config CONFIG_FILE]
```

### 2.2 CLI Arguments

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `count` | `Integer` | *Required* | Number of new TDLib database slots to clone. |
| `base_dir` | `String` | `/app/tdlib_user` | Source authenticated TDLib database directory. |
| `--config` | `String` | `/app/config_local.py` | Target configuration file to patch with new array values. |

---

## 3. Step-by-Step Execution

### Step 1: Execute One-Click Clone

Run the cloner to generate 8 slots and patch `config.py`:

```bash
docker exec -it anasy-rss-mhjoybots-fuse-app-1 python3 clone_tdlib_pool.py 8 /app/tdlib_user --config /app/config.py
```

#### Output Trace:
```text
CLONED /app/tdlib_user -> /app/tdlib_user_2
CLONED /app/tdlib_user -> /app/tdlib_user_3
CLONED /app/tdlib_user -> /app/tdlib_user_4
CLONED /app/tdlib_user -> /app/tdlib_user_5
CLONED /app/tdlib_user -> /app/tdlib_user_6
CLONED /app/tdlib_user -> /app/tdlib_user_7
CLONED /app/tdlib_user -> /app/tdlib_user_8
CLONED /app/tdlib_user -> /app/tdlib_user_9
UPDATED /app/config.py

TDLIB_USER_DB_PATHS = [
    "tdlib_user_2",
    "tdlib_user_3",
    "tdlib_user_4",
    "tdlib_user_5",
    "tdlib_user_6",
    "tdlib_user_7",
    "tdlib_user_8",
    "tdlib_user_9",
]
```

### Step 2: Restart Bot Service

Reload the container to mount the newly cloned database pool:

```bash
docker compose restart app
```

---

## 4. Architectural Boundaries: Cloned vs Multi-Account Pools

| Feature | Cloned Single-Account Pool | Multi-Account Pool (`setup_tdlib_pool.py`) |
| :--- | :--- | :--- |
| **Setup Time** | < 2 seconds (Zero prompt) | 2–5 minutes (Requires SMS/2FA codes) |
| **Telegram Account Count** | 1 (Replicated session token) | Multiple ($N$ distinct accounts) |
| **Flood-Wait Protection** | Shared account limits | **Independent per-account quotas** |
| **Max Network Throughput** | Single account ceiling (~40–60 MB/s) | **Linear scaling ($N \times \text{Bandwidth}$)** |
| **Best Used For** | Rapid testing, queue isolation | High-volume production deployments |
