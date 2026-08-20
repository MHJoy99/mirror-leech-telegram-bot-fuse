import json
from PIL import Image
from aiofiles.os import remove, path as aiopath, makedirs, makedirs as aiomakedirs
from asyncio import (
    create_subprocess_exec,
    gather,
    wait_for,
)
from asyncio.subprocess import PIPE
from os import path as ospath
from re import search as re_search, escape
from time import time
from aioshutil import rmtree

from ... import LOGGER, DOWNLOAD_DIR, threads, cores
from ...core.config_manager import Config
from .bot_utils import cmd_exec, sync_to_async
from .files_utils import get_mime_type, is_archive, is_archive_split
from .status_utils import (
    get_readable_file_size,
    get_readable_time,
    time_to_seconds,
)

try:
    from langcodes import Language
except ImportError:
    Language = None


async def create_thumb(msg, _id=""):
    if not _id:
        _id = time()
        path = f"{DOWNLOAD_DIR}thumbnails"
    else:
        path = "thumbnails"
    await makedirs(path, exist_ok=True)
    photo_dir = await msg.download()
    output = ospath.join(path, f"{_id}.jpg")
    await sync_to_async(Image.open(photo_dir).convert("RGB").save, output, "JPEG")
    await remove(photo_dir)
    return output


def ffconcat_escape(path):
    return path.replace("'", r"'\''")


def _display_language(lang_code):
    code = str(lang_code or "").strip()
    if not code or code.lower() in {"und", "unknown", "n/a"}:
        return None
    manual_map = {
        "ben": "Bengali",
        "bn": "Bengali",
        "hin": "Hindi",
        "hi": "Hindi",
        "eng": "English",
        "en": "English",
        "tam": "Tamil",
        "ta": "Tamil",
        "tel": "Telugu",
        "te": "Telugu",
        "mal": "Malayalam",
        "ml": "Malayalam",
        "kan": "Kannada",
        "kn": "Kannada",
    }
    if code.lower() in manual_map:
        return manual_map[code.lower()]
    if Language is None:
        return code
    try:
        display = Language.get(code).display_name()
        return display or code
    except Exception:
        return code


def _normalize_metadata_value(value):
    value = str(value or "").strip()
    return value or "N/A"


def _infer_languages_from_text(*values):
    text = " ".join(str(value or "") for value in values).lower()
    matches = []
    language_keywords = {
        "Bengali": ["bengali", "bangla", "bn"],
        "Hindi": ["hindi", "hin", "hi"],
        "English": ["english", "eng", "en"],
        "Tamil": ["tamil", "tam", "ta"],
        "Telugu": ["telugu", "tel", "te"],
        "Malayalam": ["malayalam", "mal", "ml"],
        "Kannada": ["kannada", "kan", "kn"],
        "Punjabi": ["punjabi", "panjabi", "pa"],
        "Urdu": ["urdu", "ur"],
        "Arabic": ["arabic", "ara", "ar"],
    }
    for display_name, keywords in language_keywords.items():
        for keyword in keywords:
            if keyword in text:
                matches.append(display_name)
                break
    if "dual audio" in text and len(matches) >= 2:
        return ", ".join(dict.fromkeys(matches))
    return ", ".join(dict.fromkeys(matches))


