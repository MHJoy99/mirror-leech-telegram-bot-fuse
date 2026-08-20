# ==============================================================================
#                      MIRROR-LEECH-TELEGRAM-BOT-FUSE CONFIGURATION
# ==============================================================================
# This configuration file controls bot behavior, database persistence, Telegram
# uploads (TDLib / Pyrogram), concurrency, cloud storage (Google Drive, Rclone),
# Leech parameters, torrent engines, media processing, and RSS automation.
#
# Instructions:
# 1. Fill in required parameters (BOT_TOKEN, OWNER_ID, TELEGRAM_API, TELEGRAM_HASH).
# 2. Adjust optional parameters according to your deployment needs.
# 3. Rename or copy this file to 'config.py' (or set CONFIG_MODULE environment variable).
# ==============================================================================


# ==============================================================================
# 1. REQUIRED CONFIGURATION
# ==============================================================================

# Telegram Bot Token obtained from @BotFather (e.g., "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")
# Type: str
BOT_TOKEN = ""

# Telegram User ID of the bot owner (e.g., 123456789)
# Type: int
OWNER_ID = 0

# Telegram API App ID obtained from https://my.telegram.org (e.g., 12345678)
# Type: int
TELEGRAM_API = 0

# Telegram API App Hash obtained from https://my.telegram.org (e.g., "0123456789abcdef0123456789abcdef")
# Type: str
TELEGRAM_HASH = ""


# ==============================================================================
# 2. TELEGRAM CLIENT & UPLOAD CONCURRENCY
# ==============================================================================

# Telegram HTTP / SOCKS5 proxy settings dictionary if running in restricted network environments
# Example: {"scheme": "socks5", "hostname": "127.0.0.1", "port": 1080, "username": "", "password": ""}
# Type: dict
TG_PROXY = {}

# Maximum concurrent part uploads per split file (Range: 1 to 4)
# Type: int (Default: 4)
TG_SPLIT_UPLOAD_CONCURRENCY = 4

# Maximum concurrent file uploads active at the same time across tasks (Range: 1 to 16)
# Type: int (Default: 8)
TG_FILE_UPLOAD_CONCURRENCY = 8

# Concurrency worker threads per file upload chunk stream (Range: 1 to 16)
# Type: int (Default: 16)
TG_UPLOAD_WORKERS = 16

# Pyrogram String Session for single premium/userbot upload (supports up to 4GB files)
# Generate via session generator script or bot
# Type: str
USER_SESSION_STRING = ""

# Pyrogram String Sessions pool for multi-user session uploads
# Example: ["session_str_1", "session_str_2"]
# Type: list of str
USER_SESSION_STRINGS = []


# ==============================================================================
# 3. TDLIB (FAST USERBOT ENGINE & POOL)
# ==============================================================================

# Dedicated Telegram API ID for TDLib userbot sessions (0 uses TELEGRAM_API)
# Type: int
TDLIB_API_ID = 0

# Dedicated Telegram API Hash for TDLib userbot sessions ("" uses TELEGRAM_HASH)
# Type: str
TDLIB_API_HASH = ""

# Encryption key for TDLib local database storage
# Type: str (Default: "mltbmltb")
TDLIB_DB_KEY = "mltbmltb"

# Path to primary TDLib user session database folder
# Type: str (Default: "tdlib_user")
TDLIB_USER_DB_PATH = "tdlib_user"

# List of paths to multiple authorized TDLib user session folders for pool uploading
# Example: ["tdlib_user", "tdlib_user_2", "tdlib_user_3"]
# Type: list of str
TDLIB_USER_DB_PATHS = []

# Enable ultra-fast TDLib userbot engine for large uploads (4GB premium / fast upload)
# Type: bool (Default: False)
TDLIB_USER_UPLOAD = False

# Minimum file size in bytes to trigger TDLib userbot upload engine
# Example: 2097152000 (2 GB) or 524288000 (500 MB)
# Type: int (Default: 2097152000)
TDLIB_USER_UPLOAD_MIN_SIZE = 2097152000


# ==============================================================================
# 4. DATABASE CONFIGURATION
# ==============================================================================

# MongoDB Connection URI for persisting settings, users, RSS feeds, incomplete tasks
# Example: "mongodb+srv://username:password@cluster0.mongodb.net/?retryWrites=true&w=majority"
# Type: str
DATABASE_URL = ""

