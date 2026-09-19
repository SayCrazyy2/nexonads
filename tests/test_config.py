import importlib
import sys
import types
import unittest
from unittest import mock


class ConfigTests(unittest.TestCase):
    def _load_config(self, env):
        with mock.patch.dict("os.environ", env, clear=True):
            fake_dotenv = types.ModuleType("dotenv")
            fake_dotenv.load_dotenv = lambda: None

            with mock.patch.dict(sys.modules, {"dotenv": fake_dotenv}):
                sys.modules.pop("config", None)
                return importlib.import_module("config")

    def test_bucket_env_values_are_loaded(self):
        config = self._load_config({
            "BOT_TOKEN": "token",
            "ADMIN_ID": "1",
            "API_ID": "2",
            "API_HASH": "hash",
            "RAILWAY_BUCKET_ENDPOINT": "https://s3.example.com",
            "RAILWAY_BUCKET_NAME": "bucket",
            "RAILWAY_BUCKET_ACCESS_KEY": "access",
            "RAILWAY_BUCKET_SECRET_KEY": "secret",
            "RAILWAY_BUCKET_REGION": "us-east-1",
            "RAILWAY_BUCKET_PREFIX": "prod",
        })

        self.assertEqual(config.RAILWAY_BUCKET_ENDPOINT, "https://s3.example.com")
        self.assertEqual(config.RAILWAY_BUCKET_NAME, "bucket")
        self.assertEqual(config.RAILWAY_BUCKET_ACCESS_KEY, "access")
        self.assertEqual(config.RAILWAY_BUCKET_SECRET_KEY, "secret")
        self.assertEqual(config.RAILWAY_BUCKET_REGION, "us-east-1")
        self.assertEqual(config.RAILWAY_BUCKET_PREFIX, "prod")

    def test_bucket_env_defaults_to_none_when_blank(self):
        config = self._load_config({
            "BOT_TOKEN": "token",
            "ADMIN_ID": "1",
            "API_ID": "2",
            "API_HASH": "hash",
            "RAILWAY_BUCKET_ENDPOINT": "   ",
        })
        self.assertIsNone(config.RAILWAY_BUCKET_ENDPOINT)
        self.assertIsNone(config.RAILWAY_BUCKET_NAME)


if __name__ == "__main__":
    unittest.main()