async def get_media_info(path, extra_info=False):
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ]
        )
    except Exception as e:
        LOGGER.error(f"Get Media Info: {e}. Mostly File not found! - File: {path}")
        return (0, "N/A", "N/A", "N/A") if extra_info else (0, None, None)
    if result[0] and result[2] == 0:
        try:
            ffprobe_output = json.loads(result[0])
        except json.JSONDecodeError:
            LOGGER.error(f"get_media_info: invalid ffprobe json for {path}")
            return (0, "N/A", "N/A", "N/A") if extra_info else (0, None, None)
        fields = ffprobe_output.get("format")
        if fields is None:
            LOGGER.error(f"get_media_info: {result}")
            return (0, "N/A", "N/A", "N/A") if extra_info else (0, None, None)
        duration = round(float(fields.get("duration", 0)))
        if extra_info:
            audio_languages = []
            subtitle_languages = []
            quality = "N/A"
            for stream in ffprobe_output.get("streams", []) or []:
                codec_type = stream.get("codec_type")
                if codec_type == "video" and quality == "N/A":
                    if height := stream.get("height"):
                        height = int(height)
                        quality = (
                            f"{480 if height <= 480 else 540 if height <= 540 else 720 if height <= 720 else 1080 if height <= 1080 else 2160 if height <= 2160 else 4320 if height <= 4320 else 8640}p"
                        )
                language = _display_language(stream.get("tags", {}).get("language"))
                if not language:
                    continue
                if codec_type == "audio" and language not in audio_languages:
                    audio_languages.append(language)
                elif codec_type == "subtitle" and language not in subtitle_languages:
                    subtitle_languages.append(language)
            return (
                duration,
                _normalize_metadata_value(quality),
                _normalize_metadata_value(", ".join(audio_languages)),
                _normalize_metadata_value(", ".join(subtitle_languages)),
            )
        tags = fields.get("tags", {})
        artist = tags.get("artist") or tags.get("ARTIST") or tags.get("Artist")
        title = tags.get("title") or tags.get("TITLE") or tags.get("Title")
        return duration, artist, title
    return (0, "N/A", "N/A", "N/A") if extra_info else (0, None, None)


async def render_leech_caption(listener, file_name, upload_path, display_name, file_size):
    context = await get_leech_media_context(
        listener,
        file_name,
        upload_path,
        display_name,
        file_size,
    )
    caption_template = listener.user_dict.get("LEECH_CAPTION")
    if caption_template is None:
        caption_template = Config.LEECH_CAPTION
    if not caption_template:
        return f"<code>{display_name}</code>"
    try:
        return caption_template.format(**context)
    except KeyError as exc:
        LOGGER.warning(
            f"Invalid LEECH_CAPTION placeholder {exc} for user {listener.user_id}; "
            "falling back to default caption."
        )
    except Exception as exc:
        LOGGER.warning(
            f"Failed to render leech caption for {file_name} at {upload_path}: {exc}"
        )
    return f"<code>{display_name}</code>"


async def get_leech_media_context(listener, file_name, upload_path, display_name, file_size):
    duration_seconds = 0
    quality = languages = subtitles = "N/A"
    try:
        duration_seconds, quality, languages, subtitles = await get_media_info(
            upload_path, extra_info=True
        )
    except Exception as exc:
        LOGGER.warning(f"Leech caption metadata fallback for {upload_path}: {exc}")

    inferred_languages = _infer_languages_from_text(display_name, file_name)
    if inferred_languages and (
        languages == "N/A"
        or languages.lower() in {"unknown", "ben", "bn", "hin", "hi", "eng", "en", "tam", "ta"}
    ):
        languages = inferred_languages
    if subtitles == "N/A":
        subtitles = "None"
    if languages == "N/A":
        languages = "Unknown"
    duration = get_readable_time(duration_seconds) if duration_seconds else "Unknown"

    context = {
        "filename": display_name,
        "originalname": file_name,
        "uploadname": display_name,
        "size": get_readable_file_size(file_size),
        "duration": duration,
        "quality": quality,
        "languages": languages,
        "subtitles": subtitles,
    }
    return context


async def get_document_type(path):
    is_video, is_audio, is_image = False, False, False
    if (
        is_archive(path)
        or is_archive_split(path)
        or re_search(r".+(\.|_)(rar|7z|zip|bin)(\.0*\d+)?$", path)
    ):
        return is_video, is_audio, is_image
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type.startswith("image"):
        return False, False, True
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                path,
            ]
        )
        if result[1] and mime_type.startswith("video"):
            is_video = True
    except Exception as e:
        LOGGER.error(f"Get Document Type: {e}. Mostly File not found! - File: {path}")
        if mime_type.startswith("audio"):
            return False, True, False
        if not mime_type.startswith("video") and not mime_type.endswith("octet-stream"):
            return is_video, is_audio, is_image
        if mime_type.startswith("video"):
            is_video = True
        return is_video, is_audio, is_image
    if result[0] and result[2] == 0:
        try:
            fields = json.loads(result[0]).get("streams")
        except Exception:
            fields = None
        if fields is None:
            LOGGER.error(f"get_document_type: {result}")
            return is_video, is_audio, is_image
        is_video = False
        for stream in fields:
            if stream.get("codec_type") == "video":
                codec_name = stream.get("codec_name", "").lower()
                if codec_name not in {"mjpeg", "png", "bmp"}:
                    is_video = True
            elif stream.get("codec_type") == "audio":
                is_audio = True
    return is_video, is_audio, is_image


