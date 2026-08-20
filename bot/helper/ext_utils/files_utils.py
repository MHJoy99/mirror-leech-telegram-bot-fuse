from aioshutil import rmtree as aiormtree, move
from asyncio import create_subprocess_exec, wait_for
from asyncio.subprocess import PIPE
from magic import Magic
from os import walk, path as ospath, readlink
import os
import asyncio
from re import split as re_split, I, search as re_search, escape
from aiofiles.os import (
    remove,
    path as aiopath,
    listdir,
    rmdir,
    readlink as aioreadlink,
    symlink,
    makedirs as aiomakedirs,
)

from ... import LOGGER, DOWNLOAD_DIR
from ...core.torrent_manager import TorrentManager
from .bot_utils import sync_to_async, cmd_exec
from .exceptions import NotSupportedExtractionArchive

ARCH_EXT = [
    ".tar.bz2",
    ".tar.gz",
    ".bz2",
    ".gz",
    ".tar.xz",
    ".tar",
    ".tbz2",
    ".tgz",
    ".lzma2",
    ".zip",
    ".7z",
    ".z",
    ".rar",
    ".iso",
    ".wim",
    ".cab",
    ".apm",
    ".arj",
    ".chm",
    ".cpio",
    ".cramfs",
    ".deb",
    ".dmg",
    ".fat",
    ".hfs",
    ".lzh",
    ".lzma",
    ".mbr",
    ".msi",
    ".mslz",
    ".nsis",
    ".ntfs",
    ".rpm",
    ".squashfs",
    ".udf",
    ".vhd",
    ".xar",
    ".zst",
    ".zstd",
    ".cbz",
    ".apfs",
    ".ar",
    ".qcow",
    ".macho",
    ".exe",
    ".dll",
    ".sys",
    ".pmd",
    ".swf",
    ".swfc",
    ".simg",
    ".vdi",
    ".vhdx",
    ".vmdk",
    ".gzip",
    ".lzma86",
    ".sha256",
    ".sha512",
    ".sha224",
    ".sha384",
    ".sha1",
    ".md5",
    ".crc32",
    ".crc64",
]


FIRST_SPLIT_REGEX = (
    r"\.part0*1\.rar$|\.7z\.0*1$|\.zip\.0*1$|^(?!.*\.part\d+\.rar$).*\.rar$"
)

SPLIT_REGEX = r"\.r\d+$|\.7z\.\d+$|\.z\d+$|\.zip\.\d+$|\.part\d+\.rar$"


def is_first_archive_split(file):
    return bool(re_search(FIRST_SPLIT_REGEX, file.lower(), I))


def is_archive(file):
    return file.strip().lower().endswith(tuple(ARCH_EXT))


def is_archive_split(file):
    return bool(re_search(SPLIT_REGEX, file.lower(), I))


async def clean_target(opath):
    if await aiopath.exists(opath):
        LOGGER.info(f"Cleaning Target: {opath}")
        try:
            if await aiopath.isdir(opath):
                await aiormtree(opath, ignore_errors=True)
            else:
                await remove(opath)
        except Exception as e:
            LOGGER.error(str(e))


