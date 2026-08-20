from PIL import Image
from aioshutil import rmtree
from asyncio import Lock, Semaphore, gather, sleep
from logging import getLogger
from natsort import natsorted
from os import walk, path as ospath
from re import match as re_match, sub as re_sub
from time import time

from aiofiles.os import path as aiopath, remove, rename
from pytdbot.types import (
    InputFileLocal,
    InputMessageReplyToMessage,
    InputMessageAudio,
    InputMessageDocument,
    InputMessagePhoto,
    InputMessageVideo,
    InputThumbnail,
    MessageSendOptions,
    MessageTopicForum,
)
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
    RetryError,
)

from ...core.config_manager import Config
from ...core.tdlib_manager import TdlibManager
from ..ext_utils.bot_utils import sync_to_async
from ..ext_utils.files_utils import get_base_name, is_archive
from ..ext_utils.media_utils import (
    get_audio_thumbnail,
    get_document_type,
    get_media_info,
    get_leech_media_context,
    get_multiple_frames_thumbnail,
    get_video_thumbnail,
    render_leech_caption,
)
from ..ext_utils.status_utils import get_readable_file_size
from ..telegram_helper.tdlib_progress import tracker

LOGGER = getLogger(__name__)


class TdlibTelegramUploader:
    def __init__(self, listener, path):
        self._listener = listener
        self._path = path
        self._start_time = time()
        self._processed_bytes = 0
        self._processed_bytes_lock = Lock()
        self._total_files = 0
        self._corrupted = 0
        self._is_corrupted = False
        self._error = ""
        self._thumb = self._listener.thumb or f"thumbnails/{listener.user_id}.jpg"
        self._lprefix = ""
        self._up_path = ""
        self._msgs_dict = {}
        self._msgs_dict_lock = Lock()
        self._future = None
        self._temp_message = None
        self._target_chat_id = None
        self._reply_to_message_id = None
        self._reply_to_lock = Lock()
        self._topic = None
        self._base_message = None
        self._last_progress_log = 0.0
        self._prepared_paths = []

    @property
    def speed(self):
        try:
            return self._processed_bytes / (time() - self._start_time)
        except Exception:
            return 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    async def cancel_task(self):
        self._listener.is_cancelled = True
        if self._future is not None:
            self._future.cancel()
        if self._temp_message is not None:
            try:
                await self._temp_message.delete()
            except Exception:
                pass
        LOGGER.info(f"Cancelling TDLib upload: {self._listener.name}")
        await self._listener.on_upload_error("your upload has been stopped!")

    async def _upload_progress(self, key, progress_dict, _, last_uploaded_ref):
        """Progress callback. last_uploaded_ref is a 1-element list so parallel
        tasks each track their own byte offset without sharing state."""
        if self._listener.is_cancelled:
            if self._future is not None:
                self._future.cancel()
            if self._temp_message is not None:
                try:
                    await self._temp_message.delete()
                except Exception:
                    pass
            await tracker.cancel_progress(key)
            return
        transferred = progress_dict.get("transferred", 0)
        chunk_size = max(0, transferred - last_uploaded_ref[0])
        last_uploaded_ref[0] = transferred
        async with self._processed_bytes_lock:
            self._processed_bytes += chunk_size
        now = time()
        total = progress_dict.get("total") or 0
        if now - self._last_progress_log >= 5 or progress_dict.get("is_completed"):
            pct = (transferred * 100 / total) if total else 0.0
            LOGGER.info(
                "TDLib upload progress: "
                f"name={self._listener.name} | current={transferred} | total={total} | "
                f"pct={pct:.2f}% | speed={self.speed / 1024 / 1024:.2f}MB/s"
            )
            self._last_progress_log = now

    async def _user_settings(self):
        self._lprefix = self._listener.user_dict.get("LEECH_FILENAME_PREFIX") or (
            Config.LEECH_FILENAME_PREFIX
            if "LEECH_FILENAME_PREFIX" not in self._listener.user_dict
            else ""
        )
        if self._thumb and self._thumb != "none" and not str(self._thumb).startswith("/"):
            self._thumb = ospath.join("/app", str(self._thumb))
        if self._thumb != "none" and not await aiopath.exists(self._thumb):
            self._thumb = None

    async def _setup_destination(self):
        if self._listener.chat_thread_id:
            self._topic = MessageTopicForum(self._listener.chat_thread_id)
        if self._listener.up_dest:
            self._target_chat_id = await TdlibManager.resolve_chat_id(self._listener.up_dest)
            text = (
                self._listener.message.link
                if self._listener.is_super_chat
                else self._listener.message.text.lstrip("/")
            )
            res = await TdlibManager.user.sendTextMessage(
                chat_id=self._target_chat_id,
                text=text,
                disable_web_page_preview=True,
                topic_id=self._topic,
                disable_notification=True,
            )
            if res.is_error:
                raise ValueError(res["message"])
            self._base_message = res
            self._reply_to_message_id = res.id
        else:
            self._target_chat_id = self._listener.message.chat.id
            self._reply_to_message_id = self._listener.mid

    async def _prepare_file(self, file_, dirpath, file_size):
        if self._lprefix:
            self._lprefix = re_sub("<.*?>", "", self._lprefix)
            new_path = ospath.join(dirpath, f"{self._lprefix} {file_}")
            try:
                await rename(self._up_path, new_path)
                self._up_path = new_path
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
            name = name[: 60 - extn]
            new_path = ospath.join(dirpath, f"{name}{ext}")
            try:
                await rename(self._up_path, new_path)
                self._up_path = new_path
            except OSError:
                pass
        display_name = ospath.basename(self._up_path)
        details = await get_leech_media_context(
            self._listener,
            file_,
            self._up_path,
            display_name,
            file_size,
        )
        self._listener.upload_media_details[display_name] = details
        self._listener.upload_media_details[file_] = details
        return await render_leech_caption(
            self._listener,
            file_,
            self._up_path,
            display_name,
            file_size,
        )

    def _is_split_file(self, file_path):
        return bool(
            re_match(r".+(?=\.0*\d+$)|.+(?=\.part\d+\..+$)", ospath.basename(file_path))
        )

    async def _wait_for_sent_message(self, sent_msg, timeout=300):
        deadline = time() + timeout
        last_msg = sent_msg
        while time() < deadline:
            res = await TdlibManager.user.getMessage(
                chat_id=sent_msg.chat_id,
                message_id=sent_msg.id,
            )
            if not getattr(res, "is_error", False):
                last_msg = res
                sending_state = getattr(res, "sending_state", None)
                if sending_state is None:
                    return res
                state_type = sending_state.getType()
                if state_type == "messageSendingStateFailed":
                    raise ValueError(sending_state.error.message)
            await sleep(2)
        LOGGER.warning(
            "TDLib send finalize timed out; using last known message state: "
            f"name={self._listener.name} | chat_id={sent_msg.chat_id} | message_id={sent_msg.id}"
        )
        return last_msg

    async def _send_content(self, content, reply_to_message_id, client=None):
        client = client or TdlibManager.user
        reply_to = None
        if reply_to_message_id:
            reply_to = InputMessageReplyToMessage(message_id=reply_to_message_id)
        res = await client.sendMessageWithContent(
            chat_id=self._target_chat_id,
            content=content,
            disable_notification=True,
            topic_id=self._topic,
            reply_to=reply_to,
        )
        if getattr(res, "is_error", False):
            if wait_for := getattr(res, "limited_seconds", None):
                LOGGER.warning(res["message"])
                await sleep(wait_for * 1.2)
                return await self._send_content(content, reply_to_message_id)
            raise ValueError(res["message"])
        return res

    async def _build_content(
        self,
        cap_mono,
        file_name,
        upload_path,
        force_document=False,
        client=None,
    ):
        client = client or TdlibManager.user
        thumb = self._thumb
        is_video, is_audio, is_image = await get_document_type(upload_path)
        if not is_image and thumb is None:
            root_name = ospath.splitext(file_name)[0]
            thumb_path = f"{self._path}/yt-dlp-thumb/{root_name}.jpg"
            if await aiopath.isfile(thumb_path):
                thumb = thumb_path
            elif await aiopath.isfile(thumb_path.replace("/yt-dlp-thumb", "")):
                thumb = thumb_path.replace("/yt-dlp-thumb", "")
            elif is_audio and not is_video:
                thumb = await get_audio_thumbnail(upload_path)

        caption = await client.parseText(cap_mono)
        thumbnail = None
        if thumb and thumb != "none" and await aiopath.exists(thumb):
            with Image.open(thumb) as img:
                width, height = img.size
            thumbnail = InputThumbnail(
                InputFileLocal(path=thumb),
                width=width,
                height=height,
            )

        if (
            self._listener.as_doc
            or force_document
            or (not is_video and not is_audio and not is_image)
        ):
            return InputMessageDocument(
                document=InputFileLocal(path=upload_path),
                thumbnail=thumbnail,
                disable_content_type_detection=True,
                caption=caption,
            )
        if is_video:
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
                thumbnail = InputThumbnail(
                    InputFileLocal(path=thumb),
                    width=width,
                    height=height,
                )
            else:
                width = 480
                height = 320
            return InputMessageVideo(
                video=InputFileLocal(path=upload_path),
                thumbnail=thumbnail,
                duration=duration,
                width=width,
                height=height,
                supports_streaming=True,
                caption=caption,
            )
        if is_audio:
            duration, artist, title = await get_media_info(upload_path)
            return InputMessageAudio(
                audio=InputFileLocal(path=upload_path),
                album_cover_thumbnail=thumbnail,
                duration=duration,
                title=title,
                performer=artist,
                caption=caption,
            )
        return InputMessagePhoto(
            photo=InputFileLocal(path=upload_path),
            caption=caption,
        )

    async def _maybe_cleanup_thumb(self, thumb):
        if self._thumb is None and thumb and thumb != "none" and await aiopath.exists(thumb):
            await remove(thumb)

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def _upload_file(
        self,
        cap_mono,
        file_name,
        upload_path,
        force_document=False,
        parallel=False,
        upload_client=None,
    ):
        """Upload a single file to Telegram via TDLib.
        If parallel=True the reply_to chain is managed via the shared lock so
        parallel split-part uploads thread safely through _reply_to_message_id.
        """
        if self._listener.is_cancelled:
            return
        self._is_corrupted = False
        upload_client = upload_client or TdlibManager.user
        thumb_before = self._thumb
        last_uploaded_ref = [0]

        # Capture reply-to BEFORE sending so parallel tasks don't race
        async with self._reply_to_lock:
            current_reply_to = self._reply_to_message_id

        try:
            await tracker.add_to_progress(
                upload_path,
                callback=lambda k, pd, fid: self._upload_progress(k, pd, fid, last_uploaded_ref),
            )
            content = await self._build_content(
                cap_mono,
                file_name,
                upload_path,
                force_document,
                client=upload_client,
            )
            sent_msg = await self._send_content(
                content,
                current_reply_to,
                client=upload_client,
            )
            self._temp_message = None

            # Update reply chain: sequential uploads chain forward, parallel parts reply to
            # the same anchor message (they all arrive as a batch in the chat)
            if not parallel:
                async with self._reply_to_lock:
                    self._reply_to_message_id = sent_msg.id

            if self._base_message is not None and not parallel:
                try:
                    await self._base_message.delete()
                except Exception:
                    pass
                self._base_message = None

            if (
                self._listener.is_super_chat or self._listener.up_dest
            ) and not self._listener.private_link:
                try:
                    msg_link = await sent_msg.getMessageLink(
                        in_message_thread=bool(self._listener.chat_thread_id)
                    )
                    async with self._msgs_dict_lock:
                        self._msgs_dict[msg_link.link] = file_name
                except Exception:
                    pass
        except Exception as e:
            err_message = str(e)
            if not force_document and "document" not in err_message.lower():
                try:
                    return await self._upload_file(
                        cap_mono,
                        file_name,
                        upload_path,
                        force_document=True,
                        parallel=parallel,
                        upload_client=upload_client,
                    )
                except Exception:
                    pass
            raise
        finally:
            await self._maybe_cleanup_thumb(thumb_before)

    async def _upload_entry(self, entry, parallel=False):
        """Wrap _upload_file with logging and cleanup; used in both sequential and parallel paths."""
        file_name = entry["file"]
        upload_path = entry["path"]
        upload_client = await TdlibManager.get_upload_client()
        upload_client_db = getattr(upload_client, "_mltb_db_path", "unknown")
        upload_client_index = getattr(upload_client, "_mltb_db_index", 1)
        upload_started_at = time()
        LOGGER.info(
            "TDLib upload start: "
            f"name={file_name} | size={get_readable_file_size(entry['size'])} | "
            f"parallel={parallel} | db={upload_client_db} | index={upload_client_index}"
        )
        try:
            await self._upload_file(
                cap_mono=entry["caption"],
                file_name=file_name,
                upload_path=upload_path,
                parallel=parallel,
                upload_client=upload_client,
            )
            elapsed = max(0.001, time() - upload_started_at)
            LOGGER.info(
                "TDLib upload done: "
                f"name={file_name} | size={get_readable_file_size(entry['size'])} | "
                f"elapsed={round(elapsed, 2)}s | "
                f"avg_speed={get_readable_file_size(entry['size'] / elapsed)}/s"
            )
        except RetryError as err:
            LOGGER.info(f"Total Attempts: {err.last_attempt.attempt_number}")
            elapsed = max(0.001, time() - upload_started_at)
            LOGGER.error(
                "TDLib upload failed after retries: "
                f"name={file_name} | elapsed={round(elapsed, 2)}s | error={err.last_attempt.exception()}"
            )
            self._error = str(err.last_attempt.exception())
            self._corrupted += 1
        except Exception as err:
            elapsed = max(0.001, time() - upload_started_at)
            LOGGER.error(
                "TDLib upload failed: "
                f"name={file_name} | elapsed={round(elapsed, 2)}s | error={err}"
            )
            self._error = str(err)
            self._corrupted += 1
            if self._listener.is_cancelled:
                return
        finally:
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
        """Upload a batch of files concurrently with a bounded worker pool."""
        limit = min(limit, len(entries))
        LOGGER.info(
            "TDLib parallel upload batch: "
            f"type={label} | parts={len(entries)} | parallel_limit={limit}"
        )
        semaphore = Semaphore(limit)

        async def runner(entry):
            async with semaphore:
                if self._listener.is_cancelled:
                    return
                await self._upload_entry(entry, parallel=True)

        await gather(*(runner(entry) for entry in entries))

    def _can_parallelize_split(self, entries):
        if len(entries) < 2:
            return False
        return all(self._is_split_file(e["path"]) for e in entries)

    def _can_parallelize_regular(self, entries):
        if len(entries) < 2:
            return False
        return True

    async def upload(self):
        await self._user_settings()
        self._prepared_paths = []
        await self._setup_destination()
        LOGGER.info(
            "TDLib upload plan: "
            f"name={self._listener.name} | base_path={self._path} | "
            f"file_parallel={Config.TG_FILE_UPLOAD_CONCURRENCY} | "
            f"split_parallel={Config.TG_SPLIT_UPLOAD_CONCURRENCY}"
        )
        all_entries = []
        for dirpath, _, files in natsorted(await sync_to_async(walk, self._path)):
            if dirpath.strip().endswith("/yt-dlp-thumb"):
                continue
            if dirpath.strip().endswith("_mltbss"):
                await rmtree(dirpath, ignore_errors=True)
                continue
            for file_ in natsorted(files):
                self._error = ""
                self._up_path = f_path = ospath.join(dirpath, file_)
                if not await aiopath.exists(self._up_path):
                    LOGGER.error(f"{self._up_path} not exists! Continue uploading!")
                    continue
                try:
                    f_size = await aiopath.getsize(self._up_path)
                    self._total_files += 1
                    if f_size == 0:
                        LOGGER.error(f"{self._up_path} size is zero, skipping upload")
                        self._corrupted += 1
                        continue
                    if self._listener.is_cancelled:
                        return
                    cap_mono = await self._prepare_file(file_, dirpath, f_size)
                    self._prepared_paths.append(self._up_path)
                except Exception as err:
                    LOGGER.error(f"TDLib prepare failed: {err}. Path: {self._up_path}")
                    self._error = str(err)
                    self._corrupted += 1
                    if self._listener.is_cancelled:
                        return
                    continue
                all_entries.append(
                    {
                        "caption": cap_mono,
                        "file": ospath.basename(self._up_path),
                        "path": self._up_path,
                        "size": f_size,
                    }
                )

        if all_entries:
            LOGGER.info(
                "TDLib upload batch collected: "
                f"name={self._listener.name} | files={len(all_entries)}"
            )

        if self._can_parallelize_split(all_entries):
            await self._parallel_upload_entries(
                all_entries,
                Config.TG_SPLIT_UPLOAD_CONCURRENCY,
                "split",
            )
        elif self._can_parallelize_regular(all_entries):
            await self._parallel_upload_entries(
                all_entries,
                Config.TG_FILE_UPLOAD_CONCURRENCY,
                "files",
            )
        else:
            for entry in all_entries:
                if self._listener.is_cancelled:
                    return
                await self._upload_entry(entry, parallel=False)
                if self._listener.is_cancelled:
                    return
                await sleep(0.1)  # keep a tiny delay only for true sequential fallback

        if self._base_message is not None:
            try:
                await self._base_message.delete()
            except Exception:
                pass
            self._base_message = None

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
                "No files to upload. In case you have filled EXCLUDED_EXTENSIONS, then check if all files have those extensions or not."
            )
            return
        if self._total_files <= self._corrupted:
            await self._listener.on_upload_error(
                f"Files Corrupted or unable to upload. {self._error or 'Check logs!'}"
            )
            return
        elapsed = max(time() - self._start_time, 0.001)
        LOGGER.info(
            "TDLib upload done: "
            f"name={self._listener.name} | elapsed={elapsed:.2f}s | "
            f"avg_speed={self._processed_bytes / elapsed / 1024 / 1024:.2f}MB/s"
        )
        LOGGER.info(f"TDLib leech completed: {self._listener.name}")
        await self._listener.on_upload_complete(
            None,
            self._msgs_dict,
            self._total_files,
            self._corrupted,
        )