async def take_ss(video_file, ss_nb) -> bool:
    duration = (await get_media_info(video_file))[0]
    if duration != 0:
        dirpath, name = video_file.rsplit("/", 1)
        name, _ = ospath.splitext(name)
        dirpath = f"{dirpath}/{name}_mltbss"
        await makedirs(dirpath, exist_ok=True)
        interval = duration // (ss_nb + 1)
        cap_time = interval
        cmds = []
        for i in range(ss_nb):
            output = f"{dirpath}/SS.{name}_{i:02}.png"
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{cap_time}",
                "-i",
                video_file,
                "-q:v",
                "1",
                "-frames:v",
                "1",
                "-threads",
                f"{threads}",
                output,
            ]
            cap_time += interval
            cmds.append(cmd_exec(cmd))
        try:
            resutls = await wait_for(gather(*cmds), timeout=60)
            if resutls[0][2] != 0:
                LOGGER.error(
                    f"Error while creating screenshots from video. Path: {video_file}. stderr: {resutls[0][1]}"
                )
                await rmtree(dirpath, ignore_errors=True)
                return False
        except:
            LOGGER.error(
                f"Error while creating screenshots from video. Path: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
            )
            await rmtree(dirpath, ignore_errors=True)
            return False
        return dirpath
    else:
        LOGGER.error("take_ss: Can't get the duration of video")
        return False


