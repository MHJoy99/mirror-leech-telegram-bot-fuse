import re

# 1. Update bot/helper/ext_utils/files_utils.py
with open("bot/helper/ext_utils/files_utils.py", "r") as f:
    content = f.read()

# Fix clean_download
clean_new = """async def clean_download(opath):
    if await aiopath.exists(opath):
        LOGGER.info(f"Cleaning Download: {opath}")
        try:
            from asyncio import create_subprocess_exec
            from asyncio.subprocess import PIPE
            await create_subprocess_exec("fusermount", "-uz", opath, stdout=PIPE, stderr=PIPE)
        except:
            pass
        try:
            await aiormtree(opath, ignore_errors=True)"""

content = re.sub(r'async def clean_download\(opath\):\n\s+if await aiopath\.exists\(opath\):\n\s+LOGGER\.info\(f"Cleaning Download: \{opath\}"\)\n\s+try:\n\s+await aiormtree\(opath, ignore_errors=True\)', clean_new, content)

# Fix extract cmd
extract_old = """    async def extract(self, f_path, t_path, pswd):
        cmd = [
            "7z",
            "x",
            f"-p{pswd}",
            f_path,
            f"-o{t_path}",
            "-aot",
            "-xr!@PaxHeader",
            "-bsp1",
            "-bse1",
            "-bb3",
        ]
        if not pswd:
            del cmd[2]"""

extract_new = """    async def extract(self, f_path, t_path, pswd):
        await aiomakedirs(t_path, exist_ok=True)
        cmd = [
            "archivemount",
            f_path,
            t_path
        ]"""

content = content.replace(extract_old, extract_new)

with open("bot/helper/ext_utils/files_utils.py", "w") as f:
    f.write(content)


# 2. Update bot/helper/common.py
with open("bot/helper/common.py", "r") as f:
    content = f.read()

common_old = """                    self.proceed_count += 1
                    f_path = ospath.join(dirpath, file_)
                    t_path = get_base_name(f_path) if self.is_file else dirpath
                    if not self.is_file:
                        self.subname = file_
                    code = await sevenz.extract(f_path, t_path, pswd)
            if self.is_cancelled:
                return code
            if code == 0:
                for file_ in files:
                    if is_archive_split(file_) or is_archive(file_):
                        del_path = ospath.join(dirpath, file_)
                        try:
                            await remove(del_path)
                        except:
                            pass"""

common_new = """                    self.proceed_count += 1
                    f_path = ospath.join(dirpath, file_)
                    t_path = get_base_name(f_path) if self.is_file else dirpath
                    if not self.is_file:
                        self.subname = file_
                    
                    from shutil import move
                    import os
                    hidden_source_dir = f"{self.dir}_source_archives"
                    os.makedirs(hidden_source_dir, exist_ok=True)
                    hidden_f_path = os.path.join(hidden_source_dir, file_)
                    move(f_path, hidden_f_path)
                    
                    code = await sevenz.extract(hidden_f_path, t_path, pswd)
            if self.is_cancelled:
                return code
            if code == 0:
                for file_ in files:
                    if is_archive_split(file_) or is_archive(file_):
                        pass"""

content = content.replace(common_old, common_new)

with open("bot/helper/common.py", "w") as f:
    f.write(content)

# 3. Update bot/helper/listeners/task_listener.py
with open("bot/helper/listeners/task_listener.py", "r") as f:
    content = f.read()

content = content.replace('await clean_download(self.dir)', 'await clean_download(self.dir)\n        await clean_download(f"{self.dir}_source_archives")')

with open("bot/helper/listeners/task_listener.py", "w") as f:
    f.write(content)

print("Patching complete!")