async def clean_download(opath):
    if await aiopath.exists(opath):
        LOGGER.info(f"Cleaning Download: {opath}")
        try:
            norm_target = ospath.abspath(opath).rstrip("/")
            mount_points = []
            try:
                with open("/proc/mounts", "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            mnt = ospath.abspath(parts[1]).rstrip("/")
                            if mnt == norm_target or mnt.startswith(f"{norm_target}/"):
                                mount_points.append(mnt)
            except Exception as me:
                LOGGER.warning(f"Failed to read /proc/mounts: {me}")
            from asyncio import create_subprocess_exec
            from asyncio.subprocess import PIPE
            for mnt in sorted(set(mount_points), key=len, reverse=True):
                await (await create_subprocess_exec("fusermount", "-uz", mnt, stdout=PIPE, stderr=PIPE)).wait()
        except Exception as e:
            LOGGER.error(f"Error unmounting FUSE paths for {opath}: {e}")
        try:
            await aiormtree(opath, ignore_errors=True)
        except Exception as e:
            LOGGER.error(str(e))


async def clean_all():
    await TorrentManager.remove_all()
    LOGGER.info("Cleaning Download Directory")
    await (await create_subprocess_exec("rm", "-rf", DOWNLOAD_DIR)).wait()
    await aiomakedirs(DOWNLOAD_DIR, exist_ok=True)


async def clean_unwanted(opath):
    LOGGER.info(f"Cleaning unwanted files/folders: {opath}")
    for dirpath, _, files in await sync_to_async(walk, opath, topdown=False):
        for filee in files:
            f_path = ospath.join(dirpath, filee)
            if filee.strip().endswith(".parts") and filee.startswith("."):
                await remove(f_path)
        if dirpath.strip().endswith(".unwanted"):
            await aiormtree(dirpath, ignore_errors=True)
    for dirpath, _, files in await sync_to_async(walk, opath, topdown=False):
        if not await listdir(dirpath):
            await rmdir(dirpath)


async def get_path_size(opath):
    total_size = 0
    if await aiopath.isfile(opath):
        if await aiopath.islink(opath):
            opath = await aioreadlink(opath)
        return await aiopath.getsize(opath)
    # If opath is inside a FUSE mount (e.g. .mnt_...), count its interior; otherwise skip hidden mounts when walking a parent
    opath_norm = ospath.abspath(opath).rstrip("/")
    is_mount = ".mnt_" in opath_norm
    for root, _, files in await sync_to_async(walk, opath):
        if not is_mount and ".mnt_" in root:
            continue
        for f in files:
            abs_path = ospath.join(root, f)
            if not is_mount and ".mnt_" in abs_path:
                continue
            if await aiopath.islink(abs_path):
                abs_path = await aioreadlink(abs_path)
            try:
                total_size += await aiopath.getsize(abs_path)
            except:
                pass
    return total_size


async def count_files_and_folders(opath):
    total_files = 0
    total_folders = 0
    for _, dirs, files in await sync_to_async(walk, opath):
        total_files += len(files)
        total_folders += len(dirs)
    return total_folders, total_files


def get_base_name(orig_path):
    extension = next(
        (ext for ext in ARCH_EXT if orig_path.strip().lower().endswith(ext)), ""
    )
    if extension != "":
        return re_split(f"{extension}$", orig_path, maxsplit=1, flags=I)[0]
    else:
        raise NotSupportedExtractionArchive("File format not supported for extraction")


async def create_recursive_symlink(source, destination):
    if ospath.isdir(source):
        await aiomakedirs(destination, exist_ok=True)
        for item in await listdir(source):
            item_source = ospath.join(source, item)
            item_dest = ospath.join(destination, item)
            await create_recursive_symlink(item_source, item_dest)
    elif ospath.isfile(source):
        try:
            await symlink(source, destination)
        except FileExistsError:
            LOGGER.error(f"Shortcut already exists: {destination}")
        except Exception as e:
            LOGGER.error(f"Error creating shortcut for {source}: {e}")


def get_mime_type(file_path):
    if ospath.islink(file_path):
        file_path = readlink(file_path)
    mime = Magic(mime=True)
    mime_type = mime.from_file(file_path)
    mime_type = mime_type or "text/plain"
    return mime_type


async def remove_excluded_files(fpath, ee):
    for root, _, files in await sync_to_async(walk, fpath):
        if root.strip().endswith("/yt-dlp-thumb"):
            continue
        for f in files:
            if f.strip().lower().endswith(tuple(ee)):
                await remove(ospath.join(root, f))


async def remove_non_included_files(fpath, ie):
    for root, _, files in await sync_to_async(walk, fpath):
        if root.strip().endswith("/yt-dlp-thumb"):
            continue
        for f in files:
            if f.strip().lower().endswith(tuple(ie)):
                continue
            await remove(ospath.join(root, f))


async def move_and_merge(source, destination, mid):
    if not await aiopath.exists(destination):
        await aiomakedirs(destination, exist_ok=True)
    for item in await listdir(source):
        item = item.strip()
        src_path = f"{source}/{item}"
        dest_path = f"{destination}/{item}"
        if await aiopath.isdir(src_path):
            if await aiopath.exists(dest_path):
                await move_and_merge(src_path, dest_path, mid)
            else:
                await move(src_path, dest_path)
        else:
            if item.endswith((".aria2", ".!qB")):
                continue
            if await aiopath.exists(dest_path):
                dest_path = f"{destination}/{mid}-{item}"
            await move(src_path, dest_path)


async def join_files(opath):
    files = await listdir(opath)
    results = []
    exists = False
    for file_ in files:
        if re_search(r"\.0+2$", file_) and await sync_to_async(
            get_mime_type, f"{opath}/{file_}"
        ) not in ["application/x-7z-compressed", "application/zip"]:
            exists = True
            final_name = file_.rsplit(".", 1)[0]
            fpath = f"{opath}/{final_name}"
            cmd = f'cat "{fpath}."* > "{fpath}"'
            _, stderr, code = await cmd_exec(cmd, True)
            if code != 0:
                LOGGER.error(f"Failed to join {final_name}, stderr: {stderr}")
                if await aiopath.isfile(fpath):
                    await remove(fpath)
            else:
                results.append(final_name)

    if not exists:
        LOGGER.warning("No files to join!")
    elif results:
        LOGGER.info("Join Completed!")
        for res in results:
            for file_ in files:
                if re_search(rf"{escape(res)}\.0[0-9]+$", file_):
                    await remove(f"{opath}/{file_}")


async def split_file(f_path, split_size, listener, out_dir=None):
    if out_dir:
        await aiomakedirs(out_dir, exist_ok=True)
        out_path = ospath.join(out_dir, f"{ospath.basename(f_path)}.")
    else:
        out_path = f"{f_path}."
    if listener.is_cancelled:
        return False
    listener.subproc = await create_subprocess_exec(
        "split",
        "--numeric-suffixes=1",
        "--suffix-length=3",
        f"--bytes={split_size}",
        f_path,
        out_path,
        stderr=PIPE,
    )
    _, stderr = await listener.subproc.communicate()
    code = listener.subproc.returncode
    if listener.is_cancelled:
        return False
    if code == -9:
        listener.is_cancelled = True
        return False
    elif code != 0:
        try:
            stderr = stderr.decode().strip()
        except:
            stderr = "Unable to decode the error!"
        LOGGER.error(f"{stderr}. Split Document: {f_path}")
        return False
    return True


class SevenZ:
    def __init__(self, listener):
        self._listener = listener
        self._processed_bytes = 0
        self._percentage = "0%"

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def progress(self):
        return self._percentage

    async def _sevenz_progress(self):
        pattern = (
            r"(\d+)\s+bytes|Total Physical Size\s*=\s*(\d+)|Physical Size\s*=\s*(\d+)"
        )
        while not (
            self._listener.subproc.returncode is not None
            or self._listener.is_cancelled
            or self._listener.subproc.stdout.at_eof()
        ):
            try:
                line = await wait_for(self._listener.subproc.stdout.readline(), 2)
            except:
                break
            line = line.decode().strip()
            if "%" in line:
                perc = line.split("%", 1)[0]
                if perc.isdigit():
                    self._percentage = f"{perc}%"
                    self._processed_bytes = (int(perc) / 100) * self._listener.subsize
                else:
                    self._percentage = "0%"
                continue
            if match := re_search(pattern, line):
                self._listener.subsize = int(match[1] or match[2] or match[3])
        s = b""
        while not (
            self._listener.is_cancelled
            or self._listener.subproc.returncode is not None
            or self._listener.subproc.stdout.at_eof()
        ):
            try:
                char = await wait_for(self._listener.subproc.stdout.read(1), 60)
            except:
                break
            if not char:
                break
            s += char
            if char == b"%":
                try:
                    self._percentage = s.decode().rsplit(" ", 1)[-1].strip()
                    self._processed_bytes = (
                        int(self._percentage.strip("%")) / 100
                    ) * self._listener.subsize
                except:
                    self._processed_bytes = 0
                    self._percentage = "0%"
                s = b""

        self._processed_bytes = 0
        self._percentage = "0%"

    async def extract(self, f_path, t_path, pswd):
        # mount inside parent of f_path so cleaning parent dir unmounts; keep archive file alive while mounted
        base = os.path.basename(f_path).replace('.', '_')[:40]
        parent = ospath.dirname(f_path) if ospath.isfile(f_path) or '.' in os.path.basename(f_path) else t_path
        if not parent or parent == "":
            parent = t_path
        # ensure parent exists and is dir
        try:
            await aiomakedirs(parent, exist_ok=True)
        except:
            parent = t_path
            await aiomakedirs(parent, exist_ok=True)
        mount_point = ospath.join(parent, f".mnt_{base}_{id(self)%100000}")
        await aiomakedirs(mount_point, exist_ok=True)
        archivemount_opts = "readonly,nosave"
        if pswd:
            LOGGER.warning(f"Password archive {f_path} - archivemount does not support password, falling back to 7z extract")
            cmd = [
                "7z", "x", f"-p{pswd}", f_path, f"-o{mount_point}",
                "-aot", "-xr!@PaxHeader", "-bsp1", "-bse1", "-bb3",
            ]
            if not pswd:
                del cmd[2]
            if self._listener.is_cancelled:
                return False
            self._listener.subproc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
            await self._sevenz_progress()
            _, stderr = await self._listener.subproc.communicate()
            code = self._listener.subproc.returncode
            if code == 0:
                try:
                    await remove(f_path)
                except Exception:
                    pass
                return mount_point
            else:
                try:
                    stderr = stderr.decode().strip()
                except:
                    stderr = "Unable to decode error"
                LOGGER.error(f"{stderr}. Unable to extract archive!. Path: {f_path}")
                try:
                    await aiormtree(mount_point, ignore_errors=True)
                except:
                    pass
                return False
        cmd = ["archivemount", "-o", archivemount_opts, f_path, mount_point]
        if self._listener.is_cancelled:
            return False
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        self._listener.subproc = proc
        # archivemount is a FUSE daemon: it stays alive serving the mount, so proc never exits.
        # Don't await communicate() forever - poll /proc/mounts instead.
        mounted = False
        err = ""
        for _ in range(60):
            await asyncio.sleep(0.5)
            if self._listener.is_cancelled:
                try:
                    proc.terminate()
                    await asyncio.sleep(0.3)
                    try:
                        proc.kill()
                    except:
                        pass
                except:
                    pass
                try:
                    await (await create_subprocess_exec("fusermount", "-uz", mount_point, stdout=PIPE, stderr=PIPE)).wait()
                except:
                    pass
                return False

            # Check if mount point is now active in /proc/mounts (handle \040 space escaping)
            try:
                esc = mount_point.replace(" ", "\\040")
                with open("/proc/mounts", "r") as mf:
                    for line in mf:
                        if mount_point in line or esc in line:
                            mounted = True
                            break
                    if mounted:
                        break
            except:
                pass
            # Also succeed if mount point is accessible (covers mounts missed in /proc/mounts parsing)
            if not mounted:
                try:
                    import os as _os
                    if _os.path.ismount(mount_point) or _os.path.isdir(mount_point) and len(_os.listdir(mount_point)) > 0:
                        # do a quick access test
                        _ = _os.listdir(mount_point)
                        mounted = True
                        break
                except:
                    pass

            # If parent process exited with non-zero, it failed. If 0, it forked the daemon.
            if proc.returncode is not None:
                if proc.returncode != 0:
                    try:
                        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=1)
                        err = stderr.decode().strip() if stderr else ""
                    except:
                        pass
                    LOGGER.error(f"archivemount exited with error ({proc.returncode}) {err} Path: {f_path}")
                    try:
                        await aiormtree(mount_point, ignore_errors=True)
                    except:
                        pass
                    return False
        if not mounted:
            # timeout - capture code if exited
            code = proc.returncode
            if code is not None:
                try:
                    _, stderr = await proc.communicate()
                    err = stderr.decode().strip() if stderr else ""
                except:
                    pass
                LOGGER.error(f"archivemount failed ({code}) {err}. Path: {f_path}")
            else:
                LOGGER.error(f"archivemount mount not verified after 30s: {mount_point} for {f_path}")
                try:
                    proc.terminate()
                    await asyncio.sleep(0.5)
                    try:
                        proc.kill()
                    except:
                        pass
                except:
                    pass
                try:
                    await (await create_subprocess_exec("fusermount", "-uz", mount_point, stdout=PIPE, stderr=PIPE)).wait()
                except:
                    pass
            try:
                await aiormtree(mount_point, ignore_errors=True)
            except:
                pass
            return False
        LOGGER.info(f"archivemount mounted: {mount_point} for {f_path}")
        return mount_point

    async def zip(self, dl_path, up_path, pswd):
        size = await get_path_size(dl_path)
        if self._listener.equal_splits:
            parts = -(-size // self._listener.split_size)
            split_size = (size // parts) + (size % parts)
        else:
            split_size = self._listener.split_size
        cmd = [
            "7z",
            f"-v{split_size}b",
            "a",
            "-mx=0",
            f"-p{pswd}",
            up_path,
            dl_path,
            "-bsp1",
            "-bse1",
            "-bb3",
        ]
        if self._listener.is_leech and int(size) > self._listener.split_size:
            if not pswd:
                del cmd[4]
            LOGGER.info(f"Zip: orig_path: {dl_path}, zip_path: {up_path}.0*")
        else:
            del cmd[1]
            if not pswd:
                del cmd[3]
            LOGGER.info(f"Zip: orig_path: {dl_path}, zip_path: {up_path}")
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._sevenz_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == -9:
            self._listener.is_cancelled = True
            return False
        elif code == 0:
            await clean_target(dl_path)
            return up_path
        else:
            if await aiopath.exists(up_path):
                await remove(up_path)
            try:
                stderr = stderr.decode().strip()
            except:
                stderr = "Unable to decode the error!"
            LOGGER.error(f"{stderr}. Unable to zip this path: {dl_path}")
            return dl_path
