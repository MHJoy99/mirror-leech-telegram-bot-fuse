import asyncio
import os
from os import path as ospath, walk
from aiofiles.os import path as aiopath

from bot import LOGGER, task_dict, task_dict_lock
from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.ext_utils.status_utils import get_readable_file_size
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import send_message, edit_message

# mid -> {files:[(rel, size, full)], selected:set(idx), mount:str, event:Event, picker_msg, done:bool, cancel:bool}
zip_pick_state = {}

PAGE_SIZE = 8

def _build_text(files, selected, page):
    total = len(files)
    sel_cnt = len(selected)
    total_size = sum(s for _, s, _ in files)
    sel_size = sum(files[i][1] for i in selected)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    txt = f"<b>Select files from ZIP</b>\n"
    txt += f"Selected: {sel_cnt}/{total} ({get_readable_file_size(sel_size)} / {get_readable_file_size(total_size)})\n"
    txt += f"Page {page+1}/{(total+PAGE_SIZE-1)//PAGE_SIZE}\n"
    txt += f"Tap to toggle. Done to continue (auto Done in 60s).\n"
    for idx in range(start, end):
        rel, size, _ = files[idx]
        mark = "[x]" if idx in selected else "[ ]"
        name = ospath.basename(rel) or rel
        # cut long name
        if len(name) > 38:
            name = name[:36] + ".."
        txt += f"\n{mark} {name} ({get_readable_file_size(size)})"
    if not files:
        txt += "\nNo files found."
    return txt

def _build_markup(mid, files, page, selected):
    buttons = ButtonMaker()
    total = len(files)
    pages = (total + PAGE_SIZE - 1)//PAGE_SIZE if total else 1
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    for idx in range(start, end):
        rel, size, _ = files[idx]
        mark = "✅" if idx in selected else "⬜"
        name = ospath.basename(rel) or rel
        if len(name) > 20:
            name = name[:19] + "…"
        label = f"{mark} {name} {get_readable_file_size(size)}"
        # callback <64B : zipsel MID t IDX PAGE
        buttons.data_button(label, f"zipsel {mid} t {idx} {page}")
    # nav row
    if pages > 1:
        if page > 0:
            buttons.data_button("◀ Prev", f"zipsel {mid} p {page-1}")
        if page < pages-1:
            buttons.data_button("Next ▶", f"zipsel {mid} p {page+1}")
    # control row
    buttons.data_button("Select All", f"zipsel {mid} all {page}")
    buttons.data_button("Deselect All", f"zipsel {mid} none {page}")
    buttons.data_button("✅ Done", f"zipsel {mid} done {page}")
    buttons.data_button("❌ Cancel", f"zipsel {mid} cancel {page}")
    return buttons.build_menu(1)

async def collect_zip_files(mount_path):
    files = []
    # walk mount/view
    for dirpath, _, filenames in await sync_to_async(walk, mount_path, topdown=True):
        # skip .mnt_ hidden inside?
        for fn in filenames:
            full = ospath.join(dirpath, fn)
            # avoid counting splits or same? just regular files
            rel = ospath.relpath(full, mount_path)
            try:
                # use os.stat for FUSE files; aiopath fails sometimes
                st = await sync_to_async(os.stat, full)
                size = int(st.st_size)
            except:
                try:
                    # fallback via aiopath
                    size = 0
                    if await aiopath.isfile(full):
                        # get_path_size for file is os.path.getsize
                        size = await sync_to_async(os.path.getsize, full)
                except:
                    size = 0
            if size == 0:
                # try list anyway but skip zero? still include
                pass
            files.append((rel, size, full))
    # natural sort by rel
    try:
        from natsort import natsorted
        files = natsorted(files, key=lambda x: x[0])
    except:
        files.sort(key=lambda x: x[0])
    return files