# MongoDB Database name
# Type: str (Default: "mltb")
DATABASE_NAME = "mltb"


# ==============================================================================
# 5. ACCESS CONTROL & COMMANDS
# ==============================================================================

# Authorized Chat IDs (groups/channels) separated by space where the bot can be used
# Example: "-1001234567890 -1009876543210"
# Type: str
AUTHORIZED_CHATS = ""

# Sudo User IDs separated by space who have administrative control over the bot
# Example: "123456789 987654321"
# Type: str
SUDO_USERS = ""

# Custom suffix appended to bot commands to prevent conflicts in shared groups
# Example: "_bot1" -> command becomes /mirror_bot1
# Type: str
CMD_SUFFIX = ""


# ==============================================================================
# 6. GENERAL BOT SETTINGS & PIPELINE
# ==============================================================================

# Default upload destination: 'rc' (Rclone) or 'gd' (Google Drive)
# Type: str (Default: "rc")
DEFAULT_UPLOAD = "rc"

# Number of active tasks displayed per status message page
# Type: int (Default: 4)
STATUS_LIMIT = 4

# Status message refresh interval in seconds
# Type: int (Default: 15)
STATUS_UPDATE_INTERVAL = 15

# Notify users about incomplete tasks across bot restarts (requires DATABASE_URL)
# Type: bool (Default: False)
INCOMPLETE_TASK_NOTIFIER = False

# Regex/string substitution rules for renaming downloaded files
# Format: r"pattern1:replacement1|pattern2:replacement2"
# Example: r"\[1080p\]:|www\.website\.com - :"
# Type: str
NAME_SUBSTITUTE = r""

# File extensions to exclude from upload (separated by space, without leading dot)
# Example: "exe txt nfo sample"
# Type: str
EXCLUDED_EXTENSIONS = ""

# Only include specific file extensions for upload (separated by space, without leading dot)
# Example: "mkv mp4 zip rar"
# Type: str
INCLUDED_EXTENSIONS = ""

# Mapping of custom destination keys/aliases to cloud/chat destinations
# Example: {"main": "remote:videos", "dump": "-1001234567890"}
# Type: dict
UPLOAD_PATHS = {}

# Custom FFmpeg command pipelines to process media before upload
# Format: {"label": ["-command_args mltb.ext -del"]}
# Example: {"merge": ["-f concat -safe 0 -i mltb.txt -c copy mltb.mp4 -del"]}
# Type: dict
FFMPEG_CMDS = {}


# ==============================================================================
# 7. GOOGLE DRIVE CONFIGURATION
# ==============================================================================

# Google Drive Target Folder ID or Team Drive ID for uploads/clones
# Example: "0AO_xxxxxxxxx" or "1A2B3C4D5E6F7G8H9I0J" or "root"
# Type: str
GDRIVE_ID = ""

# Set to True if GDRIVE_ID is a Team Drive (Shared Drive)
# Type: bool (Default: False)
IS_TEAM_DRIVE = False

# Prevent uploading duplicate files if already present in destination Google Drive folder
# Type: bool (Default: False)
STOP_DUPLICATE = False

# Google Drive Index Worker / Cloudflare Index URL for direct stream & download links
# Example: "https://myindex.workers.dev/0:"
# Type: str
INDEX_URL = ""

# Use Google Service Accounts (service_accounts directory / accounts.zip) to bypass daily upload limits
# Type: bool (Default: False)
USE_SERVICE_ACCOUNTS = False


# ==============================================================================
# 8. RCLONE CONFIGURATION
# ==============================================================================

# Default Rclone remote path / destination folder (requires rclone.conf)
# Example: "remote_name:folder_name/subfolder"
# Type: str
RCLONE_PATH = ""

# Custom global flags passed to Rclone commands
# Example: "--fast-list --transfers=8 --buffer-size=64M"
# Type: str
RCLONE_FLAGS = ""

# Rclone serve HTTP URL for streaming/downloading files
# Example: "https://rclone.mydomain.com"
# Type: str
RCLONE_SERVE_URL = ""

# Rclone HTTP serve listening port
# Type: int (Default: 8080)
RCLONE_SERVE_PORT = 8080

