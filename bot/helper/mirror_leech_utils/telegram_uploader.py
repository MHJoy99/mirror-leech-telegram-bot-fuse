from PIL import Image
from aioshutil import rmtree
from asyncio import Lock, Semaphore, gather, sleep
from logging import getLogger
from natsort import natsorted
from os import walk, path as ospath
from time import time
from re import match as re_match, sub as re_sub
from pyrogram.errors import FloodWait, RPCError, FloodPremiumWait, BadRequest
from pyrogram.types import (
    InputMediaVideo,
    InputMediaDocument,
    InputMediaPhoto,
)
from aiofiles.os import (
    remove,
    path as aiopath,
    rename,
)
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
    RetryError,
)

from ... import intervals
from ...core.config_manager import Config
from ...core.telegram_manager import TgClient
from ..ext_utils.bot_utils import sync_to_async
from ..ext_utils.files_utils import is_archive, get_base_name
from ..ext_utils.status_utils import get_readable_file_size
from ..telegram_helper.message_utils import delete_message
from ..ext_utils.media_utils import (
    get_media_info,
    get_document_type,
    get_video_thumbnail,
    get_audio_thumbnail,
    get_multiple_frames_thumbnail,
    get_leech_media_context,
    render_leech_caption,
)

LOGGER = getLogger(__name__)


