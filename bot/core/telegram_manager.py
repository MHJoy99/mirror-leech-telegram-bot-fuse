from pyrogram import Client, enums
from pyrogram.types import LinkPreviewOptions
from asyncio import Lock
from os import makedirs
from re import split as re_split

from .. import LOGGER
from .config_manager import Config


class TgClient:
    _lock = Lock()
    _pool_lock = Lock()
    bot = None
    user = None
    user_pool = []
    _user_pool_index = 0
    NAME = ""
    ID = 0
    IS_PREMIUM_USER = False
    MAX_SPLIT_SIZE = 2097152000

    @classmethod
    def _collect_session_strings(cls):
        sessions = []

        def add(value):
            if not value:
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    add(item)
                return
            if not isinstance(value, str):
                value = str(value)
            for item in re_split(r"[\n,]+", value):
                item = item.strip()
                if item:
                    sessions.append(item)

        add(getattr(Config, "USER_SESSION_STRINGS", []))
        add(getattr(Config, "USER_SESSION_STRING", ""))
        return sessions

    @classmethod
    def has_user_pool(cls):
        return len(cls.user_pool) > 1

    @classmethod
    async def get_upload_client(cls):
        if cls.user_pool:
            if len(cls.user_pool) == 1:
                return cls.user_pool[0]
            async with cls._pool_lock:
                client = cls.user_pool[cls._user_pool_index % len(cls.user_pool)]
                cls._user_pool_index = (cls._user_pool_index + 1) % len(cls.user_pool)
                return client
        return cls.user

    @classmethod
    async def start_bot(cls):
        LOGGER.info("Creating client from BOT_TOKEN")
        cls.ID = Config.BOT_TOKEN.split(":", 1)[0]
        cls.bot = Client(
            cls.ID,
            Config.TELEGRAM_API,
            Config.TELEGRAM_HASH,
            proxy=Config.TG_PROXY,
            bot_token=Config.BOT_TOKEN,
            workdir="/app",
            parse_mode=enums.ParseMode.HTML,
            max_concurrent_transmissions=16,
            max_message_cache_size=15000,
            max_topic_cache_size=15000,
            sleep_threshold=0,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        await cls.bot.start()
        cls.NAME = cls.bot.me.username

    @classmethod
    async def start_user(cls):
        cls.user_pool = []
        cls.user = None
        cls._user_pool_index = 0
        cls.IS_PREMIUM_USER = False
        cls.MAX_SPLIT_SIZE = 2097152000
        session_strings = cls._collect_session_strings()
        if session_strings:
            for index, session_string in enumerate(session_strings, start=1):
                LOGGER.info(
                    "Creating client from USER_SESSION_STRING"
                    if len(session_strings) == 1
                    else f"Creating client from USER_SESSION_STRING #{index}"
                )
                try:
                    workdir = (
                        "/app"
                        if len(session_strings) == 1
                        else f"/app/user_sessions/{index}"
                    )
                    if len(session_strings) > 1:
                        makedirs(workdir, exist_ok=True)
                    client = Client(
                        "user" if len(session_strings) == 1 else f"user_{index}",
                        Config.TELEGRAM_API,
                        Config.TELEGRAM_HASH,
                        proxy=Config.TG_PROXY,
                        session_string=session_string,
                        workdir=workdir,
                        parse_mode=enums.ParseMode.HTML,
                        sleep_threshold=60,
                        max_concurrent_transmissions=16,
                        max_message_cache_size=15000,
                        max_topic_cache_size=15000,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
                    await client.start()
                    cls.user_pool.append(client)
                    if cls.user is None:
                        cls.user = client
                    if client.me.is_premium:
                        cls.IS_PREMIUM_USER = True
                except Exception as e:
                    LOGGER.error(
                        f"Failed to start client from USER_SESSION_STRING"
                        f"{'' if len(session_strings) == 1 else f' #{index}'}. {e}"
                    )
            if cls.user_pool and cls.IS_PREMIUM_USER:
                cls.MAX_SPLIT_SIZE = 4194304000
            if not cls.user_pool:
                cls.IS_PREMIUM_USER = False
                cls.user = None
        elif Config.USER_SESSION_STRING:
            LOGGER.info("Creating client from USER_SESSION_STRING")
            try:
                cls.user = Client(
                    "user",
                    Config.TELEGRAM_API,
                    Config.TELEGRAM_HASH,
                    proxy=Config.TG_PROXY,
                    session_string=Config.USER_SESSION_STRING,
                    workdir="/app",
                    parse_mode=enums.ParseMode.HTML,
                    sleep_threshold=60,
                    max_concurrent_transmissions=16,
                    max_message_cache_size=15000,
                    max_topic_cache_size=15000,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                await cls.user.start()
                cls.user_pool = [cls.user]
                cls.IS_PREMIUM_USER = cls.user.me.is_premium
                if cls.IS_PREMIUM_USER:
                    cls.MAX_SPLIT_SIZE = 4194304000
            except Exception as e:
                LOGGER.error(f"Failed to start client from USER_SESSION_STRING. {e}")
                cls.IS_PREMIUM_USER = False
                cls.user = None
                cls.user_pool = []

    @classmethod
    async def stop(cls):
        from .tdlib_manager import TdlibManager

        async with cls._lock:
            for client in cls.user_pool:
                try:
                    await client.stop()
                except Exception:
                    pass
            if cls.bot:
                await cls.bot.stop()
            await TdlibManager.stop()
            cls.user_pool = []
            cls.user = None
            LOGGER.info("Client(s) stopped")

    @classmethod
    async def reload(cls):
        from .tdlib_manager import TdlibManager

        async with cls._lock:
            await cls.bot.restart()
            if cls.user_pool:
                for client in cls.user_pool:
                    await client.restart()
            await TdlibManager.reload()
            LOGGER.info("Client(s) restarted")
