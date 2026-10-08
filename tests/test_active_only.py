import base64
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import account_discovery
import desktop_ui
import local_switcher as core
import quota
import quota_projection
import refresh_policy
from synthetic_storage import SyntheticProtector
from test_capture_lifecycle import credential, SyntheticStore, SyntheticSwitcher
from test_refresh_schedule import Clock
from test_quota import response, group_response


def updated_record(name, access, expired=False):
    record = credential(name)
    value, token, _ = quota.decode(record)
    token['access_token'] = access
    token['expiry'] = datetime.fromtimestamp(time.time() + (-60 if expired else 3600), timezone.utc).isoformat()
    record['blob'] = base64.b64encode(json.dumps(value).encode()).decode()
    return record


class ActiveOnlyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.clock = Clock()
        self.running = True
        self.store = SyntheticStore()
        self.calls = []
        self.app = desktop_ui.Application(directory=Path(temporary.name), store=self.store,
                                          running_check=lambda: self.running, request_sender=self.sender,
                                          clock=lambda: self.clock.mono, wall_clock=lambda: self.clock.wall, wait=self.clock.wait)
        self.app.vault.protector = SyntheticProtector()
        self.app.switcher = SyntheticSwitcher()
        self.a = self.app.vault.save('A', credential('A'))
        self.b = self.app.vault.save('B', credential('B'))
        self.app.eligible_login()
        self.app.session.pending = None

    def sender(self, url, payload, **options):
        self.calls.append((url, options.get('access')))
        self.assertNotEqual(url, quota.TOKEN_URL)
        if url == quota.CONTEXT_URL:
            return {}
        return group_response() if url in quota.GROUP_URLS else response()

    def join(self):
        deadline = time.monotonic() + 3
        while self.app.busy and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(self.app.busy)

    def test_inactive_refresh_rejected_even_through_direct_api(self):
        with self.assertRaises(core.LocalError):
            self.app.action('refresh-one', {'id': self.b})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.app.cached(self.b), {})

    def test_closed_client_never_queries_or_scans_over_network(self):
        self.running = False
        for action, payload in [('refresh', {}), ('refresh-one', {'id': self.a})]:
            with self.assertRaises(core.LocalError):
                self.app.action(action, payload)
        self.clock.advance(24 * 3600)
        self.app.scheduler_tick()
        self.assertEqual(self.calls, [])
        view = self.app.state()
        self.assertFalse(view['current_login']['quota_eligible'])
        self.assertTrue(next(p for p in view['profiles'] if p['id'] == self.a)['quota']['offline'])
        # A known grant can still be recognized locally without a Google call.
        self.app.discovery.scan()
        self.assertEqual(self.calls, [])

    def test_request_uses_official_latest_access_token_and_syncs_snapshot(self):
        fresh = updated_record('A', 'synthetic-official-new-access')
        self.store.record = fresh
        untouched = (self.app.directory / self.b).read_bytes()
        self.app.action('refresh', {})
        self.join()
        self.assertEqual({access for _, access in self.calls}, {'synthetic-official-new-access'})
        self.assertEqual(self.app.vault.load(self.a)['credential'], fresh)
        self.assertEqual((self.app.directory / self.b).read_bytes(), untouched)

    def test_snapshot_sync_runs_when_automatic_queries_disabled(self):
        self.app.auto.configure(0)
        fresh = updated_record('A', 'synthetic-official-refresh')
        self.store.record = fresh
        self.app.scheduler_tick()
        self.assertEqual(self.app.vault.load(self.a)['credential'], fresh)
        self.assertEqual(self.calls, [])

    def test_new_grant_is_never_bound_to_last_clicked_account(self):
        before = (self.app.directory / self.a).read_bytes()
        self.app.switcher.active = self.a
        self.store.record = credential('unknown')
        self.app.scheduler_tick()
        self.clock.advance(10)
        self.app.scheduler_tick()
        self.assertEqual(self.app.state()['current_login']['status'], 'unmatched')
        self.assertEqual((self.app.directory / self.a).read_bytes(), before)
        self.assertEqual(self.calls, [])

    def test_external_account_change_stops_remaining_requests(self):
        def sender(url, payload, **options):
            result = self.sender(url, payload, **options)
            self.store.record = credential('B')
            return result
        self.app.requests.sender = sender
        self.app.action('refresh', {})
        self.join()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1], 'synthetic-access-A')
        self.assertEqual(self.app.cached(self.a), {})
        self.assertEqual(self.app.cached(self.b), {})

    def test_guard_runs_after_rate_limit_wait(self):
        def wait(seconds):
            self.clock.wait(seconds)
            self.store.record = credential('B')
        self.app.requests.wait = wait
        self.app.requests.last_started = self.clock.mono
        self.app.action('refresh', {})
        self.join()
        self.assertEqual(self.calls, [])

    def test_close_during_query_stops_remaining_requests(self):
        def sender(url, payload, **options):
            self.running = False
            return self.sender(url, payload, **options)
        self.app.requests.sender = sender
        self.app.action('refresh', {})
        self.join()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.app.cached(self.a), {})

    def test_returned_data_is_discarded_when_login_changes_at_last_request(self):
        def sender(url, payload, **options):
            result = self.sender(url, payload, **options)
            if url in quota.MODEL_URLS:
                self.store.record = credential('B')
            return result
        self.app.requests.sender = sender
        self.app.action('refresh', {})
        self.join()
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.app.cached(self.a), {})

    def test_access_update_between_requests_uses_latest_official_token(self):
        def sender(url, payload, **options):
            result = self.sender(url, payload, **options)
            self.store.record = updated_record('A', 'synthetic-official-next')
            return result
        self.app.requests.sender = sender
        self.app.action('refresh', {})
        self.join()
        self.assertEqual(self.calls[0][1], 'synthetic-access-A')
        self.assertEqual({access for _, access in self.calls[1:]}, {'synthetic-official-next'})

    def test_expiry_waits_for_official_update_without_token_endpoint(self):
        self.store.record = updated_record('A', 'synthetic-expired', expired=True)
        self.app.action('refresh', {})
        self.join()
        self.assertEqual(self.calls, [])
        self.assertIsNotNone(self.app.session.blocked_token)
        self.clock.advance(5 * 3600)
        self.app.scheduler_tick()
        self.assertEqual(self.calls, [])
        self.store.record = updated_record('A', 'synthetic-official-renewed')
        self.app.scheduler_tick()
        self.clock.advance(6)
        self.app.scheduler_tick()
        self.join()
        self.assertTrue(self.calls)
        self.assertEqual({access for _, access in self.calls}, {'synthetic-official-renewed'})

    def test_http401_does_not_refresh_or_retry_until_official_changes(self):
        def rejected(url, payload, **options):
            self.calls.append((url, options.get('access')))
            raise quota.QuotaError('synthetic-rejected', 401)
        self.app.requests.sender = rejected
        self.app.action('refresh', {})
        self.join()
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.app.cached(self.a)['needs_official_refresh'])
        self.clock.advance(5 * 3600)
        self.app.scheduler_tick()
        self.assertEqual(len(self.calls), 1)

    def test_login_alignment_waits_for_settling_and_runs_once(self):
        self.store.record = credential('B')
        self.app.scheduler_tick()
        self.assertEqual(self.calls, [])
        self.clock.advance(6)
        self.app.scheduler_tick()
        self.join()
        self.assertEqual({access for _, access in self.calls}, {'synthetic-access-B'})
        count = len(self.calls)
        self.clock.advance(40)
        self.app.scheduler_tick()
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.app.cached(self.a), {})

    def test_inactive_reset_deadline_does_not_trigger_query(self):
        now = self.clock.wall
        cache = {'updated': now - 100, 'groups': [{'family': 'gemini', 'window': '5h',
                 'percentage': 35, 'reset': datetime.fromtimestamp(now - 1, timezone.utc).isoformat()}]}
        self.app.vault.write(self.b + '.quota', cache)
        self.app.scheduler_tick()
        self.assertEqual(self.calls, [])
        public = next(p for p in self.app.state()['profiles'] if p['id'] == self.b)['quota']
        self.assertEqual(public['groups'][0]['percentage'], 100)
        self.assertTrue(public['groups'][0]['estimated'])
        self.assertEqual(self.app.cached(self.b), cache)

    def test_direct_batch_start_is_rejected(self):
        with self.assertRaises(core.LocalError):
            self.app.start_refresh([self.a, self.b])
        self.assertEqual(self.calls, [])

    def test_final_official_update_is_captured_after_client_exits(self):
        final = updated_record('A', 'synthetic-exit-token')
        store = self.store
        vault = self.app.vault
        def close():
            store.record = final
        switcher = core.Switcher(store, vault)
        with patch.object(core, 'close_antigravity', side_effect=close), patch.object(core, 'executable_path', return_value=Path('synthetic.exe')), patch.object(core, 'replace_verified'), patch.object(core, 'launch'):
            switcher.switch(self.b)
        self.assertEqual(vault.load(self.a)['credential'], final)

    def test_logout_never_overwrites_saved_snapshot_with_empty_credentials(self):
        previous = (self.app.directory / self.a).read_bytes()
        self.store.record = None
        self.app.scheduler_tick()
        self.assertEqual((self.app.directory / self.a).read_bytes(), previous)
        self.assertEqual(self.calls, [])

    def test_public_state_never_contains_official_tokens(self):
        text = json.dumps(self.app.state())
        self.assertNotIn('synthetic-access', text)
        self.assertNotIn('synthetic-refresh', text)
        self.assertNotIn('blocked_token', text)


