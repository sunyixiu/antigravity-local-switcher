import base64
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_ui
import local_switcher as core
from synthetic_storage import SyntheticProtector


def credential(name):
    payload = {'token': {'access_token': 'synthetic-access-' + name, 'refresh_token': 'synthetic-refresh-' + name}}
    return {'blob': base64.b64encode(json.dumps(payload).encode()).decode(), 'username': 'synthetic', 'comment': None, 'persist': 2}


class SyntheticStore:
    def __init__(self):
        self.record = credential('A')
        self.reads = 0

    def read(self):
        self.reads += 1
        return self.record

    def write(self, _):
        raise AssertionError('Capture tests must not write OS credentials')


class SyntheticSwitcher:
    active = None

    def switch(self, _):
        raise core.LocalError('Synthetic test never closes or switches Antigravity')

    def restore(self):
        raise core.LocalError('Synthetic test never restores OS credentials')


class CaptureLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.temporary.name)
        self.store = SyntheticStore()
        self.app = desktop_ui.Application(directory=self.directory, store=self.store)
        self.app.vault.protector = SyntheticProtector()
        self.app.switcher = SyntheticSwitcher()
        self.server = desktop_ui.create_server(application=self.app)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, data=None, extra_cookie=''):
        headers = {'X-Local-Switcher': self.server.secret,
                   'Cookie': self.server.cookie_name + '=' + self.server.secret + extra_cookie,
                   'Origin': self.server.origin, 'Content-Type': 'application/json'}
        method = 'GET' if data is None else 'POST'
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        connection.request(method, path, body=None if data is None else json.dumps(data), headers=headers)
        response = connection.getresponse()
        status, body = response.status, json.loads(response.read())
        connection.close()
        return status, body

    def test_second_account_save_survives_old_idle_and_pagehide_conditions(self):
        first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
        self.assertEqual(self.request('/api/save', {'label': 'Synthetic first', 'request_id': first_id})[0], 200)
        first = (self.directory / (uuid.UUID(first_id).hex + '.agprofile')).read_bytes()
        self.app.last_seen = time.monotonic() - 7200
        self.assertFalse(self.app.should_stop())
        self.assertEqual(self.request('/api/close', {'token': self.server.secret})[0], 200)
        self.assertFalse(self.app.should_stop())
        self.store.record = credential('B')
        self.assertEqual(self.request('/api/save', {'label': 'Synthetic second', 'request_id': second_id})[0], 200)
        status, state = self.request('/api/state')
        self.assertEqual(status, 200)
        self.assertEqual({p['label'] for p in state['profiles']}, {'Synthetic first', 'Synthetic second'})
        self.assertEqual((self.directory / (uuid.UUID(first_id).hex + '.agprofile')).read_bytes(), first)
        second = self.app.vault.load(uuid.UUID(second_id).hex + '.agprofile')
        self.assertEqual(core.refresh_identity(second['credential']), 'synthetic-refresh-B')
        self.assertNotIn('synthetic-refresh', json.dumps(state))

    def test_repeated_save_request_is_not_a_second_capture(self):
        request_id = str(uuid.uuid4())
        data = {'label': 'Synthetic first', 'request_id': request_id}
        self.assertEqual(self.request('/api/save', data)[0], 200)
        self.store.record = credential('B')
        self.assertEqual(self.request('/api/save', data)[0], 200)
        self.assertEqual(self.store.reads, 1)
        self.assertEqual(len(self.app.vault.profiles()), 1)
        saved = self.app.vault.load(uuid.UUID(request_id).hex + '.agprofile')
        self.assertEqual(core.refresh_identity(saved['credential']), 'synthetic-refresh-A')

    def test_bad_request_id_cannot_choose_a_file_path(self):
        status, _ = self.request('/api/save', {'label': 'Synthetic', 'request_id': '../foreign'})
        self.assertEqual(status, 400)
        self.assertEqual(self.store.reads, 0)
        self.assertEqual(self.app.vault.profiles(), [])

    def test_rename_keeps_credential_quota_identity_and_active_selection(self):
        filename = self.app.vault.save('Before rename', credential('A'))
        self.app.switcher.active = filename
        self.app.last_attempt[filename] = self.app.clock()
        self.app.vault.write(filename + '.quota', {'updated': 100, 'groups': [], 'models': [], 'status': 'Synthetic'})
        cache_before = (self.directory / (filename + '.quota')).read_bytes()
        original_record = self.app.vault.load(filename)['credential']
        before_files = set(path.name for path in self.directory.glob('*.agprofile'))
        status, value = self.request('/api/rename', {'id': filename, 'label': '  工作账号 · 新名称  '})
        self.assertEqual(status, 200)
        self.assertEqual(self.app.vault.load(filename)['label'], '工作账号 · 新名称')
        self.assertEqual(self.app.vault.load(filename)['credential'], original_record)
        self.assertEqual((self.directory / (filename + '.quota')).read_bytes(), cache_before)
        self.assertEqual(self.app.switcher.active, filename)
        self.assertEqual(self.native_read_count(), 0)
        self.assertEqual(set(path.name for path in self.directory.glob('*.agprofile')), before_files)
        self.assertIn(filename, self.app.last_attempt)
        self.assertNotIn('新名称', (self.directory / 'diagnostics.log').read_text())

    def native_read_count(self):
        return self.store.reads

    def test_invalid_rename_does_not_modify_snapshot(self):
        filename = self.app.vault.save('Original', credential('A'))
        original = (self.directory / filename).read_bytes()
        for label in ('', '   ', 'x' * 81, 'line\nname', 123):
            self.assertEqual(self.request('/api/rename', {'id': filename, 'label': label})[0], 400)
        self.assertEqual(self.request('/api/rename', {'id': '../other', 'label': 'New'})[0], 400)
        self.assertEqual((self.directory / filename).read_bytes(), original)
        self.assertEqual(self.store.reads, 0)

    def test_rename_requires_idle_backend_and_supports_no_change(self):
        filename = self.app.vault.save('Original', credential('A'))
        original = (self.directory / filename).read_bytes()
        self.app.busy = True
        self.assertEqual(self.request('/api/rename', {'id': filename, 'label': 'New'})[0], 400)
        self.app.busy = False
        self.assertEqual(self.request('/api/rename', {'id': filename, 'label': 'Original'})[0], 200)
        self.assertEqual((self.directory / filename).read_bytes(), original)

    def test_quit_is_explicit_and_waits_for_operations(self):
        self.assertFalse(self.app.should_stop())
        self.app.busy = True
        self.assertEqual(self.request('/api/quit', {})[0], 400)
        self.assertFalse(self.app.should_stop())
        self.app.busy = False
        self.assertEqual(self.request('/api/quit', {})[0], 200)
        self.assertTrue(self.app.should_stop())

    def test_existing_launcher_validates_owner_without_account_data(self):
        path = self.directory / 'instance.json'
        path.write_text(json.dumps({'port': self.server.server_port, 'instance': self.server.instance}))
        self.assertEqual(desktop_ui.existing_url(path), self.server.origin + '/')
        path.write_text(json.dumps({'port': self.server.server_port, 'instance': '0' * 32}))
        self.assertIsNone(desktop_ui.existing_url(path))
        path.write_text(json.dumps({'port': True, 'instance': self.server.instance}))
        self.assertIsNone(desktop_ui.existing_url(path))

    def test_cookies_for_other_ports_do_not_replace_this_session(self):
        other = desktop_ui.create_server(demo=True)
        try:
            self.assertNotEqual(other.cookie_name, self.server.cookie_name)
            extra = '; ' + other.cookie_name + '=' + other.secret
            self.assertEqual(self.request('/api/save', {'label': 'Synthetic', 'request_id': str(uuid.uuid4())}, extra)[0], 200)
        finally:
            other.server_close()

    def test_diagnostics_exclude_credentials_and_labels(self):
        label = 'Private synthetic label'
        self.assertEqual(self.request('/api/save', {'label': label, 'request_id': str(uuid.uuid4())})[0], 200)
        text = (self.directory / 'diagnostics.log').read_text()
        self.assertIn('account.capture_complete', text)
        self.assertNotIn(label, text)
        self.assertNotIn('synthetic-refresh', text)
        self.assertNotIn('synthetic-access', text)


if __name__ == '__main__':
    unittest.main()
