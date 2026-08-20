import asyncio
import functools
import inspect
import io
import logging
import math
import os
from hashlib import md5
from importlib.util import find_spec
from pathlib import PurePath
from typing import BinaryIO, Callable, Union

from pyrogram import Client, StopTransmission, raw

from .. import LOGGER
from .config_manager import Config

log = logging.getLogger(__name__)
_PATCH_ATTR = "_mltb_save_file_patched"
_DEFAULT_BIG_FILE_WORKERS = 4
_MAX_BIG_FILE_WORKERS = 16


def _get_big_file_workers():
    workers = int(getattr(Config, "TG_UPLOAD_WORKERS", _DEFAULT_BIG_FILE_WORKERS) or 0)
    return max(1, min(workers, _MAX_BIG_FILE_WORKERS))


async def _patched_save_file(
    self: "Client",
    path: Union[str, BinaryIO],
    file_id: int = None,
    file_part: int = 0,
    progress: Callable = None,
    progress_args: tuple = (),
):
    async with self.save_file_semaphore:
        if path is None:
            return None

        queue = None

        async def worker(session):
            while True:
                data = await queue.get()

                if data is None:
                    return

                try:
                    await session.invoke(data)
                except Exception as e:
                    log.exception(e)

        part_size = 512 * 1024

        if isinstance(path, (str, PurePath)):
            fp = open(path, "rb")
        elif isinstance(path, io.IOBase):
            fp = path
        else:
            raise ValueError(
                "Invalid file. Expected a file path as string or a binary (not text) file pointer"
            )

        file_name = getattr(fp, "name", "file.jpg")

        fp.seek(0, os.SEEK_END)
        file_size = fp.tell()
        fp.seek(0)

        if file_size == 0:
            raise ValueError("File size equals to 0 B")

        if self.me and self.me.is_premium:
            file_size_limit_mib = 4000
        else:
            file_size_limit_mib = 2000

        if file_size > file_size_limit_mib * 1024 * 1024:
            raise ValueError(f"Can't upload files bigger than {file_size_limit_mib} MiB")

        file_total_parts = int(math.ceil(file_size / part_size))
        is_big = file_size > 10 * 1024 * 1024
        workers_count = _get_big_file_workers() if is_big else 1
        is_missing_part = file_id is not None
        file_id = file_id or self.rnd_id()
        md5_sum = md5() if not is_big and not is_missing_part else None
        dc_id = await self.storage.dc_id()

        session = await self.get_session(dc_id, is_media=True)
        queue = asyncio.Queue(max(1, workers_count))
        workers = [self.loop.create_task(worker(session)) for _ in range(workers_count)]

        try:
            fp.seek(part_size * file_part)

            while True:
                chunk = fp.read(part_size)

                if not chunk:
                    if not is_big and not is_missing_part:
                        md5_sum = "".join(
                            [hex(i)[2:].zfill(2) for i in md5_sum.digest()]
                        )
                    break

                if is_big:
                    rpc = raw.functions.upload.SaveBigFilePart(
                        file_id=file_id,
                        file_part=file_part,
                        file_total_parts=file_total_parts,
                        bytes=chunk,
                    )
                else:
                    rpc = raw.functions.upload.SaveFilePart(
                        file_id=file_id,
                        file_part=file_part,
                        bytes=chunk,
                    )

                await queue.put(rpc)

                if is_missing_part:
                    return

                if not is_big and not is_missing_part:
                    md5_sum.update(chunk)

                file_part += 1

                if progress:
                    func = functools.partial(
                        progress,
                        min(file_part * part_size, file_size),
                        file_size,
                        *progress_args,
                    )

                    if inspect.iscoroutinefunction(progress):
                        await func()
                    else:
                        await self.loop.run_in_executor(self.executor, func)
        except StopTransmission:
            raise
        except Exception as e:
            log.exception(e)
        else:
            if is_big:
                return raw.types.InputFileBig(
                    id=file_id,
                    parts=file_total_parts,
                    name=file_name,
                )
            return raw.types.InputFile(
                id=file_id,
                parts=file_total_parts,
                name=file_name,
                md5_checksum=md5_sum,
            )
        finally:
            for _ in workers:
                await queue.put(None)

            await asyncio.gather(*workers)

            if isinstance(path, (str, PurePath)):
                fp.close()


def apply_telegram_speedups():
    if find_spec("tgcrypto") is None:
        LOGGER.warning(
            "TgCrypto is not installed. Telegram uploads and downloads will be much slower until it is available in the runtime environment."
        )

    if getattr(Client, _PATCH_ATTR, False):
        return

    Client.save_file = _patched_save_file
    setattr(Client, _PATCH_ATTR, True)

    workers = _get_big_file_workers()
    LOGGER.info(
        f"Telegram big-file uploads will use up to {workers} parallel part workers per file."
    )
