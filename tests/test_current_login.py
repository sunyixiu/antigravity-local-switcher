import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import account_discovery
import current_login
import desktop_ui
import local_switcher as core
from synthetic_storage import SyntheticProtector
from test_capture_lifecycle import SyntheticStore, SyntheticSwitcher, credential


class CurrentLoginTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.app = desktop_ui.Application(directory=Path(self.temporary.name), store=SyntheticStore(),
                                          request_sender=lambda *a, **k: self.fail('current-login polling must not contact Google'))
        self.app.vault.protector = SyntheticProtector()
        self.app.switcher = SyntheticSwitcher()
        self.first = self.app.vault.save('First', credential('A'))
        self.second = self.app.vault.save('Second', credential('B'))

    def marked(self):
        state = self.app.state()
        self.assertNotIn('synthetic-refresh', json.dumps(state))
        self.assertNotIn('synthetic-access', json.dumps(state))
        return state, [p['id'] for p in state['profiles'] if p['current']]

    def test_current_login_does_not_follow_recent_selection(self):
        self.app.switcher.active = self.second
        state, active = self.marked()
        self.assertEqual(active, [self.first])
        self.assertEqual(state['current_login']['label'], 'First')

    def test_external_switch_and_logout_are_detected(self):
        self.marked()
        self.app.store.record = credential('B')
        self.assertEqual(self.marked()[1], [self.second])
        self.app.store.record = None
        state, active = self.marked()
        self.assertEqual(active, [])
        self.assertEqual(state['current_login']['status'], 'signed-out')

    def test_access_token_change_does_not_change_identity(self):
        record = credential('A')
        token = json.loads(base64.b64decode(record['blob']))
        token['token']['access_token'] = 'synthetic-new-access'
        record['blob'] = base64.b64encode(json.dumps(token).encode()).decode()
        self.app.store.record = record
        self.assertEqual(self.marked()[1], [self.first])

    def test_unknown_or_unreadable_login_is_not_guessed(self):
        self.app.store.record = credential('C')
        self.assertEqual(self.marked()[0]['current_login']['status'], 'unmatched')
        with patch.object(self.app.store, 'read', side_effect=core.LocalError('private backend detail')):
            state, active = self.marked()
            self.assertEqual(active, [])
            self.assertEqual(state['current_login']['status'], 'error')
            self.assertNotIn('private backend detail', json.dumps(state))

    def test_duplicate_snapshots_are_not_arbitrarily_selected(self):
        self.app.vault.save('Duplicate', credential('A'))
        state, active = self.marked()
        self.assertEqual(active, [])
        self.assertEqual(state['current_login']['status'], 'ambiguous')

    def test_rotation_preserves_verified_binding_but_manual_replacement_does_not(self):
        self.assertEqual(self.marked()[1], [self.first])
        rotated = credential('A-rotated')
        self.app.vault.save('First', rotated, self.first)
        self.app.current_login.rotated(self.first, credential('A'), rotated)
        self.assertEqual(self.marked()[1], [self.first])
        self.app.vault.save('Unrelated replacement', credential('C'), self.first)
        self.assertEqual(self.marked()[1], [])

    def test_google_verified_scan_binding_requires_unchanged_current_and_snapshot(self):
        self.app.store.record = credential('A-new-grant')
        self.app.discovery.verified_binding = (account_discovery.fingerprint(self.app.store.record), self.first,
                                               account_discovery.fingerprint(credential('A')))
        self.assertEqual(self.marked()[1], [self.first])
        self.app.store.record = credential('C')
        self.assertEqual(self.marked()[1], [])

    def test_switching_does_not_claim_a_completed_login(self):
        self.app.switch_in_progress = True
        state, active = self.marked()
        self.assertEqual(active, [])
        self.assertEqual(state['current_login']['status'], 'switching')
        self.app.switch_in_progress = False
        self.assertEqual(self.marked()[1], [self.first])

    def test_delete_removes_snapshot_cache_and_schedule_without_logging_out(self):
        self.app.vault.write(self.first + '.quota', {'updated': 1000})
        self.app.last_attempt[self.first] = 100
        self.app.auto.reset_attempts[self.first + ':123'] = self.app.wall_clock()
        self.app.auto.save()
        original = self.app.store.record
        self.app.action('delete', {'id': self.first})
        self.assertEqual(self.app.store.record, original)
        self.assertFalse((self.app.directory / self.first).exists())
        self.assertFalse((self.app.directory / (self.first + '.quota')).exists())
        self.assertNotIn(self.first, self.app.last_attempt)
        self.assertFalse(any(key.startswith(self.first + ':') for key in self.app.auto.reset_attempts))
        self.assertEqual(self.marked()[0]['current_login']['status'], 'unmatched')
        self.assertEqual(self.app.vault.load(self.second)['label'], 'Second')

    def test_delete_cannot_race_a_query_or_switch(self):
        self.app.busy = True
        with self.assertRaises(core.LocalError):
            self.app.action('delete', {'id': self.first})
        self.assertTrue((self.app.directory / self.first).exists())

    def test_delete_rejects_arbitrary_paths(self):
        for name in ['../before-switch.agrecovery', 'refresh-settings.json', None]:
            with self.assertRaises(core.LocalError):
                self.app.action('delete', {'id': name})
        self.assertTrue(self.app.auto.path.exists())
        self.assertEqual(len(self.app.vault.profiles()), 2)

    def test_missing_account_does_not_delete_other_files(self):
        with self.assertRaises(OSError):
            self.app.action('delete', {'id': 'f' * 32 + '.agprofile'})
        self.assertEqual(len(self.app.vault.profiles()), 2)

    def test_delete_restores_removed_files_if_a_later_removal_fails(self):
        self.app.vault.write(self.first + '.quota', {'updated': 1000})
        profile = self.app.directory / self.first
        cache = self.app.directory / (self.first + '.quota')
        original = profile.read_bytes()
        unlink = Path.unlink
        def fail_cache(path, *args, **kwargs):
            if path == cache:
                raise PermissionError('synthetic failure')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_cache):
            with self.assertRaises(core.LocalError):
                self.app.action('delete', {'id': self.first})
        self.assertEqual(profile.read_bytes(), original)
        self.assertEqual(self.app.vault.read(cache.name)['updated'], 1000)

    def test_matching_recovery_is_removed_with_deleted_account(self):
        self.app.vault.write('before-switch.agrecovery', {'version': 1, 'credential': credential('A')})
        self.app.action('delete', {'id': self.first})
        self.assertFalse((self.app.directory / 'before-switch.agrecovery').exists())

    def test_unrelated_recovery_is_preserved(self):
        self.app.vault.write('before-switch.agrecovery', {'version': 1, 'credential': credential('B')})
        self.app.action('delete', {'id': self.first})
        self.assertEqual(self.app.vault.read('before-switch.agrecovery')['credential'], credential('B'))