# Username for Rclone HTTP serve authentication
# Type: str
RCLONE_SERVE_USER = ""

# Password for Rclone HTTP serve authentication
# Type: str
RCLONE_SERVE_PASS = ""


# ==============================================================================
# 9. LEECH & TELEGRAM UPLOADER CONFIGURATION
# ==============================================================================

# Maximum split size in bytes for Leech files (Default: 2097152000 for standard 2GB, 4194304000 for 4GB premium)
# Set to 0 to use bot limit automatically (2GB bot / 4GB userbot)
# Type: int (Default: 2097152000)
LEECH_SPLIT_SIZE = 2097152000

# Leech files as Document by default instead of Media (Video/Audio/Photo)
# Type: bool (Default: False)
AS_DOCUMENT = False

# Split files into equal sized parts instead of max part sizes
# Type: bool (Default: False)
EQUAL_SPLITS = False

# Upload split parts or multiple media files as a Telegram Media Group album
# Type: bool (Default: False)
MEDIA_GROUP = False

# Leech using user session (Telegram Premium Userbot) for 4GB upload support
# Type: bool (Default: False)
USER_TRANSMISSION = False

# Hybrid Leech upload mode (Userbot uploads big files, Bot uploads status/info)
# Type: bool (Default: False)
HYBRID_LEECH = False

# Global caption template for Leech uploads
# Supported dynamic placeholders: {filename}, {size}, {duration}, {languages}, {subtitles}
# Type: str
LEECH_CAPTION = """{filename}
📦 SIZE: {size}
🕒 DURATION: {duration}
🔊 LANGUAGE: {languages}
📄 SUBTITLES: {subtitles}"""

# Prefix added to the beginning of leeched file names
# Example: "[MyChannel] "
# Type: str
LEECH_FILENAME_PREFIX = ""

# Chat ID, Username (@channel), or 'pm' where all Leech files are forwarded/dumped
# Example: "-1001234567890" or "@my_leech_dump" or "pm"
# Type: str
LEECH_DUMP_CHAT = ""

# Destination chats for cloned messages (Chat_id/username|thread_id or list of chats)
# Example: "-1001234567890|2" or "[-1001234567890, '@backup_channel']"
# Type: str
CLONE_DUMP_CHATS = ""

# Send clickable Telegram message links of uploaded files in task complete message
# Type: bool (Default: False)
FILES_LINKS = False

# Thumbnail grid layout when generating multiple screenshot thumbnails (e.g., "2x2", "3x3", "2x4")
# Type: str (Default: "")
THUMBNAIL_LAYOUT = ""


# ==============================================================================
# 10. TORRENT & DIRECT DOWNLOAD (ARIA2 / QBITTORRENT)
# ==============================================================================

# Torrent stall / inactive timeout in seconds (0 to disable timeout)
# Stops torrents when no seeders/traffic occurs within the timeout
# Type: int (Default: 0)
TORRENT_TIMEOUT = 0

# Base URL / IP of the host server used for direct web downloads and Aria2/qBit web UI
# Example: "http://198.51.100.1" or "https://mltb.example.com"
# Type: str
BASE_URL = ""

# Port for the web server / file download server
# Type: int (Default: 80)
BASE_URL_PORT = 80

# Require pincode authorization before accessing web download links
# Type: bool (Default: False)
WEB_PINCODE = False


# ==============================================================================
# 11. QUEUEING SYSTEM
# ==============================================================================

# Total maximum simultaneous tasks (download + upload combined). 0 disables limit.
# Type: int (Default: 0)
QUEUE_ALL = 0

# Maximum simultaneous active downloads. 0 disables limit.
# Type: int (Default: 0)
QUEUE_DOWNLOAD = 0

# Maximum simultaneous active uploads. 0 disables limit.
# Type: int (Default: 0)
QUEUE_UPLOAD = 0


# ==============================================================================
# 12. RSS AUTOMATION
# ==============================================================================

# Delay interval in seconds between RSS feed refresh checks (Minimum: 600)
# Type: int (Default: 600)
RSS_DELAY = 600

# Telegram Chat ID where RSS feed auto-download notifications and updates are sent
# Example: "-1001234567890"
# Type: str
RSS_CHAT = ""