class TelegramUploader:
    def __init__(self, listener, path):
        self._processed_bytes = 0
        self._listener = listener
        self._path = path
        self._start_time = time()
        self._total_files = 0
        self._thumb = self._listener.thumb or f"thumbnails/{listener.user_id}.jpg"
        self._msgs_dict = {}
        self._corrupted = 0
        self._is_corrupted = False
        self._media_dict = {"videos": {}, "documents": {}}
        self._last_msg_in_group = False
        self._up_path = ""
        self._lprefix = ""
        self._media_group = False
        self._is_private = False
        self._sent_msg = None
        self._user_session = self._listener.user_transmission
        self._error = ""
        self._base_msg = None
        self._files_links = False
        self._progress = {}
        self._progress_lock = Lock()
        self._upload_lock = Lock()
        self._upload_started_at = {}
        self._prepared_paths = []

    async def _upload_progress(self, current, _, progress_key, user_session, client):
        if self._listener.is_cancelled:
            client = client or (TgClient.user if user_session else self._listener.client)
            if user_session:
                client.stop_transmission()
            else:
                self._listener.client.stop_transmission()
        async with self._progress_lock:
            last_uploaded = self._progress.get(progress_key, 0)
            chunk_size = max(0, current - last_uploaded)
            self._progress[progress_key] = current
            self._processed_bytes += chunk_size

    async def _user_settings(self):
        self._media_group = self._listener.user_dict.get("MEDIA_GROUP", False) or (
            Config.MEDIA_GROUP
            if "MEDIA_GROUP" not in self._listener.user_dict
            else False
        )
        self._lprefix = self._listener.user_dict.get("LEECH_FILENAME_PREFIX") or (
            Config.LEECH_FILENAME_PREFIX
            if "LEECH_FILENAME_PREFIX" not in self._listener.user_dict
            else ""
        )
        self._files_links = self._listener.user_dict.get("FILES_LINKS", False) or (
            Config.FILES_LINKS
            if "FILES_LINKS" not in self._listener.user_dict
            else False
        )
        if self._thumb and self._thumb != "none" and not str(self._thumb).startswith("/"):
            self._thumb = ospath.join("/app", str(self._thumb))
        if self._thumb != "none" and not await aiopath.exists(self._thumb):
            self._thumb = None

    async def _msg_to_reply(self, client=None):
        if self._listener.up_dest:
            msg = (
                self._listener.message.link
                if self._listener.is_super_chat
                else self._listener.message.text.lstrip("/")
            )
            try:
                if self._user_session:
                    client = client or TgClient.user
                    self._sent_msg = await client.send_message(
                        chat_id=self._listener.up_dest,
                        text=msg,
                        message_thread_id=self._listener.chat_thread_id,
                        disable_notification=True,
                    )
                else:
                    self._sent_msg = await self._listener.client.send_message(
                        chat_id=self._listener.up_dest,
                        text=msg,
                        message_thread_id=self._listener.chat_thread_id,
                        disable_notification=True,
                    )
                    self._is_private = self._sent_msg.chat.type.name == "PRIVATE"
            except Exception as e:
                await self._listener.on_upload_error(str(e))
                return False
            finally:
                self._base_msg = self._sent_msg
        elif self._user_session:
            client = client or TgClient.user
            self._sent_msg = await client.get_messages(
                chat_id=self._listener.message.chat.id, message_ids=self._listener.mid
            )
            if self._sent_msg is None:
                self._sent_msg = await client.send_message(
                    chat_id=self._listener.message.chat.id,
                    text="Deleted Cmd Message! Don't delete the cmd message again!",
                    disable_notification=True,
                )
        else:
            self._sent_msg = self._listener.message
        return True

    async def _prepare_file(self, file_, dirpath, up_path, file_size):
        if self._lprefix:
            self._lprefix = re_sub("<.*?>", "", self._lprefix)
            new_path = ospath.join(dirpath, f"{self._lprefix} {file_}")
            try:
                await rename(up_path, new_path)
                up_path = new_path
            except OSError:
                pass
        if len(file_) > 60:
            if is_archive(file_):
                name = get_base_name(file_)
                ext = file_.split(name, 1)[1]
            elif match := re_match(r".+(?=\..+\.0*\d+$)|.+(?=\.part\d+\..+$)", file_):
                name = match.group(0)
                ext = file_.split(name, 1)[1]
            elif len(fsplit := ospath.splitext(file_)) > 1:
                name = fsplit[0]
                ext = fsplit[1]
            else:
                name = file_
                ext = ""
            extn = len(ext)
            remain = 60 - extn
            name = name[:remain]
            new_path = ospath.join(dirpath, f"{name}{ext}")
            try:
                await rename(up_path, new_path)
                up_path = new_path
            except OSError:
                pass
        display_name = ospath.basename(up_path)
        details = await get_leech_media_context(
            self._listener,
            file_,
            up_path,
            display_name,
            file_size,
        )
        self._listener.upload_media_details[display_name] = details
        self._listener.upload_media_details[file_] = details
        cap_mono = await render_leech_caption(
            self._listener,
            file_,
            up_path,
            display_name,
            file_size,
        )
        return cap_mono, up_path

    def _is_split_file(self, file_path):
        return bool(
            re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", ospath.basename(file_path))
        )

    def _get_upload_session(self, file_size):
        if self._listener.hybrid_leech and self._listener.user_transmission:
            return file_size > 2097152000
        return self._user_session

    async def _get_reply_message(self, user_session, client=None):
        base_msg = self._base_msg or self._sent_msg
        if self._listener.hybrid_leech and self._listener.user_transmission:
            client = client or (TgClient.user if user_session else self._listener.client)
            return await client.get_messages(
                chat_id=base_msg.chat.id,
                message_ids=base_msg.id,
            )
        return base_msg

    def _can_parallelize_split_uploads(self, entries):
        if len(entries) < 2 or self._media_group:
            return False
        return all(self._is_split_file(entry["path"]) for entry in entries)

    def _can_parallelize_regular_uploads(self, entries):
        if len(entries) < 2 or self._media_group:
            return False
        return True

    def _get_session_name(self, user_session):
        return "user" if user_session else "bot"

    def _get_upload_mode(self, file_name):
        if self._is_split_file(file_name):
            return "split-part"
        return "single-file"

    async def _handle_upload_success(self, sent_msg, file_name, is_corrupted):
        if sent_msg is None:
            return
        if sent_msg and sent_msg.media_group_id:
            for ch, ch_data in list(self._listener.clone_dump_chats.items()):
                try:
                    res = await TgClient.bot.copy_message(
                        chat_id=ch,
                        from_chat_id=sent_msg.chat.id,
                        message_id=sent_msg.id,
                        message_thread_id=ch_data["thread_id"],
                        disable_notification=True,
                        reply_to_message_id=ch_data["last_sent_msg"],
                    )
                    self._listener.clone_dump_chats[ch]["last_sent_msg"] = res.id
                except Exception as e:
                    LOGGER.error(
                        f"Can't forward message to clone dump chat: {ch}. Error: {e}"
                    )
        if (
            self._files_links
            and not is_corrupted
            and (self._listener.is_super_chat or self._listener.up_dest)
            and not self._is_private
        ):
            async with self._upload_lock:
                self._msgs_dict[sent_msg.link] = file_name

    async def _upload_entry(self, entry, parallel=False):
        file_name = entry["file"]
        upload_path = entry["path"]
        progress_key = upload_path
        upload_started_at = time()
        sent_msg = None
        is_corrupted = False
        upload_client = await TgClient.get_upload_client() if entry["user_session"] else None
        LOGGER.info(
            "Telegram upload start: "
            f"name={file_name} | size={get_readable_file_size(entry['size'])} | "
            f"mode={self._get_upload_mode(file_name)} | "
            f"session={self._get_session_name(entry['user_session'])} | "
            f"parallel={parallel}"
        )
        try:
            reply_msg = await self._get_reply_message(entry["user_session"], upload_client)
            sent_msg, is_corrupted = await self._upload_file(
                entry["caption"],
                file_name,
                upload_path,
                reply_msg=reply_msg,
                user_session=entry["user_session"],
                progress_key="__sequential__" if not parallel else progress_key,
                upload_client=upload_client,
            )
            await self._handle_upload_success(sent_msg, file_name, is_corrupted)
            elapsed = max(0.001, time() - upload_started_at)
            LOGGER.info(
                "Telegram upload done: "
                f"name={file_name} | size={get_readable_file_size(entry['size'])} | "
                f"session={self._get_session_name(entry['user_session'])} | "
                f"elapsed={round(elapsed, 2)}s | "
                f"avg_speed={get_readable_file_size(entry['size'] / elapsed)}/s"
            )
            if not parallel:
                self._sent_msg = sent_msg
        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            elapsed = max(0.001, time() - upload_started_at)
            LOGGER.error(
                "Telegram upload failed: "
                f"name={file_name} | size={get_readable_file_size(entry['size'])} | "
                f"session={self._get_session_name(entry['user_session'])} | "
                f"elapsed={round(elapsed, 2)}s | error={err}"
            )
            LOGGER.error(f"{err}. Path: {upload_path}")
            self._error = str(err)
            self._corrupted += 1
            if self._listener.is_cancelled:
                return
        finally:
            async with self._progress_lock:
                self._progress.pop(progress_key, None)
            if (
                not self._listener.is_cancelled
                and not self._listener.preserve_upload_files
                and await aiopath.exists(upload_path)
            ):
                try:
                    await remove(upload_path)
                except (OSError, Exception):
                    pass

    async def _parallel_upload_entries(self, entries, limit, label):
        limit = min(limit, len(entries))
        LOGGER.info(
            "Telegram parallel upload batch: "
            f"type={label} | files={len(entries)} | parallel_limit={limit} | "
            f"session_mix={','.join(sorted({self._get_session_name(e['user_session']) for e in entries}))}"
        )
        semaphore = Semaphore(limit)

        async def runner(entry):
            async with semaphore:
                if self._listener.is_cancelled:
                    return
                await self._upload_entry(entry, parallel=True)

        await gather(*(runner(entry) for entry in entries))

    def _get_input_media(self, subkey, key):
        rlist = []
        for msg in self._media_dict[key][subkey]:
            if key == "videos":
                input_media = InputMediaVideo(
                    media=msg.video.file_id, caption=msg.caption
                )
            else:
                input_media = InputMediaDocument(
                    media=msg.document.file_id, caption=msg.caption
                )
            rlist.append(input_media)
        return rlist

    async def _send_screenshots(self, dirpath, outputs):
        inputs = [
            InputMediaPhoto(ospath.join(dirpath, p), p.rsplit("/", 1)[-1])
            for p in outputs
        ]
        for i in range(0, len(inputs), 10):
            batch = inputs[i : i + 10]
            self._sent_msg = (
                await self._sent_msg.reply_media_group(
                    media=batch,
                    disable_notification=True,
                )
            )[-1]

    async def _send_media_group(self, subkey, key, msgs, client=None):
        for index, msg in enumerate(msgs):
            if self._listener.hybrid_leech or not self._user_session:
                msgs[index] = await self._listener.client.get_messages(
                    chat_id=msg[0], message_ids=msg[1]
                )
            else:
                client = client or TgClient.user
                msgs[index] = await client.get_messages(
                    chat_id=msg[0], message_ids=msg[1]
                )
        msgs_list = await msgs[0].reply_to_message.reply_media_group(
            media=self._get_input_media(subkey, key),
            disable_notification=True,
        )
        for msg in msgs:
            if msg.link in self._msgs_dict:
                del self._msgs_dict[msg.link]
            await delete_message(msg)
        del self._media_dict[key][subkey]
        if self._files_links and (
            self._listener.is_super_chat or self._listener.up_dest
        ):
            for m in msgs_list:
                self._msgs_dict[m.link] = m.caption
        self._sent_msg = msgs_list[-1]
        if self._base_msg:
            await delete_message(self._base_msg)
            self._base_msg = None

    async def upload(self):
        await self._user_settings()
        self._prepared_paths = []
        upload_client = await TgClient.get_upload_client() if self._user_session else None
        res = await self._msg_to_reply(upload_client)
        if not res:
            return
        LOGGER.info(
            "Telegram upload plan: "
            f"name={self._listener.name} | base_path={self._path} | "
            f"user_transmission={self._listener.user_transmission} | "
            f"hybrid_leech={self._listener.hybrid_leech} | "
            f"media_group={self._media_group} | as_doc={self._listener.as_doc} | "
            f"file_parallel={Config.TG_FILE_UPLOAD_CONCURRENCY} | "
            f"split_parallel={Config.TG_SPLIT_UPLOAD_CONCURRENCY}"
        )
        for dirpath, _, files in natsorted(await sync_to_async(walk, self._path)):
            if dirpath.strip().endswith("/yt-dlp-thumb"):
                continue
            if dirpath.strip().endswith("_mltbss"):
                await self._send_screenshots(dirpath, files)
                await rmtree(dirpath, ignore_errors=True)
                continue
            entries = []
            for file_ in natsorted(files):
                self._error = ""
                f_path = ospath.join(dirpath, file_)
                if not await aiopath.exists(f_path):
                    if intervals["stopAll"]:
                        return
                    LOGGER.error(f"{f_path} not exists! Continue uploading!")
                    continue
                try:
                    f_size = await aiopath.getsize(f_path)
                    self._total_files += 1
                    if f_size == 0:
                        LOGGER.error(
                            f"{f_path} size is zero, telegram don't upload zero size files"
                        )
                        self._corrupted += 1
                        continue
                    if self._listener.is_cancelled:
                        return
                    cap_mono, f_path = await self._prepare_file(
                        file_,
                        dirpath,
                        f_path,
                        f_size,
                    )
                    self._prepared_paths.append(f_path)
                    if self._last_msg_in_group:
                        group_lists = [
                            x for v in self._media_dict.values() for x in v.keys()
                        ]
                        match = re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", f_path)
                        if not match or match and match.group(0) not in group_lists:
                            for key, value in list(self._media_dict.items()):
                                for subkey, msgs in list(value.items()):
                                    if len(msgs) > 1:
                                        await self._send_media_group(subkey, key, msgs)
                except Exception as err:
                    if isinstance(err, RetryError):
                        LOGGER.info(
                            f"Total Attempts: {err.last_attempt.attempt_number}"
                        )
                        err = err.last_attempt.exception()
                    LOGGER.error(f"{err}. Path: {f_path}")
                    self._error = str(err)
                    self._corrupted += 1
                    if self._listener.is_cancelled:
                        return
                    if not self._listener.is_cancelled and await aiopath.exists(f_path):
                        try:
                            await remove(f_path)
                        except (OSError, Exception):
                            pass
                    continue
                entries.append(
                    {
                        "caption": cap_mono,
                        "file": ospath.basename(f_path),
                        "path": f_path,
                        "size": f_size,
                        "user_session": self._get_upload_session(f_size),
                    }
                )
            if self._can_parallelize_split_uploads(entries):
                await self._parallel_upload_entries(
                    entries,
                    Config.TG_SPLIT_UPLOAD_CONCURRENCY,
                    "split",
                )
            elif self._can_parallelize_regular_uploads(entries):
                await self._parallel_upload_entries(
                    entries,
                    Config.TG_FILE_UPLOAD_CONCURRENCY,
                    "files",
                )
            else:
                if entries:
                    LOGGER.info(
                        "Telegram sequential upload batch: "
                        f"files={len(entries)} | "
                        f"reason={'media_group_enabled' if self._media_group else 'non_split_or_single'}"
                    )
                for entry in entries:
                    if self._listener.is_cancelled:
                        return
                    self._last_msg_in_group = False
                    await self._upload_entry(entry)
                    if self._listener.is_cancelled:
                        return
                    await sleep(1)
        for key, value in list(self._media_dict.items()):
            for subkey, msgs in list(value.items()):
                if len(msgs) > 1:
                    try:
                        await self._send_media_group(subkey, key, msgs)
                    except Exception as e:
                        LOGGER.info(
                            f"While sending media group at the end of task. Error: {e}"
                        )
        if self._base_msg:
            await delete_message(self._base_msg)
            self._base_msg = None
        if self._listener.preserve_upload_files:
            existing_paths = [
                path for path in self._prepared_paths if await aiopath.exists(path)
            ]
            if len(existing_paths) == 1:
                self._listener.secondary_drive_source = existing_paths[0]
            elif existing_paths:
                self._listener.secondary_drive_source = self._path
        if self._listener.is_cancelled:
            return
        if self._total_files == 0:
            await self._listener.on_upload_error(
                "No files to upload. In case you have filled EXCLUDED/INCLUDED EXTENSIONS, then check if all files have those extensions or not."
            )
            return
        if self._total_files <= self._corrupted:
            await self._listener.on_upload_error(
                f"Files Corrupted or unable to upload. {self._error or 'Check logs!'}"
            )
            return
        LOGGER.info(f"Leech Completed: {self._listener.name}")
        await self._listener.on_upload_complete(
            None, self._msgs_dict, self._total_files, self._corrupted
        )
        return

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def _upload_file(
        self,
        cap_mono,
        file,
        o_path,
        force_document=False,
        reply_msg=None,
        user_session=None,
        progress_key=None,
        upload_client=None,
    ):
        if (
            self._thumb is not None
            and not await aiopath.exists(self._thumb)
            and self._thumb != "none"
        ):
            self._thumb = None
        thumb = self._thumb
        upload_path = o_path
        sent_msg = None
        is_corrupted = False
        if reply_msg is None:
            reply_msg = self._sent_msg
        if user_session is None:
            user_session = self._user_session
        if user_session and upload_client is None:
            upload_client = await TgClient.get_upload_client()
        if progress_key is None:
            progress_key = upload_path
        delete_base_msg = progress_key == "__sequential__"
        self._upload_started_at[progress_key] = time()
        try:
            is_video, is_audio, is_image = await get_document_type(upload_path)
            media_kind = (
                "document"
                if self._listener.as_doc or force_document
                else "video"
                if is_video
                else "audio"
                if is_audio
                else "photo"
                if is_image
                else "document"
            )
            LOGGER.info(
                "Telegram upload dispatch: "
                f"name={file} | kind={media_kind} | "
                f"session={self._get_session_name(user_session)} | "
                f"path={upload_path}"
            )

            if not is_image and thumb is None:
                file_name = ospath.splitext(file)[0]
                thumb_path = f"{self._path}/yt-dlp-thumb/{file_name}.jpg"
                if await aiopath.isfile(thumb_path):
                    thumb = thumb_path
                elif await aiopath.isfile(thumb_path.replace("/yt-dlp-thumb", "")):
                    thumb = thumb_path.replace("/yt-dlp-thumb", "")
                elif is_audio and not is_video:
                    thumb = await get_audio_thumbnail(upload_path)

            if (
                self._listener.as_doc
                or force_document
                or (not is_video and not is_audio and not is_image)
            ):
                key = "documents"
                if is_video and thumb is None:
                    thumb = await get_video_thumbnail(upload_path, None)

                if self._listener.is_cancelled:
                    return reply_msg, is_corrupted
                if thumb == "none":
                    thumb = None
                sent_msg = await reply_msg.reply_document(
                    document=upload_path,
                    thumb=thumb,
                    caption=cap_mono,
                    force_document=True,
                    disable_notification=True,
                    progress=self._upload_progress,
                    progress_args=(progress_key, user_session, upload_client),
                )
            elif is_video:
                key = "videos"
                duration = (await get_media_info(upload_path))[0]
                if thumb is None and self._listener.thumbnail_layout:
                    thumb = await get_multiple_frames_thumbnail(
                        upload_path,
                        self._listener.thumbnail_layout,
                        self._listener.screen_shots,
                    )
                if thumb is None:
                    thumb = await get_video_thumbnail(upload_path, duration)
                if thumb is not None and thumb != "none":
                    with Image.open(thumb) as img:
                        width, height = img.size
                else:
                    width = 480
                    height = 320
                if self._listener.is_cancelled:
                    return reply_msg, is_corrupted
                if thumb == "none":
                    thumb = None
                sent_msg = await reply_msg.reply_video(
                    video=upload_path,
                    caption=cap_mono,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=thumb,
                    supports_streaming=True,
                    disable_notification=True,
                    progress=self._upload_progress,
                    progress_args=(progress_key, user_session, upload_client),
                )
            elif is_audio:
                key = "audios"
                duration, artist, title = await get_media_info(upload_path)
                if self._listener.is_cancelled:
                    return reply_msg, is_corrupted
                if thumb == "none":
                    thumb = None
                sent_msg = await reply_msg.reply_audio(
                    audio=upload_path,
                    caption=cap_mono,
                    duration=duration,
                    performer=artist,
                    title=title,
                    thumb=thumb,
                    disable_notification=True,
                    progress=self._upload_progress,
                    progress_args=(progress_key, user_session, upload_client),
                )
            else:
                key = "photos"
                if self._listener.is_cancelled:
                    return reply_msg, is_corrupted
                sent_msg = await reply_msg.reply_photo(
                    photo=upload_path,
                    caption=cap_mono,
                    disable_notification=True,
                    progress=self._upload_progress,
                    progress_args=(progress_key, user_session, upload_client),
                )

            if (
                not self._listener.is_cancelled
                and self._media_group
                and (sent_msg.video or sent_msg.document)
            ):
                key = "documents" if sent_msg.document else "videos"
                if match := re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", o_path):

                    pname = match.group(0)
                    if pname in self._media_dict[key].keys():
                        self._media_dict[key][pname].append(
                            [sent_msg.chat.id, sent_msg.id]
                        )
                    else:
                        self._media_dict[key][pname] = [
                            [sent_msg.chat.id, sent_msg.id]
                        ]
                    msgs = self._media_dict[key][pname]
                    if len(msgs) == 10:
                        await self._send_media_group(pname, key, msgs)
                    else:
                        self._last_msg_in_group = True
            if (
                self._thumb is None
                and thumb is not None
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            if self._base_msg and not self._last_msg_in_group and delete_base_msg:
                await delete_message(self._base_msg)
                self._base_msg = None
        except (FloodWait, FloodPremiumWait) as f:
            LOGGER.warning(
                "Telegram upload flood wait: "
                f"name={file} | session={self._get_session_name(user_session)} | "
                f"wait={f.value}s | path={upload_path}"
            )
            await sleep(f.value * 1.3)
            if (
                self._thumb is None
                and thumb is not None
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            return await self._upload_file(
                cap_mono,
                file,
                o_path,
                force_document=force_document,
                reply_msg=reply_msg,
                user_session=user_session,
                progress_key=progress_key,
                upload_client=upload_client,
            )
        except Exception as err:
            if (
                self._thumb is None
                and thumb is not None
                and await aiopath.exists(thumb)
            ):
                await remove(thumb)
            err_type = "RPCError: " if isinstance(err, RPCError) else ""
            LOGGER.error(f"{err_type}{err}. Path: {upload_path}")
            if isinstance(err, BadRequest) and key != "documents":
                LOGGER.error(f"Retrying As Document. Path: {upload_path}")
                return await self._upload_file(
                    cap_mono,
                    file,
                    o_path,
                    True,
                    reply_msg=reply_msg,
                    user_session=user_session,
                    progress_key=progress_key,
                    upload_client=upload_client,
                )
            raise err
        finally:
            self._upload_started_at.pop(progress_key, None)
        return sent_msg, is_corrupted

    @property
    def speed(self):
        try:
            return self._processed_bytes / (time() - self._start_time)
        except:
            return 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    async def cancel_task(self):
        self._listener.is_cancelled = True
        LOGGER.info(f"Cancelling Upload: {self._listener.name}")
        await self._listener.on_upload_error("your upload has been stopped!")
