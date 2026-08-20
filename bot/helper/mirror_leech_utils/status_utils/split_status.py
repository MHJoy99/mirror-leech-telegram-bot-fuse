from time import time
import os

from .... import LOGGER
from ...ext_utils.status_utils import (
    get_readable_file_size,
    MirrorStatus,
    get_readable_time,
)


class SplitStatus:
    def __init__(self, listener, f_path, total_size, gid):
        self.listener = listener
        self._f_path = f_path
        self._total_size = total_size
        self._gid = gid
        self._start_time = time()
        self.tool = "split"

    def _get_processed_bytes(self):
        base_dir = os.path.dirname(self._f_path)
        base_name = os.path.basename(self._f_path)
        total = 0
        dirs_to_check = [base_dir]
        if hasattr(self.listener, 'dir') and self.listener.dir:
            dirs_to_check.append(self.listener.dir)
            if hasattr(self.listener, 'name') and self.listener.name:
                dirs_to_check.append(os.path.join(self.listener.dir, self.listener.name))
        try:
            seen_files = set()
            for d in dirs_to_check:
                if os.path.exists(d):
                    for root, _, files in os.walk(d):
                        for f in files:
                            if f.startswith(base_name + ".") and f not in seen_files:
                                seen_files.add(f)
                                p = os.path.join(root, f)
                                if os.path.isfile(p) and not os.path.islink(p):
                                    total += os.path.getsize(p)
        except:
            pass
        return min(total, self._total_size)

    def processed_bytes(self):
        return get_readable_file_size(self._get_processed_bytes())

    def speed(self):
        elapsed = time() - self._start_time
        if elapsed <= 0:
            return "0B/s"
        spd = self._get_processed_bytes() / elapsed
        return f"{get_readable_file_size(spd)}/s"

    def progress(self):
        if self._total_size == 0:
            return "0%"
        pct = (self._get_processed_bytes() / self._total_size) * 100
        return f"{round(pct, 2)}%"

    def eta(self):
        elapsed = time() - self._start_time
        proc = self._get_processed_bytes()
        if proc == 0 or elapsed <= 0:
            return "-"
        spd = proc / elapsed
        rem = self._total_size - proc
        if rem <= 0:
            return "0s"
        return get_readable_time(rem / spd)

    def gid(self):
        return self._gid

    def name(self):
        return self.listener.name

    def size(self):
        return get_readable_file_size(self.listener.size)

    def status(self):
        return MirrorStatus.STATUS_SPLIT

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(f"Cancelling Split: {self.listener.name}")
        self.listener.is_cancelled = True
        if self.listener.subproc is not None:
            try:
                self.listener.subproc.kill()
            except:
                pass
        await self.listener.on_upload_error("Split stopped by user!")
