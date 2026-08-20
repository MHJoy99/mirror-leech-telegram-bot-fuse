import json
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from logging import getLogger
from os import path as ospath, listdir, remove
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
    RetryError,
)

from .... import intervals
from ....core.config_manager import Config
from ...ext_utils.bot_utils import async_to_sync, SetInterval
from ...ext_utils.files_utils import get_mime_type
from ...mirror_leech_utils.gdrive_utils.helper import GoogleDriveHelper

LOGGER = getLogger(__name__)


class GoogleDriveUpload(GoogleDriveHelper):
    def __init__(self, listener, path, destination=None):
        self.listener = listener
        self._updater = None
        self._path = path
        self._destination = destination or listener.up_dest
        self._is_errored = False
        self.uploaded_files = {}
        super().__init__()
        self.is_uploading = True

    def _record_uploaded_file(self, file_name, link):
        if link:
            self.uploaded_files[link] = file_name

    def user_setting(self):
        if self._destination.startswith("mtp:"):
            self.token_path = f"tokens/{self.listener.user_id}.pickle"
            self._destination = self._destination.replace("mtp:", "", 1)
            self.use_sa = False
        elif self._destination.startswith("tp:"):
            self._destination = self._destination.replace("tp:", "", 1)
            self.use_sa = False
        elif self._destination.startswith("sa:"):
            self._destination = self._destination.replace("sa:", "", 1)
            self.use_sa = True

    def upload(self):
        self.user_setting()
        self.service = self.authorize()
        LOGGER.info(f"Uploading: {self._path}")
        self._updater = SetInterval(self.update_interval, self.progress)
        try:
            if ospath.isfile(self._path):
                mime_type = get_mime_type(self._path)
                link = self._upload_file(
                    self._path,
                    self.listener.name,
                    mime_type,
                    self._destination,
                    in_dir=False,
                )
                if self.listener.is_cancelled:
                    return
                if link is None:
                    raise ValueError("Upload has been manually cancelled")
                self._record_uploaded_file(self.listener.name, link)
                LOGGER.info(f"Uploaded To G-Drive: {self._path}")
            else:
                mime_type = "Folder"
                dir_id = self.create_directory(
                    ospath.basename(ospath.abspath(self.listener.name)),
                    self._destination,
                )
                result = self._upload_dir(self._path, dir_id, self._path)
                if result is None:
                    raise ValueError("Upload has been manually cancelled!")
                link = self.G_DRIVE_DIR_BASE_DOWNLOAD_URL.format(dir_id)
                if self.listener.is_cancelled:
                    return
                LOGGER.info(f"Uploaded To G-Drive: {self.listener.name}")
        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err = str(err).replace(">", "").replace("<", "")
            LOGGER.error(err)
            async_to_sync(self.listener.on_upload_error, err)
            self._is_errored = True
        finally:
            self._updater.cancel()
            if self.listener.is_cancelled and not self._is_errored:
                if mime_type == "Folder" and dir_id:
                    LOGGER.info("Deleting uploaded data from Drive...")
                    self.service.files().delete(
                        fileId=dir_id, supportsAllDrives=True
                    ).execute()
                return
            elif self._is_errored:
                return
            async_to_sync(
                self.listener.on_upload_complete,
                link,
                self.total_files,
                self.total_folders,
                mime_type,
                dir_id=self.get_id_from_url(link),
                drive_files=self.uploaded_files,
            )
            return

    def _upload_dir(self, input_directory, dest_id, base_directory):
        list_dirs = sorted(listdir(input_directory))
        if len(list_dirs) == 0:
            return dest_id
        new_id = None
        for item in list_dirs:
            current_file_name = ospath.join(input_directory, item)
            if not ospath.exists(current_file_name):
                if intervals["stopAll"]:
                    return
                LOGGER.error(f"{current_file_name} not exists! Continue uploading!")
                continue
            if ospath.isdir(current_file_name):
                current_dir_id = self.create_directory(item, dest_id)
                new_id = self._upload_dir(current_file_name, current_dir_id, base_directory)
                self.total_folders += 1
            else:
                mime_type = get_mime_type(current_file_name)
                file_name = current_file_name.split("/")[-1]
                file_link = self._upload_file(
                    current_file_name,
                    file_name,
                    mime_type,
                    dest_id,
                )
                rel_name = ospath.relpath(current_file_name, base_directory).replace(
                    "\\", "/"
                )
                self._record_uploaded_file(rel_name, file_link)
                self.total_files += 1
                new_id = dest_id
            if self.listener.is_cancelled:
                break
        return new_id

    @retry(
        wait=wait_exponential(multiplier=2, min=3, max=6),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    def _upload_file(self, file_path, file_name, mime_type, dest_id, in_dir=True):
        file_metadata = {
            "name": file_name,
            "description": "Uploaded by Mirror-leech-telegram-bot",
            "mimeType": mime_type,
        }
        if dest_id is not None:
            file_metadata["parents"] = [dest_id]

        if ospath.getsize(file_path) == 0:
            media_body = MediaFileUpload(file_path, mimetype=mime_type, resumable=False)
            response = (
                self.service.files()
                .create(
                    body=file_metadata, media_body=media_body, supportsAllDrives=True
                )
                .execute()
            )
            if not Config.IS_TEAM_DRIVE:
                self.set_permission(response["id"])

            drive_file = (
                self.service.files()
                .get(fileId=response["id"], supportsAllDrives=True)
                .execute()
            )
            return self.G_DRIVE_BASE_DOWNLOAD_URL.format(drive_file.get("id"))
        media_body = MediaFileUpload(
            file_path, mimetype=mime_type, resumable=True, chunksize=100 * 1024 * 1024
        )

        drive_file = self.service.files().create(
            body=file_metadata, media_body=media_body, supportsAllDrives=True
        )
        response = None
        retries = 0
        while response is None and not self.listener.is_cancelled:
            try:
                self.status, response = drive_file.next_chunk()
            except HttpError as err:
                if err.resp.status in [500, 502, 503, 504, 429] and retries < 10:
                    retries += 1
                    continue
                if err.resp.get("content-type", "").startswith("application/json"):
                    try:
                        err_json = json.loads(err.content.decode("utf-8") if isinstance(err.content, bytes) else err.content)
                        reason = (
                            err_json.get("error", {}).get("errors", [{}])[0].get("reason", "")
                        )
                    except Exception:
                        reason = ""
                    if reason not in [
                        "userRateLimitExceeded",
                        "dailyLimitExceeded",
                    ]:
                        raise err
                    if self.use_sa:
                        if self.sa_count >= self.sa_number:
                            LOGGER.info(
                                f"Reached maximum number of service accounts switching, which is {self.sa_count}"
                            )
                            raise err
                        else:
                            if self.listener.is_cancelled:
                                return
                            self.switch_service_account()
                            LOGGER.info(f"Got: {reason}, Trying Again...")
                            return self._upload_file(
                                file_path,
                                file_name,
                                mime_type,
                                dest_id,
                                in_dir,
                            )
                    else:
                        LOGGER.error(f"Got: {reason}")
                        raise err
        if self.listener.is_cancelled:
            return
        try:
            remove(file_path)
        except:
            pass
        self.file_processed_bytes = 0
        if not Config.IS_TEAM_DRIVE:
            self.set_permission(response["id"])
        drive_file = (
            self.service.files()
            .get(fileId=response["id"], supportsAllDrives=True)
            .execute()
        )
        return self.G_DRIVE_BASE_DOWNLOAD_URL.format(drive_file.get("id"))
