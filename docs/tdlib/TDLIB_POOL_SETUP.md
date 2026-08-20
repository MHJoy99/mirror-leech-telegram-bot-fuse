# TDLib Multi-Session Concurrency Pool Setup Guide

<div align="center">

[![TDLib](https://img.shields.io/badge/Telegram-TDLib%201.8%2B-0088CC?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/tdlib)
[![Concurrency](https://img.shields.io/badge/Concurrency-Multi--Session%20Pool-success?style=for-the-badge&logo=fastapi&logoColor=white)](TDLIB_UPLOAD_PARALLELISM.md)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge&logo=gnu&logoColor=white)](LICENSE)

*Comprehensive guide for provisioning, authorizing, and configuring a high-throughput multi-session TDLib userbot pool in mirror-leech-telegram-bot-fuse (MHJoy99/mirror-leech-telegram-bot-fuse).*

</div>

---

## 1. Architectural Overview

Telegram applies strict per-account upload rate limits and flood-wait controls on standard MTProto connections. Single-session bots attempting to transmit multiple multi-gigabyte files simultaneously encounter throughput bottlenecks and temporary upload bans (`FLOOD_WAIT_X`).

The **TDLib Multi-Session Concurrency Pool** architecture provisions multiple independent SQLite database instances (`tdlib_user_2`, `tdlib_user_3`, etc.) managed by a centralized round-robin orchestrator (`bot/core/tdlib_manager.py`).

```
                              ┌───────────────────────────────┐
                              │     Task Execution Engine     │
                              └───────────────┬───────────────┘
                                              │
                                     (Acquires Upload Lock)
                                              │
                                              ▼
                             ┌─────────────────────────────────┐
                             │ TdlibManager.get_upload_client()│
                             └────────────────┬────────────────┘
                                              │
                         ┌────────────────────┼────────────────────┐
                         ▼ (Round-Robin)      ▼ (Round-Robin)      ▼ (Round-Robin)
               ┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐
               │  TDLib Client #1   │ │  TDLib Client #2   │ │  TDLib Client #3   │
               │ (/app/tdlib_user)  │ │(/app/tdlib_user_2) │ │(/app/tdlib_user_3) │
               └─────────┬──────────┘ └─────────┬──────────┘ └─────────┬──────────┘
                         │                      │                      │
                         ▼                      ▼                      ▼
                   Telegram DC            Telegram DC            Telegram DC
               (Account A - 50MB/s)   (Account B - 50MB/s)   (Account C - 50MB/s)
```

---

## 2. Multi-Account vs Single-Account Concurrency

| Architecture Mode | Setup Method | Throughput Scaling | Primary Benefit |
| :--- | :--- | :--- | :--- |
| **Multi-Account Pool (Recommended)** | Distinct phone numbers per session | **Linear ($N \times \text{Bandwidth}$)** | Maximum throughput, bypasses per-account flood limits. |
| **Cloned Single-Account Pool** | Cloned base session DB | Flat (Account capped) | Process-level isolation and queue management stability. |

> **Note:** To achieve true linear upload speed multiplication, each database slot in the pool must be authenticated against a distinct Telegram account (phone number). Multiple sessions tied to the same Telegram account share the same cloud-side bandwidth quota.

---

## 3. Interactive Pool Setup CLI

The automated setup tool `setup_tdlib_pool.py` streamlines the authentication flow for multiple sessions, managing TDLib parameters, verification codes, and 2FA passwords sequentially.

### 3.1 CLI Invocation

Execute the tool within the bot environment or container:

```bash
# Syntax: python3 setup_tdlib_pool.py [NUMBER_OF_ACCOUNTS] [BASE_DIRECTORY]
docker exec -it mirror-leech-telegram-bot-fuse-app-1 bash -c "source /app/mltbenv/bin/activate && python3 setup_tdlib_pool.py 3 /app/tdlib_user"
```

### 3.2 Parameter Reference

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `COUNT` (Arg 1) | `Integer` | `4` | Number of secondary session databases to initialize. |
| `BASE_DIR` (Arg 2) | `String` | `/app/tdlib_user` | Target directory prefix for generated SQLite databases. |

### 3.3 Interactive Setup Flow

```
=== TDLib Multi-Session Setup Tool ===
Enter api_id: 1234567
Enter api_hash: 0123456789abcdef0123456789abcdef

=== TDLib account 2/3 ===
Enter phone number (e.g. +880171...): +1234567890
auth_state=authorizationStateWaitCode
Enter code: 54321
auth_state=authorizationStateWaitPassword
Enter password: mySecret2faPassword
LOGIN_OK db=/app/tdlib_user_2 id=987654321 username=UserTwo premium=True

Press Enter for next account, or type stop to end: 
```

The script automatically detects existing databases and increments index counters (e.g., if `tdlib_user_2` exists, it starts from `tdlib_user_3`).

---

## 4. Configuration Integration

Upon completion, `setup_tdlib_pool.py` outputs the formatted Python array. Insert this into `config.py` or `config_local.py`:

```python
# Primary Base TDLib Session
TDLIB_USER_DB_PATH = "tdlib_user"

# Active Secondary TDLib Pool Sessions
TDLIB_USER_DB_PATHS = [
    "tdlib_user_2",
    "tdlib_user_3",
    "tdlib_user_4",
]

# Enable TDLib Userbot Upload Engine
TDLIB_USER_UPLOAD = True

# Concurrency & Worker Tuning
TG_FILE_UPLOAD_CONCURRENCY = 8
TG_SPLIT_UPLOAD_CONCURRENCY = 4
TG_UPLOAD_WORKERS = 16
```

---

## 5. Deployment & Runtime Verification

### 5.1 Restart Container

Apply configuration changes by restarting the container:

```bash
docker compose restart app
```

### 5.2 Assert Startup Logs

Inspect the startup sequence to verify that all database instances initialized successfully:

```bash
docker compose logs --tail=50 app | grep -E "TDLib|user upload backend"
```

#### Expected Log Output:
```text
2026-08-20 09:15:02 INFO  bot.core.tdlib_manager: Initializing TDLib Manager with base DB: tdlib_user
2026-08-20 09:15:03 INFO  bot.core.tdlib_manager: Added TDLib pool client: tdlib_user_2 (index=1)
2026-08-20 09:15:04 INFO  bot.core.tdlib_manager: Added TDLib pool client: tdlib_user_3 (index=2)
2026-08-20 09:15:05 INFO  bot.core.tdlib_manager: Added TDLib pool client: tdlib_user_4 (index=3)
2026-08-20 09:15:05 INFO  bot.core.startup: TDLib user upload backend is ready (active_clients=4, pool_size=3)
```

---

## 6. Operational Troubleshooting & Health Checks

| Symptom | Probable Cause | Diagnostic / Resolution Procedure |
| :--- | :--- | :--- |
| `LOGIN_FAILED db=...` | Incorrect verification code or 2FA password | Re-run `setup_tdlib_pool.py` for that specific index. |
| `TDLib client unauthorized` | Session revoked in Telegram client settings | Remove the corrupted `tdlib_user_N` directory and regenerate. |
| `FLOOD_WAIT` during login | Too many SMS/code requests in short window | Wait for Telegram cooldown timer (typically 12–24 hours) or use alternate number. |
| Speed not scaling | All databases belong to the same Telegram account | Authenticate distinct Telegram accounts across the pool. |
