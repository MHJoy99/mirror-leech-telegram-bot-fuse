# TDLib Upload Parallelism & Concurrency Architecture

<div align="center">

[![TDLib](https://img.shields.io/badge/TDLib-Upload%20Parallelism-0088CC?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/tdlib)
[![AsyncIO](https://img.shields.io/badge/Concurrency-AsyncIO%20Bounded%20Workers-4EBA6F?style=for-the-badge&logo=fastapi&logoColor=white)](https://docs.python.org/3/library/asyncio.html)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge&logo=gnu&logoColor=white)](LICENSE)

*Technical specification detailing the global batching pipeline, bounded semaphore workers, thread-safe reply chaining, and multi-session round-robin load distribution in TDLib userbot uploads.*

</div>

---

## 1. Executive Summary

Standard Telegram mirror bots process leech uploads serially: traversing directories, preparing one file, uploading it synchronously, and blocking all subsequent transfers until the current file completes.

**mirror-leech-telegram-bot-fuse** (`MHJoy99/mirror-leech-telegram-bot-fuse`) replaces serial traversal with an asynchronous **Global Batch Dispatch & Bounded Worker Architecture**. Upload payloads are aggregated into structured batches and dispatched across an `asyncio.Semaphore` pool, dynamically rotating across authenticated TDLib client instances.

---

## 2. Concurrency Architecture & Request Lifecycle

```
                           [ Leech Download & Media Processing Complete ]
                                                 │
                                                 ▼
                           ┌───────────────────────────────────────────┐
                           │      Global Batch Collection Stage        │
                           │   - Scans output directory tree           │
                           │   - Generates ffprobe WZML captions       │
                           │   - Builds structured entries array       │
                           └─────────────────────┬─────────────────────┘
                                                 │
                                                 ▼
                             ┌───────────────────────────────────────┐
                             │       Batch Routing Evaluation        │
                             └───────────────────┬───────────────────┘
                                                 │
                        ┌────────────────────────┴────────────────────────┐
                        │ (All Split Parts?)                              │ (Regular Multi-File?)
                        ▼                                                 ▼
         ┌───────────────────────────────┐                 ┌───────────────────────────────┐
         │ TG_SPLIT_UPLOAD_CONCURRENCY   │                 │ TG_FILE_UPLOAD_CONCURRENCY    │
         │ Bounded Semaphore (Default: 4)│                 │ Bounded Semaphore (Default: 8)│
         └──────────────┬────────────────┘                 └──────────────┬────────────────┘
                        │                                                 │
                        └────────────────────────┬────────────────────────┘
                                                 │
                                                 ▼
                            ┌─────────────────────────────────────────┐
                            │    asyncio.gather(*workers) Execution   │
                            └────────────────────┬────────────────────┘
                                                 │
                        ┌────────────────────────┼────────────────────────┐
                        ▼                        ▼                        ▼
             ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
             │  Worker 1 (Part 01) │  │  Worker 2 (Part 02) │  │  Worker 3 (Part 03) │
             │  Acquires Client #1 │  │  Acquires Client #2 │  │  Acquires Client #3 │
             └──────────┬──────────┘  └──────────┬──────────┘  └──────────┬──────────┘
                        │                        │                        │
                        ▼                        ▼                        ▼
                  Telegram DC              Telegram DC              Telegram DC
```

---

## 3. Core Concurrency Mechanics

### 3.1 Global Batching vs Legacy Serial Traversal

- **Legacy Model**: Directory walked sequentially; each file is prepared, uploaded, and logged before discovering the next file. Failure on file $N$ halts discovery.
- **Global Batch Model**: Scans the target tree, builds media contexts (`ffprobe`, thumbnails, localized language tags), and forms an atomic upload manifest before initiating network I/O.

### 3.2 Thread-Safe Reply Chaining & Progress Aggregation

Parallel uploads sending messages to the same Telegram chat require strict sequencing to maintain reply-thread integrity and prevent message races:

1. **`_reply_to_lock`**: An `asyncio.Lock` that synchronizes initial message anchoring without blocking payload data transmission.
2. **`_processed_bytes_lock`**: Protects shared throughput counters, allowing concurrent upload callbacks to update speed and ETA calculations with zero race conditions.
3. **Dedicated Progress References (`last_uploaded_ref`)**: Each concurrent worker receives a private 1-element reference array (`[0]`) to calculate delta byte offsets independently.

### 3.3 Dynamic TDLib Client Acquisition

When an upload worker starts, it requests a client via `TdlibManager.get_upload_client()`. The manager cycles through `user_pool` under `_pool_lock`, assigning the next healthy TDLib session instance.

---

## 4. Configuration & Worker Tuning Parameters

Adjust concurrency knobs in `config.py` according to network bandwidth and available CPU/RAM resources:

```python
# Concurrency & Worker Knobs
TG_FILE_UPLOAD_CONCURRENCY = 8    # Maximum concurrent distinct files uploaded simultaneously
TG_SPLIT_UPLOAD_CONCURRENCY = 4   # Maximum concurrent split chunks uploaded simultaneously
TG_UPLOAD_WORKERS = 16            # Internal worker threads per upload task
```

### Recommended Resource Tuning Matrix

| Deployment Profile | File Concurrency | Split Concurrency | Internal Workers | Minimum Recommended RAM |
| :--- | :---: | :---: | :---: | :---: |
| **Budget VPS (2 vCPU / 2GB RAM)** | `4` | `2` | `8` | 2 GB |
| **Standard Production (4 vCPU / 4GB RAM)** | `8` | `4` | `16` | 4 GB |
| **High-Throughput Dedicated (8+ vCPU / 16GB RAM)** | `16` | `8` | `32` | 8 GB |

---

## 5. Live Production Log Verification

Monitor upload parallelism using Docker logs:

```bash
docker compose logs --tail=100 -f app | grep -E "TDLib upload (plan|batch|start|done|progress)"
```

### Expected Production Log Sequence

```text
2026-08-20 10:02:11 INFO  bot.helper.mirror_leech_utils.tdlib_uploader: TDLib upload plan: name=The.K2.S01 | file_parallel=8 | split_parallel=4
2026-08-20 10:02:12 INFO  bot.helper.mirror_leech_utils.tdlib_uploader: TDLib upload batch collected: name=The.K2.S01 | files=4
2026-08-20 10:02:12 INFO  bot.helper.mirror_leech_utils.tdlib_uploader: TDLib parallel upload batch: type=files | parts=4 | parallel_limit=4
2026-08-20 10:02:13 INFO  bot.helper.mirror_leech_utils.tdlib_uploader: TDLib upload start: name=The.K2.S01E01.mkv | size=1.94 GB | parallel=True | db=tdlib_user_2 | index=1
2026-08-20 10:02:13 INFO  bot.helper.mirror_leech_utils.tdlib_uploader: TDLib upload start: name=The.K2.S01E02.mkv | size=1.94 GB | parallel=True | db=tdlib_user_3 | index=2
2026-08-20 10:02:18 INFO  bot.helper.mirror_leech_utils.tdlib_uploader: TDLib upload progress: name=The.K2.S01E01.mkv | current=209715200 | total=2083528192 | pct=10.07% | speed=41.20MB/s
2026-08-20 10:02:18 INFO  bot.helper.mirror_leech_utils.tdlib_uploader: TDLib upload progress: name=The.K2.S01E02.mkv | current=198180864 | total=2083528192 | pct=9.51% | speed=39.45MB/s
```