# Maximum file size in bytes for RSS automatic downloads. 0 disables limit.
# Example: 10737418240 (10 GB)
# Type: int (Default: 0)
RSS_SIZE_LIMIT = 0


# ==============================================================================
# 13. TORRENT SEARCH & SEARCH PLUGINS
# ==============================================================================

# API URL for external torrent search engines (e.g., Torrent Search API)
# Example: "https://torrent-search-api.example.com"
# Type: str
SEARCH_API_LINK = ""

# Maximum number of search results to fetch and display per query (0 = default limit)
# Type: int (Default: 0)
SEARCH_LIMIT = 0

# List of qBittorrent Nova3 python search plugin URLs enabled for in-bot search
# Type: list of str
SEARCH_PLUGINS = [
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/piratebay.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/limetorrents.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torlock.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torrentscsv.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/eztv.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torrentproject.py",
    "https://raw.githubusercontent.com/MaurizioRicci/qBittorrent_search_engines/master/kickass_torrent.py",
    "https://raw.githubusercontent.com/MaurizioRicci/qBittorrent_search_engines/master/yts_am.py",
    "https://raw.githubusercontent.com/MadeOfMagicAndWires/qBit-plugins/master/engines/linuxtracker.py",
    "https://raw.githubusercontent.com/MadeOfMagicAndWires/qBit-plugins/master/engines/nyaasi.py",
    "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/ettv.py",
    "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/glotorrents.py",
    "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/thepiratebay.py",
    "https://raw.githubusercontent.com/v1k45/1337x-qBittorrent-search-plugin/master/leetx.py",
    "https://raw.githubusercontent.com/nindogo/qbtSearchScripts/master/magnetdl.py",
    "https://raw.githubusercontent.com/msagca/qbittorrent_plugins/main/uniondht.py",
    "https://raw.githubusercontent.com/khensolomon/leyts/master/yts.py",
]


# ==============================================================================
# 14. DIRECT DOWNLOAD SERVICES & YT-DLP
# ==============================================================================

# FileLion Premium API Key for debrid/direct download links
# Type: str
FILELION_API = ""

# StreamWish Premium API Key for debrid/direct download links
# Type: str
STREAMWISH_API = ""

# JDownloader MyJDownloader account email
# Type: str
JD_EMAIL = ""

# JDownloader MyJDownloader account password
# Type: str
JD_PASS = ""

# File path to cookies.txt for yt-dlp authenticated extractions (e.g., YouTube, Netflix)
# Type: str (Default: "cookies.txt")
YT_DLP_COOKIEFILE = "cookies.txt"

# Default yt-dlp download options dict passed to YoutubeDL
# Example: {"format": "bestvideo+bestaudio/best", "nocheckcertificate": True}
# Type: dict
YT_DLP_OPTIONS = {}

# HTTP/SOCKS5 proxy URL for yt-dlp extraction requests
# Example: "http://user:pass@127.0.0.1:8080"
# Type: str
YT_DLP_PROXY = ""


# ==============================================================================
# 15. USENET / SABNZBD & NZB SEARCH
# ==============================================================================

# List of Usenet/SABnzbd server configurations for NZB downloads
# Example:
# USENET_SERVERS = [
#     {
#         "name": "main",
#         "host": "news.example.com",
#         "port": 563,
#         "timeout": 60,
#         "username": "user",
#         "password": "pass",
#         "connections": 8,
#         "ssl": 1,
#         "ssl_verify": 2,
#         "ssl_ciphers": "",
#         "enable": 1,
#         "required": 0,
#         "optional": 0,
#         "retention": 0,
#         "send_group": 0,
#         "priority": 0,
#     }
# ]
# Type: list of dict
USENET_SERVERS = []

# NZB Hydra 2 IP / Hostname for NZB search integration
# Example: "http://192.168.1.100:5076"
# Type: str
HYDRA_IP = ""

# NZB Hydra 2 API Key
# Type: str
HYDRA_API_KEY = ""


# ==============================================================================
# 16. UPSTREAM UPDATE CONFIGURATION
# ==============================================================================

# Git repository URL for automatic in-bot update command (/restart /update)
# Example: "https://github.com/username/repo"
# Type: str
UPSTREAM_REPO = ""

# Git repository branch to track for updates
# Type: str (Default: "master")
UPSTREAM_BRANCH = "master"
