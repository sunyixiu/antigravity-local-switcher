import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oauth_config
import quota


class LocalConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.client_id = b"1234567890-" + b"a" * 32 + b".apps.googleusercontent.com"
        self.secret = b"GO" + b"CSPX-" + b"x" * 28
        digest = hashlib.sha256(self.client_id + b"\0" + self.secret).hexdigest()
        known = patch.object(oauth_config, "COMPATIBLE_PAIR_SHA256", digest)
        known.start()
        self.addCleanup(known.stop)
        oauth_config._read_config.cache_clear()
        self.addCleanup(oauth_config._read_config.cache_clear)

    def test_selects_verified_pair_with_multiple_clients(self):
        data = b"\0".join([self.client_id.replace(b"a", b"b", 1), self.secret.replace(b"x", b"y", 1), self.secret, self.client_id])
        self.assertEqual(oauth_config.extract_config(data), (self.client_id.decode(), self.secret.decode()))

    def test_unknown_configuration_fails_without_network(self):
        with patch.object(quota, "local_client_config", side_effect=oauth_config.ConfigurationError("incompatible")):
            from test_quota import credential
            with self.assertRaisesRegex(quota.QuotaError, "incompatible"):
                quota.renew(credential(True), request=lambda *a, **k: self.fail("network reached"))
        with self.assertRaises(oauth_config.ConfigurationError):
            oauth_config.extract_config(self.client_id)

    def test_standard_install_and_updated_file_are_reread(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "Programs/Antigravity/resources/bin/language_server.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(self.client_id + b"\0" + self.secret)
            with patch.dict(oauth_config.os.environ, {"LOCALAPPDATA": directory, "ProgramFiles": directory}, clear=True):
                self.assertEqual(oauth_config.local_client_config()[0], self.client_id.decode())
                binary.write_bytes(b"new incompatible version")
                with self.assertRaises(oauth_config.ConfigurationError):
                    oauth_config.local_client_config()

    def test_machine_wide_install_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "Antigravity/resources/bin/language_server.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(self.client_id + b"\0" + self.secret)
            with patch.dict(oauth_config.os.environ, {"ProgramFiles": directory}, clear=True):
                self.assertEqual(oauth_config.local_client_config()[1], self.secret.decode())

    def test_missing_install_has_actionable_error(self):
        with patch.dict(oauth_config.os.environ, {}, clear=True):
            with self.assertRaisesRegex(oauth_config.ConfigurationError, "先安装"):
                oauth_config.local_client_config()