async def get_audio_thumbnail(audio_file):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        audio_file,
        "-an",
        "-vcodec",
        "copy",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while extracting thumbnail from audio. Name: {audio_file} stderr: {err}"
            )
            return None
    except:
        LOGGER.error(
            f"Error while extracting thumbnail from audio. Name: {audio_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    return output


async def get_video_thumbnail(video_file, duration):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration // 2
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{duration}",
        "-i",
        video_file,
        "-vf",
        "thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while extracting thumbnail from video. Name: {video_file} stderr: {err}"
            )
            return None
    except:
        LOGGER.error(
            f"Error while extracting thumbnail from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    return output


async def get_multiple_frames_thumbnail(video_file, layout, keep_screenshots):
    ss_nb = layout.split("x")
    ss_nb = int(ss_nb[0]) * int(ss_nb[1])
    dirpath = await take_ss(video_file, ss_nb)
    if not dirpath:
        return None
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-pattern_type",
        "glob",
        "-i",
        f"{escape(dirpath)}/*.png",
        "-vf",
        f"tile={layout}, thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while combining thumbnails for video. Name: {video_file} stderr: {err}"
            )
            return None
    except:
        LOGGER.error(
            f"Error while combining thumbnails from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    finally:
        if not keep_screenshots:
            await rmtree(dirpath, ignore_errors=True)
    return output


class FFMpeg:

    def __init__(self, listener):
        self._listener = listener
        self._processed_bytes = 0
        self._last_processed_bytes = 0
        self._processed_time = 0
        self._last_processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._total_time = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._start_time = 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def speed_raw(self):
        return self._speed_raw

    @property
    def progress_raw(self):
        return self._progress_raw

    @property
    def eta_raw(self):
        return self._eta_raw

    def clear(self):
        self._start_time = time()
        self._processed_bytes = 0
        self._processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._last_processed_time = 0
        self._last_processed_bytes = 0

    async def _ffmpeg_progress(self):
        total_bytes = getattr(self._listener, "subsize", 0) or getattr(self._listener, "size", 0)
        while not (
            self._listener.subproc.returncode is not None
            or self._listener.is_cancelled
            or self._listener.subproc.stdout.at_eof()
        ):
            try:
                line = await wait_for(self._listener.subproc.stdout.readline(), 60)
            except:
                break
            if not line:
                break
            line = line.decode().strip()
            if not line:
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                value = value.strip()
                if value != "N/A":
                    if key == "total_size":
                        try:
                            self._processed_bytes = int(value) + self._last_processed_bytes
                            self._speed_raw = self._processed_bytes / max(0.001, (time() - self._start_time))
                        except:
                            pass
                    elif key == "speed":
                        try:
                            self._time_rate = max(0.1, float(value.rstrip("x")))
                        except:
                            pass
                    elif key == "out_time":
                        self._processed_time = (
                            time_to_seconds(value) + self._last_processed_time
                        )
                        try:
                            if self._total_time > 0:
                                self._progress_raw = (
                                    self._processed_time * 100
                                ) / self._total_time
                                self._eta_raw = (
                                    self._total_time - self._processed_time
                                ) / self._time_rate
                                if not self._processed_bytes and total_bytes > 0:
                                    self._processed_bytes = int((self._processed_time / self._total_time) * total_bytes)
                                self._speed_raw = self._processed_bytes / max(0.001, (time() - self._start_time))
                        except:
                            self._progress_raw = 0
                            self._eta_raw = 0

    async def ffmpeg_cmds(self, ffmpeg, f_path):
        self.clear()
        if isinstance(f_path, list):
            self._total_time = 0
            for f in f_path:
                self._total_time += (await get_media_info(f))[0]
            base_name = ospath.commonprefix(f_path)
            ext = f_path[0].rsplit(".", 1)[-1]
        else:
            self._total_time = (await get_media_info(f_path))[0]
            base_name, ext = ospath.splitext(f_path)
        dir, base_name = base_name.rsplit("/", 1)
        indices = [
            index
            for index, item in enumerate(ffmpeg)
            if (item.startswith("mltb") or item == "mltb") and item != "mltb.txt"
        ]
        outputs = []
        for index in indices:
            output_file = ffmpeg[index]
            if output_file != "mltb" and output_file.startswith("mltb"):
                bo, oext = ospath.splitext(output_file)
                if oext:
                    if isinstance(f_path, list) or ext != oext:
                        prefix = ""
                    else:
                        prefix = f"ffmpeg{index}." if bo == "mltb" else ""
                    ext = ""
                else:
                    prefix = ""
            else:
                prefix = f"ffmpeg{index}."
            output = f"{dir}/{prefix}{output_file.replace("mltb", base_name)}{ext}"
            outputs.append(output)
            ffmpeg[index] = output
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *ffmpeg, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return outputs
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while running ffmpeg cmd, mostly file requires different/specific arguments. Path: {f_path}"
            )
            for op in outputs:
                if await aiopath.exists(op):
                    await remove(op)
            return False

    async def convert_video(self, video_file, ext, retry=False):
        self.clear()
        self._total_time = (await get_media_info(video_file))[0]
        base_name = ospath.splitext(video_file)[0]
        output = f"{base_name}.{ext}"
        if retry:
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-threads",
                f"{threads}",
                output,
            ]
            if ext == "mp4":
                cmd[17:17] = ["-c:s", "mov_text"]
            elif ext == "mkv":
                cmd[17:17] = ["-c:s", "ass"]
            else:
                cmd[17:17] = ["-c:s", "copy"]
        else:
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                output,
            ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            if await aiopath.exists(output):
                await remove(output)
            if not retry:
                return await self.convert_video(video_file, ext, True)
            try:
                stderr = stderr.decode().strip()
            except:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting video, mostly file need specific codec. Path: {video_file}"
            )
        return False

    async def convert_audio(self, audio_file, ext):
        self.clear()
        self._total_time = (await get_media_info(audio_file))[0]
        base_name = ospath.splitext(audio_file)[0]
        output = f"{base_name}.{ext}"
        cmd = [
            "taskset",
            "-c",
            f"{cores}",
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            audio_file,
            "-threads",
            f"{threads}",
            output,
        ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting audio, mostly file need specific codec. Path: {audio_file}"
            )
            if await aiopath.exists(output):
                await remove(output)
        return False

    async def sample_video(self, video_file, sample_duration, part_duration):
        self.clear()
        self._total_time = sample_duration
        dir, name = video_file.rsplit("/", 1)
        output_file = f"{dir}/SAMPLE.{name}"
        segments = [(0, part_duration)]
        duration = (await get_media_info(video_file))[0]
        remaining_duration = duration - (part_duration * 2)
        parts = (sample_duration - (part_duration * 2)) // part_duration
        time_interval = remaining_duration // parts
        next_segment = time_interval
        for _ in range(parts):
            segments.append((next_segment, next_segment + part_duration))
            next_segment += time_interval
        segments.append((duration - part_duration, duration))

        filter_complex = ""
        for i, (start, end) in enumerate(segments):
            filter_complex += (
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]; "
            )
            filter_complex += (
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]; "
            )

        for i in range(len(segments)):
            filter_complex += f"[v{i}][a{i}]"

        filter_complex += f"concat=n={len(segments)}:v=1:a=1[vout][aout]"

        cmd = [
            "taskset",
            "-c",
            f"{cores}",
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            video_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-threads",
            f"{threads}",
            output_file,
        ]

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == -9:
            self._listener.is_cancelled = True
            return False
        elif code == 0:
            return output_file
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while creating sample video, mostly file is corrupted. Path: {video_file}"
            )
            if await aiopath.exists(output_file):
                await remove(output_file)
            return False

    async def split(self, f_path, file_, parts, split_size, out_dir=None):
        self.clear()
        multi_streams = True
        self._total_time = duration = (await get_media_info(f_path))[0]
        base_name, extension = ospath.splitext(file_)
        split_size -= 3000000
        start_time = 0
        i = 1
        while i <= parts or start_time < duration - 4:
            if out_dir:
                await aiomakedirs(out_dir, exist_ok=True)
                out_path = ospath.join(out_dir, f"{base_name}.part{i:03}{extension}")
            else:
                out_path = f_path.replace(file_, f"{base_name}.part{i:03}{extension}")
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-ss",
                str(start_time),
                "-i",
                f_path,
                "-fs",
                str(split_size),
                "-map",
                "0",
                "-map_chapters",
                "-1",
                "-async",
                "1",
                "-strict",
                "-2",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                out_path,
            ]
            if not multi_streams:
                del cmd[15]
                del cmd[15]
            if self._listener.is_cancelled:
                return False
            self._listener.subproc = await create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )
            await self._ffmpeg_progress()
            _, stderr = await self._listener.subproc.communicate()
            code = self._listener.subproc.returncode
            if self._listener.is_cancelled:
                return False
            if code == -9:
                self._listener.is_cancelled = True
                return False
            elif code != 0:
                try:
                    stderr = stderr.decode().strip()
                except:
                    stderr = "Unable to decode the error!"
                try:
                    await remove(out_path)
                except:
                    pass
                if multi_streams:
                    LOGGER.warning(
                        f"{stderr}. Retrying without map, -map 0 not working in all situations. Path: {f_path}"
                    )
                    multi_streams = False
                    continue
                else:
                    LOGGER.warning(
                        f"{stderr}. Unable to split this video, if it's size less than {self._listener.max_split_size} will be uploaded as it is. Path: {f_path}"
                    )
                return False
            out_size = await aiopath.getsize(out_path)
            if out_size > self._listener.max_split_size:
                split_size -= (out_size - self._listener.max_split_size) + 5000000
                LOGGER.warning(
                    f"Part size is {out_size}. Trying again with lower split size!. Path: {f_path}"
                )
                await remove(out_path)
                continue
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f"Something went wrong while splitting, mostly file is corrupted. Path: {f_path}"
                )
                break
            elif duration == lpd:
                LOGGER.warning(
                    f"This file has been splitted with default stream and audio, so you will only see one part with less size from original one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {f_path}"
                )
                break
            elif lpd <= 3:
                await remove(out_path)
                break
            self._last_processed_time += lpd
            self._last_processed_bytes += out_size
            start_time += lpd - 3
            i += 1
        return True
