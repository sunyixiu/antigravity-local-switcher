import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_ui
import instance_control
import local_switcher as core


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.path = Path(self.temp.name) / 'instance.json'
        self.server = desktop_ui.create_server(demo=True)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.path.write_text(json.dumps({'port': self.server.server_port, 'instance': self.server.instance}))
        self.instance = instance_control.Instance(self.server.server_port, self.server.instance, '0.3')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=1)
        self.temp.cleanup()

    def test_probe_verifies_registered_identity(self):
        value = instance_control.probe(self.path)
        self.assertEqual(value.port, self.server.server_port)
        self.assertEqual(value.owner, self.server.instance)
        self.assertEqual(value.version, desktop_ui.VERSION)

    def test_idle_old_backend_exits_through_authenticated_quit(self):
        self.assertEqual(instance_control.retire(self.instance), 'stopped')
        self.assertTrue(self.server.application.shutdown_requested)

    def test_busy_backend_keeps_running_until_operation_completes(self):
        self.server.application.busy = True
        self.assertEqual(instance_control.retire(self.instance), 'busy')
        self.assertFalse(self.server.application.shutdown_requested)
        self.server.application.busy = False
        self.assertEqual(instance_control.retire(self.instance), 'stopped')

    def test_foreign_instance_is_not_stopped(self):
        foreign = instance_control.Instance(self.server.server_port, '0' * 32, '0.3')
        self.assertEqual(instance_control.retire(foreign), 'gone')
        self.assertFalse(self.server.application.shutdown_requested)
        self.path.write_text(json.dumps({'port': self.server.server_port, 'instance': '0' * 32}))
        self.assertIsNone(instance_control.probe(self.path))

    def test_replaced_instance_between_requests_is_not_stopped(self):
        owner = {'app': 'AntigravityLocalSwitcher', 'instance': self.server.instance}
        foreign = {'app': 'AntigravityLocalSwitcher', 'instance': '0' * 32}
        with patch.object(instance_control, 'identity', side_effect=[owner, foreign]):
            self.assertEqual(instance_control.retire(self.instance), 'gone')
        self.assertFalse(self.server.application.shutdown_requested)

    def test_cookie_and_control_token_mismatch_rejects_shutdown(self):
        class WrongToken:
            token = 'x' * 43
            def feed(self, _):
                pass
        with patch.object(instance_control, 'TokenParser', WrongToken):
            with self.assertRaises(core.LocalError):
                instance_control.retire(self.instance)
        self.assertFalse(self.server.application.shutdown_requested)

    def test_instance_file_cannot_specify_remote_host_or_invalid_port(self):
        self.path.write_text(json.dumps({'port': True, 'instance': self.server.instance}))
        self.assertIsNone(instance_control.probe(self.path))
        self.path.write_text(json.dumps({'port': 999999, 'instance': self.server.instance}))
        self.assertIsNone(instance_control.probe(self.path))


if __name__ == '__main__':
    unittest.main()