class OfflineProjectionTests(unittest.TestCase):
    def setUp(self):
        self.now = float(int(time.time()))
        self.cache = {'updated': self.now, 'groups': [
            {'family': 'gemini', 'window': '5h', 'percentage': 35,
             'reset': datetime.fromtimestamp(self.now + 3600, timezone.utc).isoformat()},
            {'family': 'gemini', 'window': 'weekly', 'percentage': 17,
             'reset': datetime.fromtimestamp(self.now + 7 * 86400, timezone.utc).isoformat()}]}

    def test_user_example_35_becomes_estimated_100_at_known_reset(self):
        original = copy.deepcopy(self.cache)
        before = quota_projection.project(self.cache, self.now + 3599, True)
        after = quota_projection.project(self.cache, self.now + 3600, True)
        self.assertEqual(before['groups'][0]['percentage'], 35)
        self.assertFalse(before['has_estimates'])
        self.assertEqual(after['groups'][0]['percentage'], 100)
        self.assertEqual(after['groups'][0]['confirmed_percentage'], 35)
        self.assertTrue(after['groups'][0]['estimated'])
        self.assertEqual(after['updated'], self.now)
        self.assertEqual(self.cache, original)

    def test_weekly_and_five_hour_are_independent(self):
        result = quota_projection.project(self.cache, self.now + 3601, True)
        self.assertEqual([r['percentage'] for r in result['groups']], [100, 17])
        result = quota_projection.project(self.cache, self.now + 7 * 86400, True)
        self.assertEqual([r['percentage'] for r in result['groups']], [100, 100])

    def test_online_account_is_not_reported_as_confirmed_100_by_clock(self):
        result = quota_projection.project(self.cache, self.now + 8 * 86400, False)
        self.assertEqual([r['percentage'] for r in result['groups']], [35, 17])
        self.assertFalse(result['has_estimates'])

    def test_missing_unknown_or_invalid_reset_does_not_invent_full_quota(self):
        for reset in ['', 'not-a-date', None]:
            self.cache['groups'][0]['reset'] = reset
            result = quota_projection.project(self.cache, self.now + 3601, True)
            self.assertEqual(result['groups'][0]['percentage'], 35)
        self.cache['groups'][0]['reset'] = datetime.fromtimestamp(self.now + 3600, timezone.utc).isoformat()
        self.cache['groups'][0]['percentage'] = None
        self.assertIsNone(quota_projection.project(self.cache, self.now + 3601, True)['groups'][0]['percentage'])

    def test_reset_already_covered_by_confirmation_is_not_applied_twice(self):
        self.cache['updated'] = self.now + 3601
        result = quota_projection.project(self.cache, self.now + 7200, True)
        self.assertEqual(result['groups'][0]['percentage'], 35)
        self.assertFalse(result['has_estimates'])

    def test_new_real_result_replaces_estimate_even_if_less_than_100(self):
        estimated = quota_projection.project(self.cache, self.now + 3601, True)
        self.assertEqual(estimated['groups'][0]['percentage'], 100)
        self.cache['updated'] = self.now + 3602
        self.cache['groups'][0]['percentage'] = 73
        actual = quota_projection.project(self.cache, self.now + 3603, False)
        self.assertEqual(actual['groups'][0]['percentage'], 73)
        self.assertFalse(actual['has_estimates'])
