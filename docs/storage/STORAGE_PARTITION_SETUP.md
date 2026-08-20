# mirror-leech-telegram-bot-fuse Storage Partition Setup & Bind Layout

Date: 2026-03-27

## Why This Was Done

The VPS disk is `100 GiB`, but the root filesystem on `/dev/vda2` only uses about `63 GiB`.
There was about `35 GiB` of free, unallocated disk space at the end of the disk.

Normal installs and normal Docker writable layers were not using that extra space.
The goal was to make **mirror-leech-telegram-bot-fuse** (`MHJoy99/mirror-leech-telegram-bot-fuse`) use that extra storage for downloads and bot data.

## Disk Layout Before

- `/dev/vda2` -> root `/` -> about `63 GiB`
- `/dev/vda3` -> swap -> `2 GiB`
- free, unallocated space -> about `35 GiB`

## What Was Created

A new partition was created from the unused space:

- `/dev/vda4`
- filesystem: `ext4`
- label: `bot-storage`
- mount point: `/srv/bot-storage`

It was also added to `/etc/fstab`:

```fstab
UUID=90980c8c-2bdf-47f0-a634-8f110bc20fb8 /srv/bot-storage ext4 defaults,nofail 0 2
```

## Why This Approach Was Chosen

This was safer than resizing the root partition.

The root partition could not be grown directly because the swap partition sat between `/dev/vda2` and the free space.
Using a separate partition avoided risky root partition edits and still made the extra `35 GiB` usable.

## Bot That Was Moved

The active Telegram bot container was:

- container name: `mltb-container` (or `mirror-leech-telegram-bot-fuse`)
- image: `mltb-container-image`

The old container was preserved for rollback as:

- `mltb-container_pre_storage_backup`

## Important Bot Paths

Inside this bot, the main download directory is hardcoded here:

- `DOWNLOAD_DIR = "/app/downloads/"`

That value is defined in:

- `bot/__init__.py`

The container also uses these paths:

- `/app`
- `/usr/src/app/downloads`
- `/JDownloader`

## New Storage Layout For The Bot

Host storage path:

- `/srv/bot-storage/fuse_bot` (or `/path/to/storage/fuse_bot`)

Bind mounts now used by the live container:

- `/srv/bot-storage/fuse_bot/app` -> `/app`
- `/srv/bot-storage/fuse_bot/usr-src-downloads` -> `/usr/src/app/downloads`
- `/srv/bot-storage/fuse_bot/JDownloader` -> `/JDownloader`

This means the bot now uses the extra disk space for:

- bot code and runtime files under `/app`
- Telegram bot downloads under `/app/downloads`
- extra downloader path under `/usr/src/app/downloads`
- JDownloader data under `/JDownloader`

## Current Result

After migration, these paths inside the running container are backed by the dedicated partition:

- `/app`
- `/app/downloads`
- `/usr/src/app/downloads`
- `/JDownloader`

The new partition has about `35 GiB` total and about `33 GiB` free after the move.

## What Was Verified

The following checks were confirmed:

- `/srv/bot-storage` is mounted from the dedicated disk partition
- the live `mltb-container` is running
- the container bind mounts point to `/srv/bot-storage/fuse_bot/...`
- a direct write test inside `/app/downloads` succeeded
- the bot started and logged:

```text
2026-03-27 17:18:57,173 - bot - INFO - Creating client from BOT_TOKEN
```

## Rollback

If needed, rollback is straightforward because the old container was kept.

Example rollback flow:

```bash
docker rm -f mltb-container
docker rename mltb-container_pre_storage_backup mltb-container
docker start mltb-container
```

If rollback is needed, verify host ports are free before starting the old container again.

## Important Update Caveat

Because `/app` is now bind-mounted from the host storage, future image rebuilds alone will not automatically replace the bot files inside `/app`.

That means:

- container recreation will keep using the host-mounted `/app`
- if the image is rebuilt with updated code, the mounted `/app` may still keep the older copied files

So future updates should be done carefully.

Safe mindset:

- treat `/srv/bot-storage/fuse_bot/app` as the live app directory
- if updating the bot image, also review whether the mounted app directory needs syncing

## Extra Live Config Caveat Learned Later

File sync alone may still not be enough for behavior changes.

This bot also stores bot-level config in Mongo `settings.config`, and those values can
override newer values from `/app/config.py`.

Example seen later:

- `LEECH_CAPTION` was updated in the repo and in the mounted `/app/config.py`
- but the running bot still used an older caption template from Mongo

So for future live changes, verify both:

- mounted live files under `/srv/bot-storage/fuse_bot/app`
- Mongo bot config values in `settings.config`

## Repeat Pattern For Similar Bots

For similar Telegram download bots, the safest repeatable pattern is:

1. Create or reuse a host path under `/srv/bot-storage/<bot-name>/`
2. Identify the real in-container download path
3. Bind mount the heavy-write paths onto the extra disk
4. Keep the old container stopped for rollback
5. Verify writes inside the mounted download directory

Good candidates to move:

- `/app/downloads`
- `/app`
- downloader working directories
- JDownloader data
- qBittorrent profile/data if it grows large

## Files Saved During This Change

- live storage root: `/srv/bot-storage/fuse_bot`
- pre-move inspect snapshot: `/srv/bot-storage/fuse_bot/meta/inspect.before.json`

## Quick Verification Commands

```bash
findmnt /srv/bot-storage
docker ps -a --filter name=mltb-container
docker inspect mltb-container --format '{{json .Mounts}}'
docker exec mltb-container bash -lc 'df -h /app /app/downloads /usr/src/app/downloads /JDownloader'
docker logs --tail 50 mltb-container
```
