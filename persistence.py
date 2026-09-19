import logging
import os
from pathlib import Path
from typing import Iterable

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

DB_ARTIFACTS = ("", "-wal", "-shm")
SESSION_SUFFIXES = (
    ".session",
    ".session-journal",
    ".session-wal",
    ".session-shm",
)
SESSION_IGNORED_DIRS = {".git", "__pycache__"}


class BucketPersistence:
    def __init__(
        self,
        *,
        db_path: str,
        sessions_dir: str,
        endpoint: str | None,
        bucket: str | None,
        access_key: str | None,
        secret_key: str | None,
        region: str | None = None,
        prefix: str | None = None,
    ):
        self.db_path = db_path
        self.sessions_dir = sessions_dir
        self.endpoint = endpoint
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.prefix = (prefix or "").strip().strip("/")

        self._client = None

    @property
    def enabled(self) -> bool:
        return all([
            self.endpoint,
            self.bucket,
            self.access_key,
            self.secret_key,
        ])

    def ensure_local_paths(self):
        db_parent = os.path.dirname(self.db_path)
        if db_parent:
            os.makedirs(db_parent, exist_ok=True)
        os.makedirs(self.sessions_dir, exist_ok=True)

    def restore(self):
        self.ensure_local_paths()

        if not self.enabled:
            logger.info("Railway bucket persistence is disabled; using local storage only.")
            return

        client = self._safe_client()
        if not client:
            return

        for local_path, object_key in self._db_artifacts():
            self._download_if_exists(client, object_key, local_path)

        session_prefix = self._prefixed("sessions/")
        continuation_token = None

        while True:
            try:
                kwargs = {
                    "Bucket": self.bucket,
                    "Prefix": session_prefix,
                }
                if continuation_token:
                    kwargs["ContinuationToken"] = continuation_token

                response = client.list_objects_v2(**kwargs)
            except (BotoCoreError, ClientError) as exc:
                logger.warning(
                    "Could not list Railway bucket session objects. Falling back to local sessions. Error: %s",
                    exc,
                )
                return

            for entry in response.get("Contents", []):
                key = entry.get("Key")
                if not key or key.endswith("/"):
                    continue

                relative = key[len(session_prefix):]
                if not relative:
                    continue

                local_path = os.path.join(self.sessions_dir, relative)
                if not self._should_sync_session_path(local_path):
                    continue

                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                self._download_if_exists(client, key, local_path)

            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")

    def sync(self):
        self.ensure_local_paths()

        if not self.enabled:
            return

        client = self._safe_client()
        if not client:
            return

        for local_path, object_key in self._db_artifacts():
            if os.path.exists(local_path):
                self._upload_file(client, local_path, object_key)

        for local_path in self._iter_session_files():
            relative = os.path.relpath(local_path, self.sessions_dir).replace("\\", "/")
            object_key = self._prefixed(f"sessions/{relative}")
            self._upload_file(client, local_path, object_key)

    def _db_artifacts(self) -> Iterable[tuple[str, str]]:
        for suffix in DB_ARTIFACTS:
            local_path = f"{self.db_path}{suffix}"
            key = self._prefixed(f"database/bot.db{suffix}")
            yield local_path, key

    def _safe_client(self):
        if self._client is not None:
            return self._client

        try:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=Config(signature_version="s3v4"),
            )
            return self._client
        except Exception as exc:
            logger.warning(
                "Could not initialize Railway bucket client. Falling back to local storage. Error: %s",
                exc,
            )
            return None

    def _download_if_exists(self, client, object_key: str, local_path: str):
        try:
            client.download_file(self.bucket, object_key, local_path)
            logger.info("Restored file from Railway bucket: %s", object_key)
        except ClientError as exc:
            error_code = (
                exc.response.get("Error", {})
                .get("Code", "")
            )
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return
            logger.warning(
                "Could not download %s from Railway bucket. Using local file if available. Error: %s",
                object_key,
                exc,
            )
        except BotoCoreError as exc:
            logger.warning(
                "Could not download %s from Railway bucket. Using local file if available. Error: %s",
                object_key,
                exc,
            )

    def _upload_file(self, client, local_path: str, object_key: str):
        try:
            client.upload_file(local_path, self.bucket, object_key)
            logger.info("Synced file to Railway bucket: %s", object_key)
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "Could not sync %s to Railway bucket key %s. Local file remains unchanged. Error: %s",
                local_path,
                object_key,
                exc,
            )

    def _iter_session_files(self):
        base = Path(self.sessions_dir)
        if not base.exists():
            return

        for path in base.rglob("*"):
            if not path.is_file():
                continue

            if any(part in SESSION_IGNORED_DIRS for part in path.parts):
                continue

            local_path = str(path)
            if self._should_sync_session_path(local_path):
                yield local_path

    def _should_sync_session_path(self, local_path: str) -> bool:
        name = os.path.basename(local_path)
        return name.endswith(SESSION_SUFFIXES)

    def _prefixed(self, key: str) -> str:
        key = key.lstrip("/")
        if not self.prefix:
            return key
        return f"{self.prefix}/{key}"
