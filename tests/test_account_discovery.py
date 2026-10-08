import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import account_discovery
import desktop_ui
import local_switcher as core
import quota
from synthetic_storage import SyntheticProtector
from test_capture_lifecycle import SyntheticStore, SyntheticSwitcher, credential


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        config = patch.object(quota, "local_client_config", return_value=("synthetic.apps.googleusercontent.com", "synthetic-client-config"))
        config.start()
        self.addCleanup(config.stop)
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.temporary.name)
        self.store = SyntheticStore()
        self.vault = core.Vault(self.directory)
        self.vault.protector = SyntheticProtector()
        self.calls = []
        self.now = 1000.0
        self.profile = {'id': 'synthetic-google-subject', 'email': 'synthetic@example.invalid', 'name': 'Synthetic User'}
        self.service = account_discovery.Discovery(self.store, self.vault, self.request, lambda: self.now)

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, url, payload, **options):
        self.calls.append((url, payload, options))
        if url == quota.TOKEN_URL:
            return {'access_token': 'synthetic-renewed', 'expires_in': 3600}
        self.assertEqual(url, quota.USER_INFO_URL)
        self.assertEqual(options['method'], 'GET')
        return self.profile

    def confirm(self, label='Work', request_id=None, scan_id=None):
        return self.service.confirm(scan_id or self.service.view['scan_id'], label, request_id or str(uuid.uuid4()))

    def test_new_login_is_verified_but_not_saved_until_named(self):
        view = self.service.scan()
        self.assertEqual(view['status'], 'new')
        self.assertEqual(view['email'], self.profile['email'])
        self.assertEqual(self.vault.profiles(), [])
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('token', json.dumps(view))
        filename = self.confirm('  工作账号  ')
        saved = self.vault.load(filename)
        self.assertEqual(saved['label'], '工作账号')
        self.assertEqual(saved['credential'], self.store.record)
        self.assertEqual(saved['identity']['subject'], self.profile['id'])
        self.assertEqual(self.service.view['status'], 'known')

    def test_known_refresh_grant_does_not_query_network_or_duplicate(self):
        filename = self.vault.save('Existing', self.store.record)
        before = (self.directory / filename).read_bytes()
        view = self.service.scan()
        self.assertEqual(view['status'], 'known')
        self.assertEqual(view['existing_id'], filename)
        self.assertEqual(self.calls, [])
        self.assertEqual((self.directory / filename).read_bytes(), before)

    def test_rescan_reads_current_login_and_reuses_unchanged_pending_identity(self):
        first = self.service.scan()
        again = self.service.scan()
        self.assertEqual(first['scan_id'], again['scan_id'])
        self.assertEqual(len(self.calls), 1)
        self.store.record = credential('B')
        self.profile = dict(self.profile, id='synthetic-B', email='second@example.invalid')
        changed = self.service.scan()
        self.assertNotEqual(changed['scan_id'], first['scan_id'])
        self.assertEqual(changed['email'], 'second@example.invalid')
        self.assertEqual(len(self.calls), 2)

    def test_same_google_subject_with_new_grant_matches_existing_identity(self):
        identity = account_discovery.verified_profile(self.profile)
        filename = self.vault.save('Existing', credential('old-grant'), identity=identity)
        view = self.service.scan()
        self.assertEqual(view['status'], 'known')
        self.assertEqual(view['existing_id'], filename)
        self.assertEqual(len(self.vault.profiles()), 1)

    def test_signed_out_has_clear_state_without_network(self):
        self.store.record = None
        self.assertEqual(self.service.scan()['status'], 'signed-out')
        self.assertEqual(self.calls, [])

    def test_account_changes_between_scan_and_confirmation_are_rejected(self):
        self.service.scan()
        self.store.record = credential('B')
        with self.assertRaises(core.LocalError):
            self.confirm()
        self.assertEqual(self.vault.profiles(), [])
        self.assertEqual(self.service.view['status'], 'changed')

    def test_expired_scan_does_not_read_or_persist_wrong_account(self):
        self.service.scan()
        reads = self.store.reads
        self.now += 601
        with self.assertRaises(core.LocalError):
            self.confirm()
        self.assertEqual(self.store.reads, reads)
        self.assertEqual(self.vault.profiles(), [])

    def test_response_retry_is_idempotent(self):
        view = self.service.scan()
        request_id = str(uuid.uuid4())
        filename = self.confirm(request_id=request_id)
        self.store.record = credential('B')
        again = self.confirm(request_id=request_id, scan_id=view['scan_id'])
        self.assertEqual(again, filename)
        self.assertEqual(len(self.vault.profiles()), 1)

    def test_invalid_name_scan_and_request_ids_do_not_save(self):
        self.service.scan()
        for label in ('', '  ', 'x' * 81, 'bad\nlabel', None):
            with self.assertRaises(core.LocalError):
                self.confirm(label=label)
        with self.assertRaises(core.LocalError):
            self.confirm(scan_id='../other')
        with self.assertRaises(core.LocalError):
            self.confirm(request_id='../other')
        self.assertEqual(self.vault.profiles(), [])

    def test_validated_identity_survives_rename_and_same_grant_refresh(self):
        self.service.scan()
        filename = self.confirm()
        old = self.vault.load(filename)
        self.vault.save('Renamed', old['credential'], filename)
        self.assertEqual(self.vault.load(filename)['identity'], old['identity'])
        rotated = credential('rotated')
        self.vault.save('Renamed', rotated, filename, identity=old['identity'])
        self.assertEqual(self.vault.load(filename)['identity'], old['identity'])
        self.vault.save('Different account', credential('B'), filename)
        self.assertNotIn('identity', self.vault.load(filename))

    def test_google_identity_validation_failure_never_creates_candidate(self):
        self.profile = {'id': 'subject', 'email': 'not-an-email'}
        with self.assertRaises(core.LocalError):
            self.service.scan()
        self.assertIsNone(self.service.pending)
        self.assertEqual(self.vault.profiles(), [])

    def test_expired_access_token_is_refreshed_only_in_candidate(self):
        record = copy.deepcopy(self.store.record)
        value, token, _ = quota.decode(record)
        token['expiry_timestamp'] = time.time() - 60
        record['blob'] = base64.b64encode(json.dumps(value).encode()).decode()
        self.store.record = record
        self.service.scan()
        self.assertEqual([c[0] for c in self.calls], [quota.TOKEN_URL, quota.USER_INFO_URL])
        self.assertEqual(self.vault.profiles(), [])
        filename = self.confirm()
        self.assertEqual(quota.decode(self.vault.load(filename)['credential'])[1]['access_token'], 'synthetic-renewed')
        self.assertEqual(self.store.record, record)

    def test_backend_exposes_bounded_scan_view_without_credential_record(self):
        app = desktop_ui.Application(directory=self.directory, store=self.store, request_sender=self.request, wait=lambda _: None)
        app.vault.protector = SyntheticProtector()
        app.switcher = SyntheticSwitcher()
        app.action('scan', {})
        deadline = time.monotonic() + 2
        while app.busy and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(app.busy)
        public = app.state()
        self.assertEqual(public['scan']['status'], 'new')
        self.assertNotIn('synthetic-refresh', json.dumps(public))
        self.assertNotIn('synthetic-access', json.dumps(public))
        self.assertEqual(app.vault.profiles(), [])
        app.action('add-discovered', {'scan_id': public['scan']['scan_id'], 'label': 'Confirmed', 'request_id': str(uuid.uuid4())})
        self.assertEqual(len(app.vault.profiles()), 1)


if __name__ == '__main__':
    unittest.main()
