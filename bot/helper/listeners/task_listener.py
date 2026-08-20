from os import path as ospath, walk
import os
from aiofiles.os import path as aiopath, listdir, remove, makedirs as aiomakedirs
from asyncio import sleep, gather, create_subprocess_exec
from asyncio.subprocess import PIPE
from html import escape
from requests import utils as rutils

from ... import (
    intervals,
    task_dict,
    task_dict_lock,
    LOGGER,
    non_queued_up,
    non_queued_dl,
    queued_up,
    queued_dl,
    queue_dict_lock,
    same_directory_lock,
    DOWNLOAD_DIR,
    upload_slots,
)
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager
from ..common import TaskConfig
from ..ext_utils.bot_utils import sync_to_async
from ..ext_utils.db_handler import database
from ..ext_utils.files_utils import (
    get_path_size,
    get_base_name,
    clean_download,
    clean_target,
    join_files,
    create_recursive_symlink,
    remove_excluded_files,
    remove_non_included_files,
    move_and_merge,
)
from ..ext_utils.links_utils import is_gdrive_id
from ..ext_utils.status_utils import get_readable_file_size
from ..ext_utils.task_manager import (
    start_from_queued,
    check_running_tasks,
    check_drive_duplicate,
)
from ..mirror_leech_utils.gdrive_utils.upload import GoogleDriveUpload
from ..mirror_leech_utils.rclone_utils.transfer import RcloneTransferHelper
from ..mirror_leech_utils.status_utils.gdrive_status import GoogleDriveStatus
from ..mirror_leech_utils.status_utils.queue_status import QueueStatus
from ..mirror_leech_utils.status_utils.rclone_status import RcloneStatus
from ..mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from ..mirror_leech_utils.telegram_uploader import TelegramUploader
from ..mirror_leech_utils.tdlib_uploader import TdlibTelegramUploader
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import (
    send_message,
    delete_status,
    update_status_message,
)
from ...core.tdlib_manager import TdlibManager


