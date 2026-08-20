from asyncio import Lock, sleep
from os import path as ospath

from aiofiles.os import path as aiopath
from pytdbot import Client, ClientManager
from pytdbot.types import AutoDownloadSettings, NetworkTypeOther

from .. import LOGGER
from .config_manager import Config


class TdlibManager:
    _lock = Lock()
    _pool_lock = Lock()
    user = None
    user_pool = []
    client_manager = None
    IS_AVAILABLE = False
    IS_PREMIUM_USER = False
    ERROR = ""
    _user_pool_index = 0

    @classmethod
    def _db_path(cls):
        db_path = str(getattr(Config, "TDLIB_USER_DB_PATH", "tdlib_user") or "tdlib_user")
        if not db_path.startswith("/"):
            db_path = ospath.join("/app", db_path)
        return db_path

    @classmethod
    def _db_paths(cls):
        raw_paths = getattr(Config, "TDLIB_USER_DB_PATHS", []) or []
        paths = []
        for item in raw_paths:
            if not item:
                continue
            db_path = str(item).strip()
            if not db_path:
                continue
            if not db_path.startswith("/"):
                db_path = ospath.join("/app", db_path)
            paths.append(db_path)
        if paths:
            return paths
        return [cls._db_path()]

    @classmethod
    def _patch_tdjson_binding(cls):
        try:
            import tdjson as tdjson_binding
        except ImportError:
            return
        if getattr(tdjson_binding, "_mltb_patched", False):
            return

        orig_send = tdjson_binding.td_send
        orig_receive = tdjson_binding.td_receive
        orig_execute = tdjson_binding.td_execute

        def wrapped_send(client_id, request):
            try:
                return orig_send(client_id, request)
            except TypeError:
                if isinstance(request, str):
                    return orig_send(client_id, request.encode())
                if isinstance(request, bytes):
                    return orig_send(client_id, request.decode())
                raise

        def wrapped_receive(timeout):
            res = orig_receive(timeout)
            if isinstance(res, bytes):
                return res.decode()
            return res

        def wrapped_execute(request):
            try:
                res = orig_execute(request)
            except TypeError:
                if isinstance(request, str):
                    res = orig_execute(request.encode())
                elif isinstance(request, bytes):
                    res = orig_execute(request.decode())
                else:
                    raise
            if isinstance(res, bytes):
                return res.decode()
            return res

        tdjson_binding.td_send = wrapped_send
        tdjson_binding.td_receive = wrapped_receive
        tdjson_binding.td_execute = wrapped_execute
        tdjson_binding._mltb_patched = True

    @classmethod
    def enabled(cls):
        return bool(Config.TDLIB_USER_UPLOAD)

    @classmethod
    def has_user_pool(cls):
        return len(cls.user_pool) > 1

    @classmethod
    async def get_upload_client(cls):
        if cls.user_pool:
            if len(cls.user_pool) == 1:
                client = cls.user_pool[0]
                LOGGER.info(
                    "TDLib upload client selected: "
                    f"db={getattr(client, '_mltb_db_path', 'unknown')} | "
                    f"index={getattr(client, '_mltb_db_index', 1)}"
                )
                return client
            async with cls._pool_lock:
                client = cls.user_pool[cls._user_pool_index % len(cls.user_pool)]
                cls._user_pool_index = (cls._user_pool_index + 1) % len(cls.user_pool)
                LOGGER.info(
                    "TDLib upload client selected: "
                    f"db={getattr(client, '_mltb_db_path', 'unknown')} | "
                    f"index={getattr(client, '_mltb_db_index', cls._user_pool_index)}"
                )
                return client
        client = cls.user
        LOGGER.info(
            "TDLib upload client selected: "
            f"db={getattr(client, '_mltb_db_path', 'unknown') if client else 'unknown'} | "
            f"index={getattr(client, '_mltb_db_index', 1) if client else 1}"
        )
        return client

    @classmethod
    async def start_user(cls):
        cls.IS_AVAILABLE = False
        cls.IS_PREMIUM_USER = False
        cls.ERROR = ""
        cls.user = None
        cls.user_pool = []
        cls.client_manager = None
        cls._user_pool_index = 0
        if not cls.enabled():
            return
        if not Config.TDLIB_API_ID or not Config.TDLIB_API_HASH:
            cls.ERROR = "TDLIB_API_ID/TDLIB_API_HASH are missing"
            LOGGER.warning(f"TDLib upload backend disabled: {cls.ERROR}")
            return
        db_paths = []
        for db_path in cls._db_paths():
            if not await aiopath.exists(db_path):
                LOGGER.warning(f"TDLib user database not found at {db_path}")
                continue
            db_paths.append(db_path)
        if not db_paths:
            cls.ERROR = "TDLib user database not found"
            LOGGER.warning(f"TDLib upload backend disabled: {cls.ERROR}")
            return
        try:
            cls._patch_tdjson_binding()
            clients = []
            for index, db_path in enumerate(db_paths, start=1):
                LOGGER.info(f"Creating TDLib user client from {db_path}")
                client = Client(
                    api_id=Config.TDLIB_API_ID,
                    api_hash=Config.TDLIB_API_HASH,
                    default_parse_mode="html",
                    files_directory=db_path,
                    database_encryption_key=Config.TDLIB_DB_KEY or "mltbmltb",
                    use_file_database=True,
                    use_chat_info_database=True,
                    use_message_database=True,
                    workers=None,
                    td_verbosity=1,
                    user_bot=True,
                )
                setattr(client, "_mltb_db_path", db_path)
                setattr(client, "_mltb_db_index", index)
                clients.append(client)

            cls.client_manager = ClientManager(clients, verbosity=1)
            await cls.client_manager.start()

            from ..helper.telegram_helper.tdlib_progress import tdlib_file_update

            for client in clients:
                client.add_handler("updateFile", tdlib_file_update)

            for client in clients:
                for _ in range(120):
                    state = client.authorization_state
                    if state == "authorizationStateReady":
                        break
                    if state in {
                        "authorizationStateWaitPhoneNumber",
                        "authorizationStateWaitCode",
                        "authorizationStateWaitPassword",
                        "authorizationStateClosed",
                    }:
                        db_path = getattr(client, "_mltb_db_path", "unknown")
                        LOGGER.warning(
                            "Skipping TDLib user database: "
                            f"db={db_path} | state={state}"
                        )
                        try:
                            await client.stop()
                        except Exception:
                            pass
                        break
                    await sleep(0.5)
                else:
                    db_path = getattr(client, "_mltb_db_path", "unknown")
                    LOGGER.warning(
                        "Skipping TDLib user database due to timeout: "
                        f"db={db_path}"
                    )
                    try:
                        await client.stop()
                    except Exception:
                        pass
                    continue
                if client.authorization_state != "authorizationStateReady":
                    continue
                me = await client.getMe()
                if getattr(me, "is_error", False):
                    db_path = getattr(client, "_mltb_db_path", "unknown")
                    LOGGER.warning(
                        "Skipping TDLib user database due to getMe failure: "
                        f"db={db_path} | error={me['message']}"
                    )
                    try:
                        await client.stop()
                    except Exception:
                        pass
                    continue
                if cls.user is None:
                    cls.user = client
                cls.user_pool.append(client)
                cls.IS_PREMIUM_USER = cls.IS_PREMIUM_USER or bool(me.is_premium)

            if cls.IS_PREMIUM_USER:
                cls.IS_PREMIUM_USER = True
            if not cls.user_pool:
                cls.ERROR = "No authorized TDLib user databases available"
                LOGGER.warning(f"TDLib upload backend disabled: {cls.ERROR}")
                await cls.stop()
                return
            await cls.user.getChats()
            for client in cls.user_pool:
                try:
                    await client.invoke({"@type": "setNetworkType", "type": {"@type": "networkTypeWiFi"}})
                except Exception:
                    pass
                try:
                    await client.setAutoDownloadSettings(AutoDownloadSettings(), NetworkTypeOther())
                except Exception:
                    pass
            LOGGER.info(
                "TDLib user upload backend is ready "
                f"(premium={cls.IS_PREMIUM_USER}, dbs={','.join(getattr(c, '_mltb_db_path', 'unknown') for c in cls.user_pool)})"
            )
            cls.IS_AVAILABLE = True
        except Exception as e:
            cls.ERROR = str(e)
            LOGGER.exception("Failed to start TDLib user upload backend")
            await cls.stop()

    @classmethod
    async def stop(cls):
        async with cls._lock:
            for client in cls.user_pool:
                try:
                    await client.stop()
                except Exception:
                    pass
            if cls.client_manager:
                try:
                    await cls.client_manager.close()
                except Exception:
                    pass
            cls.user = None
            cls.user_pool = []
            cls.client_manager = None
            cls.IS_AVAILABLE = False
            cls.IS_PREMIUM_USER = False
            cls._user_pool_index = 0

    @classmethod
    async def reload(cls):
        await cls.stop()
        await cls.start_user()

    @classmethod
    def _primary_client(cls):
        return cls.user or (cls.user_pool[0] if cls.user_pool else None)

    @classmethod
    async def resolve_chat_id(cls, target):
        primary = cls._primary_client()
        if primary is None:
            raise ValueError("TDLib user client is not ready")
        if isinstance(target, int):
            if target > 0:
                try:
                    chat = await primary.createPrivateChat(user_id=target, force=True)
                    if not getattr(chat, "is_error", False):
                        return chat.id
                except Exception:
                    pass
            try:
                chat = await primary.getChat(chat_id=target)
                if not getattr(chat, "is_error", False):
                    return chat.id
            except Exception:
                pass
            return target
        target = str(target).strip()
        if target.lstrip("-").isdigit():
            return int(target)
        if target.lower() == "me":
            me = await primary.getMe()
            if getattr(me, "is_error", False):
                raise ValueError(me["message"])
            chat = await primary.createPrivateChat(user_id=me.id, force=True)
            if getattr(chat, "is_error", False):
                raise ValueError(chat["message"])
            return chat.id
        if target.startswith("@"):
            target = target[1:]
        chat = await primary.searchPublicChat(target)
        if getattr(chat, "is_error", False):
            raise ValueError(chat["message"])
        return chat.id
