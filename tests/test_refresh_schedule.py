import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auto_refresh
import desktop_ui
import local_switcher as core
import quota
import refresh_policy
from test_capture_lifecycle import SyntheticStore, SyntheticSwitcher, credential
from test_quota import group_response, response
from synthetic_storage import SyntheticProtector


class Clock:
    def __init__(self):
        self.mono = 100.0
        self.wall = time.time()
        self.waits = []

    def wait(self, seconds):
        self.waits.append(seconds)
        self.mono += seconds
        self.wall += seconds

    def advance(self, seconds):
        self.mono += seconds
        self.wall += seconds


class RefreshScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.temp.name)
        self.clock = Clock()
        self.calls = []
        self.native = SyntheticStore()
        self.running = True
        self.app = desktop_ui.Application(directory=self.directory, store=self.native,
                                          running_check=lambda: self.running, request_sender=self.sender, clock=lambda: self.clock.mono,
                                          wall_clock=lambda: self.clock.wall, wait=self.clock.wait)
        self.app.vault.protector = SyntheticProtector()
        self.app.switcher = SyntheticSwitcher()
        self.a = self.app.vault.save('Synthetic A', credential('A'))
        self.b = self.app.vault.save('Synthetic B', credential('B'))
        self.app.eligible_login()
        self.app.session.pending = None

    def tearDown(self):
        self.join_job()
        self.temp.cleanup()

    def sender(self, url, payload, **options):
        self.calls.append((self.clock.mono, url, options.get('access')))
        if url == quota.CONTEXT_URL:
            return {}
        return group_response() if url in quota.GROUP_URLS else response()

    def join_job(self):
        deadline = time.monotonic() + 3
        while self.app.busy and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(self.app.busy, 'Synthetic refresh did not finish')

    def cache_with_due_reset(self):
        return {'groups': [{'family': 'gemini', 'window': '5h', 'percentage': 22,
                            'reset': datetime.fromtimestamp(self.clock.wall + 60, timezone.utc).isoformat()}],
                'models': [], 'updated': self.clock.wall, 'status': '已更新'}

    def test_single_refresh_reads_only_actual_current_login(self):
        untouched = (self.directory / self.b).read_bytes()
        self.app.action('refresh-one', {'id': self.a})
        self.join_job()
        self.assertTrue(self.calls)
        self.assertEqual({access for _, _, access in self.calls}, {'synthetic-access-A'})
        self.assertTrue(self.app.cached(self.a)['groups'])
        self.assertEqual(self.app.cached(self.b), {})
        self.assertEqual((self.directory / self.b).read_bytes(), untouched)
        self.assertGreater(self.native.reads, 0)

    def test_refresh_legacy_route_now_queries_only_current_account(self):
        self.app.action('refresh', {})
        self.join_job()
        self.assertEqual(len(self.calls), 3)
        starts = [entry[0] for entry in self.calls]
        self.assertTrue(all(right - left >= refresh_policy.REQUEST_INTERVAL for left, right in zip(starts, starts[1:])))
        self.assertEqual({access for _, _, access in self.calls}, {'synthetic-access-A'})
        self.assertEqual(self.app.cached(self.b), {})

    def test_repeat_single_refresh_respects_cooldown(self):
        self.app.action('refresh-one', {'id': self.a})
        self.join_job()
        count = len(self.calls)
        with self.assertRaises(core.LocalError):
            self.app.action('refresh-one', {'id': self.a})
        self.assertEqual(len(self.calls), count)
        self.clock.advance(30)
        self.app.action('refresh-one', {'id': self.a})
        self.join_job()
        self.assertGreater(len(self.calls), count)

    def test_parallel_refresh_job_is_rejected(self):
        entered, release = threading.Event(), threading.Event()
        normal = self.app.requests.sender
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(2)
            return normal(*args, **kwargs)
        self.app.requests.sender = blocked
        self.app.action('refresh-one', {'id': self.a})
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(core.LocalError):
                self.app.action('refresh-one', {'id': self.b})
        finally:
            release.set()

    def test_429_pauses_current_query_and_never_visits_offline_accounts(self):
        self.app.requests.sender = lambda *args, **kwargs: (_ for _ in ()).throw(quota.QuotaError('Synthetic throttle', 429, 120))
        self.app.action('refresh', {})
        self.join_job()
        self.assertEqual(self.app.cached(self.b), {})
        self.assertEqual(self.app.requests.remaining(), 120)
        with self.assertRaises(core.LocalError):
            self.app.action('refresh-one', {'id': self.a})
        self.assertIn('本轮已暂停', self.app.progress)

    def test_default_four_hours_and_three_hour_preference_survive_restart(self):
        self.assertEqual(self.app.auto.hours, 4)
        self.assertAlmostEqual(self.app.auto.next_run - self.clock.wall, 4 * 3600)
        self.app.action('auto-refresh', {'hours': 3})
        again = auto_refresh.Plan(self.directory, lambda: self.clock.wall)
        self.assertEqual(again.hours, 3)
        self.assertEqual(again.next_run, self.app.auto.next_run)

    def test_rate_limit_cooldown_survives_backend_restart(self):
        self.app.requests.sender = lambda *args, **kwargs: (_ for _ in ()).throw(quota.QuotaError('Synthetic throttle', 429, 120))
        self.app.action('refresh-one', {'id': self.a})
        self.join_job()
        again = desktop_ui.Application(directory=self.directory, store=self.native, request_sender=self.sender,
                                      clock=lambda: self.clock.mono, wall_clock=lambda: self.clock.wall, wait=self.clock.wait)
        self.assertEqual(again.requests.remaining(), 120)
        with self.assertRaises(core.LocalError):
            again.action('refresh-one', {'id': self.b})

    def test_disabled_auto_does_not_query_expired_reset(self):
        self.app.action('auto-refresh', {'hours': 0})
        self.app.vault.write(self.a + '.quota', self.cache_with_due_reset())
        self.clock.advance(10 * 3600)
        self.app.scheduler_tick()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.calls, [])
        self.assertEqual(auto_refresh.Plan(self.directory, lambda: self.clock.wall).hours, 0)

    def test_periodic_schedule_runs_once_after_sleep_without_catch_up_burst(self):
        self.clock.advance(24 * 3600)
        self.app.scheduler_tick()
        self.join_job()
        count = len(self.calls)
        self.assertEqual(count, 3)
        self.app.scheduler_tick()
        self.assertFalse(self.app.busy)
        self.assertEqual(len(self.calls), count)
        self.assertGreater(self.app.auto.next_run, self.clock.wall)

    def test_reset_waits_for_grace_and_updates_only_from_query_result(self):
        old = self.cache_with_due_reset()
        self.app.vault.write(self.a + '.quota', old)
        self.clock.advance(65)
        self.app.scheduler_tick()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.cached(self.a)['groups'][0]['percentage'], 22)
        self.assertTrue(auto_refresh.pending_resets(self.app.cached(self.a), self.clock.wall))
        self.clock.advance(26)
        fresh = copy.deepcopy(old)
        fresh['updated'] = self.clock.wall
        fresh['groups'][0]['percentage'] = 55
        with patch.object(desktop_ui.quota, 'query', return_value=fresh):
            self.app.scheduler_tick()
            self.join_job()
        self.assertEqual(self.app.cached(self.a)['groups'][0]['percentage'], 55)
        self.assertEqual(auto_refresh.pending_resets(self.app.cached(self.a), self.clock.wall), [])

    def test_failed_reset_confirmation_retries_after_thirty_minutes(self):
        self.app.vault.write(self.a + '.quota', self.cache_with_due_reset())
        self.clock.advance(91)
        with patch.object(desktop_ui.quota, 'query', side_effect=quota.QuotaError('Synthetic network failure')) as query:
            self.app.scheduler_tick()
            self.join_job()
            self.assertEqual(query.call_count, 1)
            self.clock.advance(31)
            self.app.scheduler_tick()
            self.assertFalse(self.app.busy)
            self.assertEqual(query.call_count, 1)
            self.clock.advance(1800)
            self.app.scheduler_tick()
            self.join_job()
            self.assertEqual(query.call_count, 2)
        self.assertEqual(self.app.cached(self.a)['groups'][0]['percentage'], 22)

    def test_corrupt_preferences_disable_automatic_network(self):
        self.app.auto.path.write_text('{invalid')
        plan = auto_refresh.Plan(self.directory, lambda: self.clock.wall)
        self.assertEqual(plan.hours, 0)
        self.assertIsNotNone(plan.error)

    def test_authorization_failure_pauses_automatic_but_allows_manual_retry(self):
        with patch.object(desktop_ui.quota, 'query', side_effect=quota.QuotaError('Synthetic invalid grant', 400)):
            self.app.action('refresh-one', {'id': self.a})
            self.join_job()
        self.assertTrue(self.app.cached(self.a)['auto_paused'])
        self.clock.advance(5 * 3600)
        with patch.object(self.app, 'start_refresh') as queue:
            self.app.scheduler_tick()
            queue.assert_not_called()
        self.app.action('refresh-one', {'id': self.a})
        self.join_job()
        self.assertFalse(self.app.cached(self.a).get('auto_paused', False))

    def test_invalid_interval_cannot_enable_fast_polling(self):
        for interval in (True, 1, 2, 0.5, 24, '3'):
            with self.assertRaises(core.LocalError):
                self.app.action('auto-refresh', {'hours': interval})
        self.assertEqual(self.app.auto.hours, 4)

    def test_old_running_backend_requires_explicit_upgrade(self):
        server = desktop_ui.create_server(demo=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        path = self.directory / 'instance.json'
        path.write_text(json.dumps({'port': server.server_port, 'instance': server.instance}))
        try:
            with patch.object(desktop_ui, 'VERSION', '0.3'):
                with self.assertRaises(core.LocalError):
                    desktop_ui.existing_url(path, expected_version='0.4')
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=1)

    def test_retry_after_seconds_and_http_date(self):
        self.assertEqual(quota.retry_after_seconds('120'), 120)
        epoch = datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp()
        self.assertEqual(quota.retry_after_seconds('Thu, 08 Oct 2026 00:02:00 GMT', epoch), 120)
        self.assertIsNone(quota.retry_after_seconds('invalid'))


if __name__ == '__main__':
    unittest.main()
