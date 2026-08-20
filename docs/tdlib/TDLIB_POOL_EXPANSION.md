# TDLib Pool Expansion & Scaling Runbook

<div align="center">

[![TDLib](https://img.shields.io/badge/TDLib-Pool%20Expansion-0088CC?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/tdlib)
[![Scaling](https://img.shields.io/badge/Scaling-Zero--Collision%20Indexing-success?style=for-the-badge&logo=prometheus&logoColor=white)](TDLIB_POOL_SETUP.md)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge&logo=gnu&logoColor=white)](LICENSE)

*Operational runbook for expanding the TDLib userbot pool, provisioning incremental database instances without downtime or index collisions.*

</div>

---

## 1. Pool Expansion Mechanics

As transmission volume grows, expanding the TDLib session pool distributes file upload concurrency across a larger cluster of Telegram accounts.

The provisioning script `setup_tdlib_pool.py` implements automatic index resolution via `_free_start_index()`. When executed against an existing deployment, it dynamically scans `/app` for existing `tdlib_user_*` directories and attaches new accounts starting from the next available slot.

```
Existing Pool State:
  /app/tdlib_user       (Base Client)
  /app/tdlib_user_2     (Account 2)
  /app/tdlib_user_3     (Account 3)
  /app/tdlib_user_4     (Account 4)

Executing: python3 setup_tdlib_pool.py 3 /app/tdlib_user
  Detects highest existing index: 4
  Allocates slots:
    ├── /app/tdlib_user_5 (Account 5)
    ├── /app/tdlib_user_6 (Account 6)
    └── /app/tdlib_user_7 (Account 7)
```

---

## 2. Step-by-Step Expansion Procedure

### Step 1: Execute Provisioning Inside Container

Attach to the running container and invoke `setup_tdlib_pool.py` with the requested expansion count:

```bash
docker exec -it anasy-rss-mhjoybots-fuse-app-1 bash -c "source /app/mltbenv/bin/activate && python3 setup_tdlib_pool.py 4 /app/tdlib_user"
```

### Step 2: Complete Authentication Prompts

Provide the API credentials and complete interactive authentication for each additional account:

```text
=== TDLib account 5/8 ===
Enter phone number (e.g. +880171...): +19876543210
auth_state=authorizationStateWaitCode
Enter code: 12345
LOGIN_OK db=/app/tdlib_user_5 id=102938475 username=UserFive premium=False

Press Enter for next account, or type stop to end: 
```

### Step 3: Update Configuration File

Append the generated list to `TDLIB_USER_DB_PATHS` in `/root/Anasy-RSS-MHJoyBots-FUSE/config.py`:

```python
# Updated TDLib Pool Configuration
TDLIB_USER_DB_PATH = "tdlib_user"
TDLIB_USER_DB_PATHS = [
    "tdlib_user_2",
    "tdlib_user_3",
    "tdlib_user_4",
    "tdlib_user_5",
    "tdlib_user_6",
    "tdlib_user_7",
    "tdlib_user_8",
]
```

### Step 4: Restart Service & Assert Pool Size

Reload the container to mount the expanded pool:

```bash
docker compose restart app
```

Verify startup initialization:

```bash
docker compose logs --tail=50 app | grep -E "Added TDLib pool client|pool_size"
```

---

## 3. Resource Allocation & Scaling Capacity Matrix

Each active TDLib SQLite database maintains its own localized state, caches, and MTProto network socket. Plan host resource allocation according to the sizing matrix below:

| Pool Size ($N$ Sessions) | RAM Footprint | SQLite Disk Space | Max Recommended Parallel Uploads |
| :---: | :---: | :---: | :---: |
| **4 Sessions** | ~200 MB | ~150 MB | 8 Concurrent Files |
| **8 Sessions** | ~400 MB | ~300 MB | 16 Concurrent Files |
| **16 Sessions** | ~800 MB | ~600 MB | 32 Concurrent Files |
| **32 Sessions** | ~1.6 GB | ~1.2 GB | 64 Concurrent Files |

---

## 4. Operational Guard Rails & Failure Handling

```
                              [Start Pool Expansion]
                                         │
                                         ▼
                             [Scan Existing DB Paths]
                                         │
                                         ▼
                           [Index Slot = Highest + 1]
                                         │
                                         ▼
                            [Authenticate New Account]
                                   /           \
                             (Success)       (Failure)
                                 /               \
                                v                 v
                    [Write SQLite DB]    [Log Reason & Skip Slot]
                                \                 /
                                 +───────┬───────+
                                         │
                                         ▼
                           [Next Account or Complete]
                                         │
                                         ▼
                           [Update TDLIB_USER_DB_PATHS]
                                         │
                                         ▼
                              [docker compose restart]
```

- **Zero Overwrite Protection**: `setup_tdlib_pool.py` will never overwrite an existing database folder. If `tdlib_user_N` exists, the slot is automatically skipped.
- **Graceful Account Eviction**: If any individual TDLib session in the pool becomes invalidated or encounters an authorization revocation, `TdlibManager` logs the error, marks that specific database as inactive, and continues round-robin dispatch across the remaining healthy clients.
