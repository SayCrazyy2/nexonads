import os
import tempfile
import unittest
from unittest import mock

from persistence import BucketPersistence


class FakeS3Client:
    def __init__(self):
        self.downloads = []
        self.uploads = []
        self.list_calls = []
        self.objects = {
            "prod/database/bot.db": b"db",
            "prod/sessions/a/account.session": b"s1",
            "prod/sessions/a/account.session-wal": b"s2",
            "prod/sessions/a/skip.txt": b"x",
        }

    def download_file(self, bucket, key, filename):
        self.downloads.append((bucket, key, filename))
        if key not in self.objects:
            error = {"Error": {"Code": "NoSuchKey"}}
            from botocore.exceptions import ClientError
            raise ClientError(error, "download_file")
        with open(filename, "wb") as file_obj:
            file_obj.write(self.objects[key])

    def upload_file(self, filename, bucket, key):
        self.uploads.append((filename, bucket, key))

    def list_objects_v2(self, **kwargs):
        self.list_calls.append(kwargs)
        prefix = kwargs["Prefix"]
        keys = [key for key in self.objects if key.startswith(prefix)]
        return {"Contents": [{"Key": key} for key in keys], "IsTruncated": False}


class BucketPersistenceTests(unittest.TestCase):
    def test_restore_downloads_db_and_session_files_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "data", "bot.db")
            sessions_dir = os.path.join(temp_dir, "sessions")
            client = FakeS3Client()

            persistence = BucketPersistence(
                db_path=db_path,
                sessions_dir=sessions_dir,
                endpoint="https://s3.example.com",
                bucket="bucket",
                access_key="key",
                secret_key="secret",
                prefix="prod",
            )

            with mock.patch.object(persistence, "_safe_client", return_value=client):
                persistence.restore()

            self.assertTrue(os.path.exists(db_path))
            self.assertTrue(os.path.exists(os.path.join(sessions_dir, "a", "account.session")))
            self.assertTrue(os.path.exists(os.path.join(sessions_dir, "a", "account.session-wal")))
            self.assertFalse(os.path.exists(os.path.join(sessions_dir, "a", "skip.txt")))

    def test_sync_uploads_db_and_session_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "data", "bot.db")
            sessions_dir = os.path.join(temp_dir, "sessions")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            os.makedirs(os.path.join(sessions_dir, "nested"), exist_ok=True)

            with open(db_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("db")
            with open(f"{db_path}-wal", "w", encoding="utf-8") as file_obj:
                file_obj.write("wal")
            with open(os.path.join(sessions_dir, "nested", "a.session"), "w", encoding="utf-8") as file_obj:
                file_obj.write("session")
            with open(os.path.join(sessions_dir, "nested", "ignore.txt"), "w", encoding="utf-8") as file_obj:
                file_obj.write("ignore")

            client = FakeS3Client()
            persistence = BucketPersistence(
                db_path=db_path,
                sessions_dir=sessions_dir,
                endpoint="https://s3.example.com",
                bucket="bucket",
                access_key="key",
                secret_key="secret",
                prefix="prod",
            )

            with mock.patch.object(persistence, "_safe_client", return_value=client):
                persistence.sync()

            uploaded_keys = {item[2] for item in client.uploads}
            self.assertIn("prod/database/bot.db", uploaded_keys)
            self.assertIn("prod/database/bot.db-wal", uploaded_keys)
            self.assertIn("prod/sessions/nested/a.session", uploaded_keys)
            self.assertNotIn("prod/sessions/nested/ignore.txt", uploaded_keys)


if __name__ == "__main__":
    unittest.main()
