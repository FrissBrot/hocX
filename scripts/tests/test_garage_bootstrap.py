"""infra/garage/bootstrap.py (storage-init): Secrets kommen im Release-Stack als *_FILE.

1.2.0 las GARAGE_ADMIN_TOKEN nur aus der Umgebung, Compose übergibt aber GARAGE_ADMIN_TOKEN_FILE -
storage-init meldete "nicht gesetzt", beendete sich mit Exit 0 und Garage blieb ohne Schlüssel
und Buckets (AccessDenied bei jedem Zugriff).
"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BOOTSTRAP = Path(__file__).resolve().parents[2] / "infra" / "garage" / "bootstrap.py"
KEYS = (
    "GARAGE_ADMIN_TOKEN", "GARAGE_ADMIN_TOKEN_FILE", "LOCAL_S3_ACCESS_KEY", "LOCAL_S3_SECRET_KEY",
    "LOCAL_S3_SECRET_KEY_FILE", "LOCAL_S3_ABGABEBOX_ACCESS_KEY", "LOCAL_S3_ABGABEBOX_SECRET_KEY",
)


def load(env: dict[str, str]):
    clean = {key: value for key, value in os.environ.items() if key not in KEYS}
    with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
        spec = importlib.util.spec_from_file_location("garage_bootstrap", BOOTSTRAP)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class GarageBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def secret(self, name: str, value: str) -> str:
        path = Path(self.tmp.name) / name
        path.write_text(value + "\n", encoding="utf-8")
        return str(path)

    def test_admin_token_from_secret_file(self):
        module = load({"GARAGE_ADMIN_TOKEN_FILE": self.secret("token", "abc123")})
        self.assertEqual(module.TOKEN, "abc123")

    def test_admin_token_from_environment(self):
        self.assertEqual(load({"GARAGE_ADMIN_TOKEN": "direct"}).TOKEN, "direct")

    def test_nothing_configured_skips_quietly(self):
        module = load({})
        with mock.patch.object(module, "wait_ready") as wait_ready:
            module.main()
        wait_ready.assert_not_called()

    def test_partial_configuration_fails(self):
        module = load({"LOCAL_S3_ACCESS_KEY": "GK0123", "LOCAL_S3_SECRET_KEY_FILE": self.secret("s", "x")})
        with mock.patch.dict(os.environ, {"LOCAL_S3_ACCESS_KEY": "GK0123",
                                          "LOCAL_S3_SECRET_KEY_FILE": self.secret("s", "x")}):
            with self.assertRaises(SystemExit) as raised:
                module.main()
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