class TaskListener(TaskConfig):
    def __init__(self):
        super().__init__()
        self.current_upload_stage = ""
        self.telegram_upload_result = None
        self.drive_upload_result = None

    async def clean(self):
        try:
            if st := intervals["status"]:
                for intvl in list(st.values()):
                    intvl.cancel()
            intervals["status"].clear()
            await gather(TorrentManager.aria2.purgeDownloadResult(), delete_status())
        except:
            pass

    def clear(self):
        self.subname = ""
        self.subsize = 0
        self.files_to_proceed = []
        self.proceed_count = 0
        self.progress = True

    def _build_upload_button(
        self,
        link="",
        mime_type="",
        rclone_path="",
        dir_id="",
        private_link=None,
    ):
        private_link = self.private_link if private_link is None else private_link
        buttons = ButtonMaker()
        has_button = False
        if link:
            buttons.url_button("☁️ Cloud Link", link)
            has_button = True
        elif rclone_path:
            return None, f"\n\nPath: <code>{rclone_path}</code>"
        if rclone_path and Config.RCLONE_SERVE_URL and not private_link:
            remote, rpath = rclone_path.split(":", 1)
            url_path = rutils.quote(f"{rpath}")
            share_url = f"{Config.RCLONE_SERVE_URL}/{remote}/{url_path}"
            if mime_type == "Folder":
                share_url += "/"
            buttons.url_button("🔗 Rclone Link", share_url)
            has_button = True
        if not rclone_path and dir_id:
            index_url = ""
            if private_link:
                index_url = self.user_dict.get("INDEX_URL", "") or ""
            elif Config.INDEX_URL:
                index_url = Config.INDEX_URL
            if index_url:
                share_url = f"{index_url}findpath?id={dir_id}"
                buttons.url_button("⚡ Index Link", share_url)
                has_button = True
                if mime_type.startswith(("image", "video", "audio")):
                    share_urls = f"{index_url}findpath?id={dir_id}&view=true"
                    buttons.url_button("🌐 View Link", share_urls)
        return (buttons.build_menu(2) if has_button else None), ""

    async def _send_leech_messages(self, header, files=None, button=None):
        files = files or {}
        if not files:
            await send_message(self.message, header, button)
            return

        body = ""
        first_chunk = True
        for index, (link, name) in enumerate(files.items(), start=1):
            line = f"{index}. <a href='{link}'>{name}</a>\n"
            if details := self.upload_media_details.get(name):
                line += self._format_media_details(details)
            prefix = header if first_chunk else ""
            if body and len((prefix + body + line).encode()) > 4000:
                await send_message(
                    self.message,
                    prefix + body,
                    button if first_chunk else None,
                )
                await sleep(1)
                first_chunk = False
                body = line
            else:
                body += line
        prefix = header if first_chunk else ""
        await send_message(
            self.message,
            prefix + body,
            button if first_chunk else None,
        )

    async def _send_drive_link_messages(self, drive_files):
        if not drive_files:
            return

        header = "<b>Drive Links</b>\n\n"
        body = ""
        first_chunk = True
        for index, (link, name) in enumerate(drive_files.items(), start=1):
            line = f"{index}. <code>{escape(name)}</code>\n"
            if details := self.upload_media_details.get(name):
                line += self._format_media_details(details)
            line += f"\n🔗 <a href='{link}'>DOWNLOAD LINK</a>\n"
            prefix = header if first_chunk else ""
            if body and len((prefix + body + line).encode()) > 4000:
                await send_message(self.message, prefix + body)
                await sleep(1)
                first_chunk = False
                body = line
            else:
                body += line

        if body:
            prefix = header if first_chunk else ""
            await send_message(self.message, prefix + body)

    async def _finalize_success(self):
        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)
        if self.seed:
            await clean_target(self.up_dir)
            async with queue_dict_lock:
                if self.mid in non_queued_up:
                    non_queued_up.remove(self.mid)
            await start_from_queued()
            return

        if hasattr(self, '_fuse_mounts') and getattr(self, '_fuse_mounts'):
            for mnt in list(self._fuse_mounts):
                try:
                    await (await create_subprocess_exec("fusermount", "-uz", mnt, stdout=PIPE, stderr=PIPE)).wait()
                except:
                    pass
        await clean_download(f"{self.dir}_extracted_view")
        await clean_download(self.dir)
        await clean_download(f"{self.dir}_source_archives")
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        async with queue_dict_lock:
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()

    def _format_media_details(self, details):
        duration = escape(details.get("duration", "Unknown"))
        languages = escape(details.get("languages", "Unknown"))
        subtitles = escape(details.get("subtitles", "None"))
        size = escape(details.get("size", ""))
        return (
            f"📦 SIZE: {size}\n"
            f"🕒 DURATION: {duration}\n"
            f"🔊 LANGUAGE: {languages}\n"
            f"📄 SUBTITLES: {subtitles}\n"
        )

    async def _send_combined_leech_result(self):
        tg_result = self.telegram_upload_result or {}
        drive_result = self.drive_upload_result or {}
        msg = (
            f"<b>Name: </b><code>{escape(self.name)}</code>\n\n"
            f"📦 <b>SIZE:</b> {get_readable_file_size(self.size)}"
        )
        if details := (
            self.upload_media_details.get(self.name)
            or next(iter(self.upload_media_details.values()), None)
        ):
            msg += (
                f"\n🕒 <b>DURATION:</b> {escape(details.get('duration', 'Unknown'))}"
                f"\n🔊 <b>LANGUAGE:</b> {escape(details.get('languages', 'Unknown'))}"
                f"\n📄 <b>SUBTITLES:</b> {escape(details.get('subtitles', 'None'))}"
            )
        total_files = tg_result.get("total_files", 0)
        corrupted = tg_result.get("corrupted", 0)
        msg += f"\n\n📁 <b>TOTAL FILES:</b> {total_files}"
        if corrupted:
            msg += f"\n⚠️ <b>CORRUPTED FILES:</b> {corrupted}"
        msg += "\n✅ <b>TELEGRAM:</b> Uploaded"

        button = drive_result.get("button")
        if drive_result.get("status") == "uploaded":
            msg += "\n☁️ <b>GOOGLE DRIVE:</b> Uploaded"
            mime_type = drive_result.get("mime_type", "")
            if mime_type:
                msg += f"\n🎞 <b>DRIVE TYPE:</b> {mime_type}"
            if mime_type == "Folder":
                msg += f"\n📁 <b>DRIVE SUBFOLDERS:</b> {drive_result.get('folders', 0)}"
                msg += f"\n📄 <b>DRIVE FILES:</b> {drive_result.get('files', 0)}"
            upload_button, extra_text = self._build_upload_button(
                link=drive_result.get("link", ""),
                mime_type=mime_type,
                dir_id=drive_result.get("dir_id", ""),
                private_link=self.secondary_private_link,
            )
            button = upload_button or button
            msg += extra_text
        elif drive_result.get("status") == "skipped":
            reason = escape(drive_result.get("reason", "Skipped"))
            msg += f"\n☁️ <b>GOOGLE DRIVE:</b> Skipped ({reason})"
        elif drive_result.get("status") == "failed":
            reason = escape(drive_result.get("error", "Upload failed"))
            msg += f"\n☁️ <b>GOOGLE DRIVE:</b> Failed ({reason})"

        msg += f"\n<b>cc: </b>{self.tag}\n\n"
        await self._send_leech_messages(msg, tg_result.get("files", {}), button)
        await self._send_drive_link_messages(drive_result.get("drive_files", {}))

    async def remove_from_same_dir(self):
        async with task_dict_lock:
            if (
                self.folder_name
                and self.same_dir
                and self.mid in self.same_dir[self.folder_name]["tasks"]
            ):
                self.same_dir[self.folder_name]["tasks"].remove(self.mid)
                self.same_dir[self.folder_name]["total"] -= 1

    async def on_download_start(self):
        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.add_incomplete_task(
                self.message.chat.id, self.message.link, self.tag
            )

    async def on_download_complete(self):
        await sleep(2)
        if self.is_cancelled:
            return
        multi_links = False
        if (
            self.folder_name
            and self.same_dir
            and self.mid in self.same_dir[self.folder_name]["tasks"]
        ):
            async with same_directory_lock:
                while True:
                    async with task_dict_lock:
                        if self.mid not in self.same_dir[self.folder_name]["tasks"]:
                            return
                        if (
                            self.same_dir[self.folder_name]["total"] <= 1
                            or len(self.same_dir[self.folder_name]["tasks"]) > 1
                        ):
                            if self.same_dir[self.folder_name]["total"] > 1:
                                self.same_dir[self.folder_name]["tasks"].remove(
                                    self.mid
                                )
                                self.same_dir[self.folder_name]["total"] -= 1
                                spath = f"{self.dir}{self.folder_name}"
                                des_id = list(self.same_dir[self.folder_name]["tasks"])[
                                    0
                                ]
                                des_path = f"{DOWNLOAD_DIR}{des_id}{self.folder_name}"
                                LOGGER.info(f"Moving files from {self.mid} to {des_id}")
                                await move_and_merge(spath, des_path, self.mid)
                                multi_links = True
                            break
                    await sleep(1)
        async with task_dict_lock:
            if self.is_cancelled:
                return
            if self.mid not in task_dict:
                return
            download = task_dict[self.mid]
            self.name = download.name()
            gid = download.gid()
        LOGGER.info(f"Download completed: {self.name}")

        if not (self.is_torrent or self.is_qbit):
            self.seed = False

        if multi_links:
            self.seed = False
            await self.on_upload_error(
                f"{self.name} Downloaded!\n\nWaiting for other tasks to finish..."
            )
            return
        elif self.same_dir:
            self.seed = False

        if self.folder_name:
            self.name = self.folder_name.strip("/").split("/", 1)[0]

        if not await aiopath.exists(f"{self.dir}/{self.name}"):
            try:
                files = await listdir(self.dir)
                self.name = files[-1]
                if self.name == "yt-dlp-thumb":
                    self.name = files[0]
            except Exception as e:
                await self.on_upload_error(str(e))
                return

        dl_path = f"{self.dir}/{self.name}"
        self.size = await get_path_size(dl_path)
        self.is_file = await aiopath.isfile(dl_path)

        if self.seed:
            up_dir = self.up_dir = f"{self.dir}10000"
            up_path = f"{self.up_dir}/{self.name}"
            await create_recursive_symlink(self.dir, self.up_dir)
            LOGGER.info(f"Shortcut created: {dl_path} -> {up_path}")
        else:
            up_dir = self.dir
            up_path = dl_path

        if not self.included_extensions:
            await remove_excluded_files(
                self.up_dir or self.dir, self.excluded_extensions
            )
        else:
            await remove_non_included_files(
                self.up_dir or self.dir, self.included_extensions
            )

        if not await aiopath.exists(up_path):
            e = "No files to upload. In case you have filled EXCLUDED/INCLUDED EXTENSIONS, then check if all files have those extensions or not."
            await self.on_upload_error(str(e))
            return

        if not Config.QUEUE_ALL:
            async with queue_dict_lock:
                if self.mid in non_queued_dl:
                    non_queued_dl.remove(self.mid)
            await start_from_queued()

        if self.join and not self.is_file:
            await join_files(up_path)

        if self.extract and not self.is_nzb:
            up_path = await self.proceed_extract(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            if hasattr(self, '_fuse_mounts') and self._fuse_mounts and up_path and any(str(x) in str(up_path) for x in self._fuse_mounts):
                # For FUSE mount, use the actual extracted content name (inner folder or mount parent) instead of .mnt_... name
                try:
                    entries = await listdir(up_path)
                    # If single top-level folder inside mount, use that as name
                    if len(entries) == 1:
                        cand = ospath.join(up_path, entries[0])
                        if await aiopath.isdir(cand):
                            self.name = entries[0]
                        else:
                            self.name = entries[0]
                    elif entries:
                        # Use first entry or fallback to mount basename minus .mnt_ prefix
                        self.name = entries[0]
                    else:
                        self.name = up_path.rstrip("/").split("/")[-1]
                except:
                    self.name = up_path.rstrip("/").split("/")[-1]
                # Clean up .mnt_ prefix if leaked
                if self.name.startswith(".mnt_"):
                    try:
                        fallback = ospath.basename(self._fuse_mounts[0]).replace(".mnt_","")
                        self.name = fallback.rsplit("_",1)[0].replace("_"," ").strip() or self.name
                    except:
                        pass
                try:
                    self.size = await get_path_size(up_path)
                except:
                    self.size = await get_path_size(self._fuse_mounts[0]) if self._fuse_mounts else 0
                LOGGER.info(f"FUSE extract: up_path={up_path} name={self.name} size={self.size} mounts={self._fuse_mounts}")
            else:
                self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0] if up_dir in up_path else up_path.split("/")[-1]
                self.size = await get_path_size(up_dir if not self._fuse_mounts else up_path)
            # ZIP picker for FUSE mounts when -s used: show inline selector before upload
            if self.select and hasattr(self, '_fuse_mounts') and self._fuse_mounts and up_path and any(str(x) in str(up_path) for x in self._fuse_mounts):
                try:
                    from bot.modules.zip_selector import show_zip_picker
                    LOGGER.info(f"Zip picker trigger: -s mode mount={up_path}")
                    sel = await show_zip_picker(self, up_path)
                    if self.is_cancelled:
                        LOGGER.info("Zip picker cancelled -> aborting task")
                        await self.on_upload_error("Zip selection cancelled")
                        return
                    LOGGER.info(f"Zip picker selected {len(sel) if sel else 0} files")
                except Exception as e:
                    LOGGER.error(f"Zip picker error: {e}")
            self.clear()
            if not self.included_extensions:
                await remove_excluded_files(up_dir, self.excluded_extensions)
            else:
                await remove_non_included_files(up_dir, self.included_extensions)

        if self.ffmpeg_cmds:
            up_path = await self.proceed_ffmpeg(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.name_sub:
            LOGGER.info(f"Start Name Substitution {up_path}")
            up_path = await self.substitute(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]

        if self.screen_shots:
            up_path = await self.generate_screenshots(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)

        if self.convert_audio or self.convert_video:
            up_path = await self.convert_media(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.sample_video:
            up_path = await self.generate_sample_video(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.compress:
            up_path = await self.proceed_compress(
                up_path,
                gid,
            )
            self.is_file = await aiopath.isfile(up_path)
            if self.is_cancelled:
                return
            self.clear()

        if not (hasattr(self, '_fuse_mounts') and self._fuse_mounts and up_path and any(str(x) in str(up_path) for x in self._fuse_mounts)):
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)

        if self.is_leech and not self.compress:
            # For FUSE mounts, use streaming split+upload to keep peak low (A)
            if hasattr(self, '_fuse_mounts') and self._fuse_mounts:
                stream_res = await self.proceed_split_streaming(up_path, gid)
                if stream_res is False or self.is_cancelled:
                    return stream_res if stream_res is False else None
                # streaming handled its own uploads; mark as already uploaded
                # Signal to skip the later generic upload block by setting a flag
                self._streaming_done = True
                # Keep up_path pointing to splits_root for any drive backup handling
                if isinstance(stream_res, str):
                    up_path = stream_res
                self.clear()
            else:
                await self.proceed_split(up_path, gid)
                if self.is_cancelled:
                    return
                self.clear()
                # If split produced files in a dedicated split folder (e.g. {clean_name}_splits), merge non-split files and update up_path
                clean_name = ospath.basename(up_path)
                if clean_name.endswith('.zip') or clean_name.endswith('.tar') or clean_name.endswith('.7z'):
                    clean_name = get_base_name(clean_name)
                split_target = ospath.normpath(os.path.join(self.dir, f"{clean_name}_splits"))
                work_target = ospath.normpath(ospath.join(self.dir, self.name))

                active_target = None
                if await aiopath.exists(split_target) and split_target != ospath.normpath(up_path):
                    active_target = split_target
                elif await aiopath.exists(work_target) and work_target != ospath.normpath(up_path):
                    active_target = work_target

                if active_target:
                    # Symlink only non-split files from up_path to active_target (files that were split shouldn't be symlinked because their .001, .002 chunks are already in active_target)
                    split_sources = set(self.files_to_proceed.keys()) if hasattr(self, 'files_to_proceed') and self.files_to_proceed else set()
                    for r, _, files in await sync_to_async(walk, up_path):
                        rel = ospath.relpath(r, up_path)
                        dst_folder = ospath.join(active_target, rel if rel != '.' else '')
                        await aiomakedirs(dst_folder, exist_ok=True)
                        for f in files:
                            src_f = ospath.join(r, f)
                            if src_f in split_sources:
                                continue
                            dst_f = ospath.join(dst_folder, f)
                            if not await aiopath.exists(dst_f):
                                try:
                                    await sync_to_async(os.symlink, src_f, dst_f)
                                except:
                                    pass
                    up_path = active_target

        self.subproc = None

        # If streaming FUSE path already uploaded everything, just handle final reporting/cleanup
        if getattr(self, '_streaming_done', False):
            # streaming path - synthesize combined telegram result from per-file accum (A)
            if self.telegram_upload_result is None:
                if getattr(self, '_streaming_accum_files', None) and self._streaming_accum_files:
                    self.telegram_upload_result = {
                        "files": dict(self._streaming_accum_files),
                        "total_files": getattr(self, '_streaming_accum_total', len(self._streaming_accum_files)),
                        "corrupted": getattr(self, '_streaming_accum_corrupted', 0),
                    }
                    LOGGER.info(f"Streaming final accum: files={len(self.telegram_upload_result['files'])} total={self.telegram_upload_result['total_files']}")
                else:
                    LOGGER.warning("Streaming done but no accum files - fallback to empty")
                    self.telegram_upload_result = {"files": {}, "total_files": 0, "corrupted": 0}
            # done accumulating
            self._streaming_active = False
            # If drive backup requested but not yet done, let on_upload_complete handle it or skip
            # Skip GDrive secondary upload when zip picker filtered (user wanted selective leech, not 32GB mirror)
            if getattr(self, '_zip_selected_rels', None) and self.secondary_drive_requested:
                LOGGER.info(f"Zip picker active - skipping secondary GDrive upload for selective {len(self._zip_selected_rels)} files")
                self.secondary_drive_requested = False
            if self.secondary_drive_requested and self.telegram_upload_result is not None and self.secondary_drive_enabled:
                # Drive upload for streaming path - source is the FUSE mount view (still available until cleanup)
                drive_source = self.secondary_drive_source or up_path
                if not await aiopath.exists(drive_source):
                    drive_source = up_dir
                LOGGER.info(f"Starting secondary Google Drive upload (streaming path): source={drive_source}")
                drive = GoogleDriveUpload(self, drive_source, destination=self.secondary_up_dest)
                self.current_upload_stage = "gdrive_secondary"
                async with task_dict_lock:
                    task_dict[self.mid] = GoogleDriveStatus(self, drive, gid, "up")
                await gather(update_status_message(self.message.chat.id), sync_to_async(drive.upload))
                del drive
                return
            await self._send_combined_leech_result()
            await self._finalize_success()
            return

        add_to_queue, event = await check_running_tasks(self, "up")
        await start_from_queued()
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Upload: {self.name}")
            async with task_dict_lock:
                task_dict[self.mid] = QueueStatus(self, gid, "Up")
            await event.wait()
            if self.is_cancelled:
                return
            LOGGER.info(f"Start from Queued/Upload: {self.name}")

        self.size = await get_path_size(up_dir)

        if self.is_leech:
            LOGGER.info(f"Leech Name: {self.name}")
            tdlib_reason = None
            use_tdlib = (
                Config.TDLIB_USER_UPLOAD
                and TdlibManager.IS_AVAILABLE
                and self.tdlib_transmission
                and not self.hybrid_leech
                and self.size >= Config.TDLIB_USER_UPLOAD_MIN_SIZE
                and not self.user_dict.get("MEDIA_GROUP", False)
                and not (
                    Config.MEDIA_GROUP
                    and "MEDIA_GROUP" not in self.user_dict
                )
                and not self.clone_dump_chats
            )
            if not use_tdlib:
                if not Config.TDLIB_USER_UPLOAD:
                    tdlib_reason = "disabled_in_config"
                elif not TdlibManager.IS_AVAILABLE:
                    tdlib_reason = f"manager_unavailable:{TdlibManager.ERROR or 'not_ready'}"
                elif not self.tdlib_transmission:
                    tdlib_reason = "destination_or_tdlib_session_not_eligible"
                elif self.hybrid_leech:
                    tdlib_reason = "hybrid_leech_enabled"
                elif self.size < Config.TDLIB_USER_UPLOAD_MIN_SIZE:
                    tdlib_reason = f"below_min_size:{Config.TDLIB_USER_UPLOAD_MIN_SIZE}"
                elif self.user_dict.get("MEDIA_GROUP", False) or (
                    Config.MEDIA_GROUP and "MEDIA_GROUP" not in self.user_dict
                ):
                    tdlib_reason = "media_group_enabled"
                elif self.clone_dump_chats:
                    tdlib_reason = "clone_dump_chats_enabled"
                else:
                    tdlib_reason = "fallback_unspecified"
            upload_base_dir = up_path if await aiopath.isdir(up_path) else up_dir
            if use_tdlib:
                LOGGER.info(
                    "Using TDLib upload backend: "
                    f"name={self.name} | size={self.size} | up_dest={self.up_dest}"
                )
                tg = TdlibTelegramUploader(self, upload_base_dir)
            else:
                LOGGER.info(
                    "Using Pyrogram upload backend: "
                    f"name={self.name} | size={self.size} | reason={tdlib_reason}"
                )
                tg = TelegramUploader(self, upload_base_dir)
            async with task_dict_lock:
                task_dict[self.mid] = TelegramStatus(self, tg, gid, "up")
            async with upload_slots:
                self.current_upload_stage = "telegram"
                self.telegram_upload_result = None
                self.drive_upload_result = None
                self.preserve_upload_files = self.secondary_drive_enabled
                self.secondary_drive_source = up_path
                LOGGER.info(
                    "Upload slot acquired: "
                    f"name={self.name} | backend={'tdlib' if use_tdlib else 'pyrogram'} | "
                    f"limit={Config.TG_FILE_UPLOAD_CONCURRENCY}"
                )
                await gather(
                    update_status_message(self.message.chat.id),
                    tg.upload(),
                )
                if self.is_cancelled:
                    return
                if self.secondary_drive_requested and self.telegram_upload_result is not None:
                    self.preserve_upload_files = False
                    if not self.secondary_drive_enabled:
                        self.drive_upload_result = {
                            "status": "failed",
                            "error": self.secondary_drive_error
                            or "Google Drive backup is unavailable.",
                        }
                        await self._send_combined_leech_result()
                        await self._finalize_success()
                    else:
                        duplicate_msg, duplicate_button = (False, None)
                        if self.stop_duplicate:
                            duplicate_msg, duplicate_button = await check_drive_duplicate(
                                self, self.secondary_up_dest
                            )
                        if duplicate_msg:
                            self.drive_upload_result = {
                                "status": "skipped",
                                "reason": "Duplicate found in Drive",
                                "button": duplicate_button,
                            }
                            await self._send_combined_leech_result()
                            await self._finalize_success()
                        else:
                            drive_source = self.secondary_drive_source or up_path
                            if not await aiopath.exists(drive_source):
                                drive_source = up_dir
                            LOGGER.info(
                                "Starting secondary Google Drive upload: "
                                f"name={self.name} | dest={self.secondary_up_dest} | "
                                f"source={drive_source}"
                            )
                            drive = GoogleDriveUpload(
                                self,
                                drive_source,
                                destination=self.secondary_up_dest,
                            )
                            self.current_upload_stage = "gdrive_secondary"
                            async with task_dict_lock:
                                task_dict[self.mid] = GoogleDriveStatus(
                                    self, drive, gid, "up"
                                )
                            await gather(
                                update_status_message(self.message.chat.id),
                                sync_to_async(drive.upload),
                            )
                            del drive
            del tg
        elif is_gdrive_id(self.up_dest):
            LOGGER.info(f"Gdrive Upload Name: {self.name}")
            drive = GoogleDriveUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = GoogleDriveStatus(self, drive, gid, "up")
            async with upload_slots:
                LOGGER.info(
                    "Upload slot acquired: "
                    f"name={self.name} | backend=gdrive | limit={Config.TG_FILE_UPLOAD_CONCURRENCY}"
                )
                await gather(
                    update_status_message(self.message.chat.id),
                    sync_to_async(drive.upload),
                )
            del drive
        else:
            LOGGER.info(f"Rclone Upload Name: {self.name}")
            RCTransfer = RcloneTransferHelper(self)
            async with task_dict_lock:
                task_dict[self.mid] = RcloneStatus(self, RCTransfer, gid, "up")
            async with upload_slots:
                LOGGER.info(
                    "Upload slot acquired: "
                    f"name={self.name} | backend=rclone | limit={Config.TG_FILE_UPLOAD_CONCURRENCY}"
                )
                await gather(
                    update_status_message(self.message.chat.id),
                    RCTransfer.upload(up_path),
                )
            del RCTransfer
        return

    async def on_upload_complete(
        self,
        link,
        files,
        folders,
        mime_type,
        rclone_path="",
        dir_id="",
        drive_files=None,
    ):
        # FUSE streaming (A) accumulates per-file Telegram uploads; don't finalize until all 10 are done
        if getattr(self, "_streaming_active", False):
            if not hasattr(self, "_streaming_accum_files"):
                self._streaming_accum_files = {}
                self._streaming_accum_total = 0
                self._streaming_accum_corrupted = 0
            if files:
                try:
                    self._streaming_accum_files.update(files or {})
                except:
                    pass
            try:
                self._streaming_accum_total += int(folders) if folders is not None else 0
            except:
                pass
            try:
                self._streaming_accum_corrupted += int(mime_type) if mime_type is not None else 0
            except:
                pass
            LOGGER.info(f"Streaming accum: +{len(files or {})} files total={self._streaming_accum_total} accum={len(self._streaming_accum_files)} corrupted={self._streaming_accum_corrupted}")
            return
        if self.is_leech and self.current_upload_stage == "telegram":
            if self.secondary_drive_requested:
                self.telegram_upload_result = {
                    "files": files or {},
                    "total_files": folders,
                    "corrupted": mime_type,
                }
                return
        elif self.is_leech and self.current_upload_stage == "gdrive_secondary":
            self.drive_upload_result = {
                "status": "uploaded",
                "link": link,
                "files": files,
                "folders": folders,
                "mime_type": mime_type,
                "dir_id": dir_id,
                "drive_files": drive_files or {},
            }
            LOGGER.info(f"Task Done: {self.name}")
            await self._send_combined_leech_result()
            await self._finalize_success()
            return

        msg = f"<b>Name: </b><code>{escape(self.name)}</code>\n\n<b>Size: </b>{get_readable_file_size(self.size)}"
        LOGGER.info(f"Task Done: {self.name}")
        if self.is_leech:
            msg += f"\n<b>Total Files: </b>{folders}"
            if mime_type != 0:
                msg += f"\n<b>Corrupted Files: </b>{mime_type}"
            msg += f"\n<b>cc: </b>{self.tag}\n\n"
            await self._send_leech_messages(msg, files)
        else:
            msg += f"\n\n<b>Type: </b>{mime_type}"
            if mime_type == "Folder":
                msg += f"\n<b>SubFolders: </b>{folders}"
                msg += f"\n<b>Files: </b>{files}"
            button, extra_text = self._build_upload_button(
                link=link,
                mime_type=mime_type,
                rclone_path=rclone_path,
                dir_id=dir_id,
            )
            msg += extra_text
            msg += f"\n\n<b>cc: </b>{self.tag}"
            await send_message(self.message, msg, button)
        await self._finalize_success()

    async def on_download_error(self, error, button=None):
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        await self.remove_from_same_dir()
        msg = f"{self.tag} Download: {escape(str(error))}"
        await send_message(self.message, msg, button)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        # Unmount any fuse mounts before deleting
        if hasattr(self, '_fuse_mounts') and getattr(self, '_fuse_mounts'):
            for mnt in list(self._fuse_mounts):
                try:
                    await (await create_subprocess_exec("fusermount", "-uz", mnt, stdout=PIPE, stderr=PIPE)).wait()
                except:
                    pass
        await clean_download(f"{self.dir}_extracted_view")
        await sleep(0.2)
        await clean_download(self.dir)
        await clean_download(f"{self.dir}_source_archives")
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)

    async def on_upload_error(self, error):
        if (
            self.is_leech
            and self.current_upload_stage == "gdrive_secondary"
            and self.telegram_upload_result is not None
        ):
            self.preserve_upload_files = False
            self.drive_upload_result = {
                "status": "failed",
                "error": str(error),
            }
            await self._send_combined_leech_result()
            await self._finalize_success()
            return
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        await send_message(self.message, f"{self.tag} {escape(str(error))}")
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            self.is_super_chat
            and Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        # Unmount any fuse mounts before deleting
        if hasattr(self, '_fuse_mounts') and getattr(self, '_fuse_mounts'):
            for mnt in list(self._fuse_mounts):
                try:
                    await (await create_subprocess_exec("fusermount", "-uz", mnt, stdout=PIPE, stderr=PIPE)).wait()
                except:
                    pass
        await clean_download(f"{self.dir}_extracted_view")
        await sleep(0.2)
        await clean_download(self.dir)
        await clean_download(f"{self.dir}_source_archives")
        if self.up_dir:
            await clean_download(self.up_dir)
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)