async def show_zip_picker(listener, mount_path):
    mid = listener.mid
    files = await collect_zip_files(mount_path)
    if not files:
        LOGGER.info(f"zip picker: no files in {mount_path}")
        return set()
    # default all selected
    selected = set(range(len(files)))
    ev = asyncio.Event()
    zip_pick_state[mid] = {"files": files, "selected": selected, "mount": mount_path, "event": ev, "done": False, "cancel": False, "picker_msg": None}
    text = _build_text(files, selected, 0)
    markup = _build_markup(mid, files, 0, selected)
    try:
        msg = await send_message(listener.message, text, markup)
        zip_pick_state[mid]["picker_msg"] = msg
    except Exception as e:
        LOGGER.error(f"zip picker send failed: {e}")
        return set(r for r,_,_ in files)
    # wait 60s
    try:
        await asyncio.wait_for(ev.wait(), timeout=60)
    except asyncio.TimeoutError:
        pass
    state = zip_pick_state.get(mid)
    if not state:
        return set(r for r,_,_ in files)
    if state.get("cancel"):
        listener.is_cancelled = True
        try:
            await edit_message(state["picker_msg"], "❌ Zip selection cancelled. Task will be cancelled.", None)
        except:
            pass
        del zip_pick_state[mid]
        return set()
    selected = state.get("selected", selected)
    sel_rels = set(files[i][0] for i in selected) if selected else set()
    try:
        await edit_message(state["picker_msg"], f"✅ Selected {len(selected)}/{len(files)} files. Continuing upload...", None)
    except:
        pass
    # keep state for potential inspection but remove event
    # do not delete immediately - let caller clean after use
    # store on listener for filtering
    listener._zip_selected_rels = sel_rels
    listener._zip_selected_indices = selected
    # clean dict after short delay
    async def _cleanup():
        await asyncio.sleep(300)
        zip_pick_state.pop(mid, None)
    asyncio.create_task(_cleanup())
    LOGGER.info(f"zip picker done mid={mid} selected={len(selected)}/{len(files)}")
    return sel_rels

async def zip_selector_callback(client, callback_query):
    data = callback_query.data or ""
    # format: "zipsel MID action [args]"
    parts = data.split()
    if len(parts) < 3:
        await callback_query.answer("Invalid")
        return
    try:
        mid = int(parts[1])
    except:
        await callback_query.answer("Invalid id")
        return
    action = parts[2]
    state = zip_pick_state.get(mid)
    if not state:
        await callback_query.answer("Selection expired (timeout or done)")
        return
    # auth: only owner/SUDO or task owner can act
    try:
        from bot import user_data
        from bot.core.config_manager import Config
        task = None
        async with task_dict_lock:
            task = task_dict.get(mid)
        allowed = False
        uid = callback_query.from_user.id if callback_query.from_user else 0
        if uid == Config.OWNER_ID:
            allowed = True
        elif task and hasattr(task, "listener") and task.listener.user_id == uid:
            allowed = True
        elif uid in user_data and user_data[uid].get("SUDO"):
            allowed = True
        elif task and task.listener.user_id == uid:
            allowed = True
        if not allowed and task is None:
            # if task not in dict yet (early picker before task_dict entry?), allow any authorized who triggered?
            allowed = True
        if not allowed:
            await callback_query.answer("Not your task!", show_alert=True)
            return
    except Exception as e:
        LOGGER.error(f"zip picker auth error: {e}")

    files = state["files"]
    selected = state["selected"]
    # page is last part for some actions
    cur_page = 0
    try:
        # last token often is page
        if parts[-1].isdigit():
            # for t action page is parts[4], for p it's parts[3], for all/none/done/cancel it's page
            if action == "t" and len(parts) >= 5:
                cur_page = int(parts[4])
            elif action == "p":
                cur_page = int(parts[3])
            elif action in ("all","none","done","cancel"):
                cur_page = int(parts[3]) if len(parts)>=4 and parts[3].isdigit() else 0
    except:
        cur_page = 0

    if action == "t":
        try:
            idx = int(parts[3])
            if idx in selected:
                selected.remove(idx)
            else:
                selected.add(idx)
            await callback_query.answer(f"{'Selected' if idx in selected else 'Deselected'} {ospath.basename(files[idx][0])[:30]}")
        except Exception as e:
            await callback_query.answer(str(e))
    elif action == "p":
        try:
            cur_page = int(parts[3])
            await callback_query.answer()
        except:
            await callback_query.answer()
    elif action == "all":
        selected.update(range(len(files)))
        await callback_query.answer("All selected")
    elif action == "none":
        selected.clear()
        await callback_query.answer("All deselected")
    elif action == "done":
        if not selected:
            await callback_query.answer("Select at least one file!", show_alert=True)
            return
        state["done"] = True
        state["event"].set()
        await callback_query.answer("Continuing...")
        return
    elif action == "cancel":
        state["cancel"] = True
        state["event"].set()
        await callback_query.answer("Cancelled")
        return
    else:
        await callback_query.answer("Unknown")
        return

    # re-render
    # clamp page
    pages = (len(files)+PAGE_SIZE-1)//PAGE_SIZE if files else 1
    if cur_page >= pages:
        cur_page = pages-1
    if cur_page < 0:
        cur_page = 0
    text = _build_text(files, selected, cur_page)
    markup = _build_markup(mid, files, cur_page, selected)
    try:
        await edit_message(state["picker_msg"], text, markup)
    except Exception as e:
        LOGGER.error(f"zip picker edit failed: {e}")
    # also answer if not already
    try:
        if action not in ("t",):
            await callback_query.answer()
    except:
        pass
