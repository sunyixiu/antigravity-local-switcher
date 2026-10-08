import base64
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

directory = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(directory))
import quota


def credential(expired=False):
    data = {'token': {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh',
                      'expiry_timestamp': time.time() + (-100 if expired else 3600)}}
    return {'blob': base64.b64encode(json.dumps(data).encode()).decode(), 'username': 'test',
            'comment': None, 'persist': 2}


def response():
    return {'models': {
        'gemini-pro': {'quotaInfo': {'remainingFraction': .7, 'resetTime': '2026-10-07T15:00:00Z'}},
        'gemini-flash': {'quotaInfo': {'remainingFraction': .25}},
        'claude-model': {'quotaInfo': {'resetTime': '2026-10-07T16:00:00Z'}},
    }}


def group_response():
    return {'groups': [
        {'displayName': 'Gemini Models', 'buckets': [
            {'bucketId': 'gemini_weekly', 'window': '7d', 'remainingFraction': .06, 'resetTime': '2026-10-09T14:00:00Z'},
            {'bucketId': 'gemini_5h', 'window': 'PT5H', 'remainingFraction': .284},
        ]},
        {'displayName': 'Claude and GPT models', 'buckets': [
            {'bucketId': '3p_weekly', 'window': 'WEEKLY', 'remainingFraction': .164},
            {'bucketId': '3p_5h', 'window': '5h', 'remainingFraction': 1},
        ]},
    ]}


class QuotaTests(unittest.TestCase):
    def setUp(self):
        config = patch.object(quota, "local_client_config", return_value=("synthetic.apps.googleusercontent.com", "synthetic-client-config"))
        config.start()
        self.addCleanup(config.stop)

    def test_missing_fraction_unknown_and_budgets_not_added(self):
        rows = quota.parse_models(response())
        self.assertIsNone(next(row for row in rows if row['id'] == 'claude-model')['percentage'])
        self.assertEqual(quota.summary({'models': rows}, 'gemini'), '25%')
        self.assertEqual(quota.summary({'models': rows}, 'claude'), '未知')
        self.assertEqual(quota.reset_display('2026-10-07T15:00:00Z'), '10-07 23:00')

    def test_invalid_fraction_not_reported_as_zero(self):
        for value in [True, float('nan'), -1, 1.1, '0.5', None]:
            result = quota.parse_models({'models': {'gemini-test': {'quotaInfo': {'remainingFraction': value}}}})
            self.assertIsNone(result[0]['percentage'])

    def test_valid_access_does_not_refresh_or_touch_credentials(self):
        calls = []
        saved = []
        def request(url, payload, **kwargs):
            calls.append(url)
            return {'cloudaicompanionProject': 'test-project'} if url == quota.CONTEXT_URL else response()
        quota.query(credential(), request, saved.append)
        self.assertEqual(calls, [quota.CONTEXT_URL, quota.GROUP_URLS[0], quota.MODEL_URLS[0]])
        self.assertEqual(saved, [])

    def test_expired_token_waits_for_official_client_without_network_or_renewal(self):
        saved = []
        with self.assertRaises(quota.OfficialRefreshRequired):
            quota.query(credential(True), lambda *a, **k: self.fail('Expired token must not reach Google'), saved.append)
        self.assertEqual(saved, [])

    def test_unauthorized_waits_for_official_client_without_oauth_retry(self):
        calls = []
        def request(url, payload, **kwargs):
            calls.append(url)
            raise quota.QuotaError('Expired', 401)
        with self.assertRaises(quota.OfficialRefreshRequired):
            quota.query(credential(), request)
        self.assertEqual(calls, [quota.CONTEXT_URL])
        self.assertNotIn(quota.TOKEN_URL, calls)

    def test_project_forbidden_retries_without_project(self):
        payloads = []
        def request(url, payload, **kwargs):
            if url == quota.CONTEXT_URL:
                return {'cloudaicompanionProject': 'synthetic-project'}
            payloads.append(payload)
            if payload:
                raise quota.QuotaError('Forbidden', 403)
            return response()
        self.assertTrue(quota.query(credential(), request)['models'])
        self.assertEqual(payloads, [{'project': 'synthetic-project'}, {}, {'project': 'synthetic-project'}, {}])

    def test_screenshot_windows_are_independent_from_model_minima(self):
        def request(url, payload, **kwargs):
            if url == quota.CONTEXT_URL:
                return {}
            return group_response() if url in quota.GROUP_URLS else response()
        result = quota.query(credential(), request)
        actual = [quota.window_summary(result, family, window) for family, window in
                  [('gemini', 'weekly'), ('gemini', '5h'), ('thirdparty', 'weekly'), ('thirdparty', '5h')]]
        self.assertEqual(actual, ['6%', '28%', '16%', '100%'])
        self.assertEqual(quota.summary(result, 'gemini'), '25%')

    def test_missing_weekly_is_unknown_never_model_fallback(self):
        result = {'models': quota.parse_models(response()), 'groups': []}
        self.assertEqual(quota.window_summary(result, 'gemini', 'weekly'), '未知')
        self.assertEqual(quota.window_summary(result, 'thirdparty', '5h'), '未知')

    def test_bucket_family_metadata_overrides_ambiguous_group(self):
        rows = quota.parse_groups({'groups': [{'displayName': 'Gemini and Claude', 'buckets': [
            {'bucketId': '3p_weekly', 'window': '7d', 'remainingFraction': 0},
            {'bucketId': 'unknown_5h', 'window': '5h', 'remainingFraction': .5},
        ]}]})
        self.assertEqual(rows[0]['family'], 'thirdparty')
        self.assertEqual(rows[0]['window'], 'weekly')
        self.assertIsNone(rows[1]['family'])
        self.assertEqual(quota.window_summary({'groups': rows}, 'thirdparty', 'weekly'), '0%')

    def test_summary_succeeds_when_model_endpoint_unavailable(self):
        def request(url, payload, **kwargs):
            if url == quota.CONTEXT_URL:
                return {}
            if url in quota.GROUP_URLS:
                return group_response()
            raise quota.QuotaError('Unavailable', 503)
        result = quota.query(credential(), request)
        self.assertEqual(result['models'], [])
        self.assertEqual(quota.window_summary(result, 'gemini', 'weekly'), '6%')
        self.assertIsNotNone(result['model_error'])

    def test_summary_forbidden_does_not_discard_model_quota(self):
        def request(url, payload, **kwargs):
            if url == quota.CONTEXT_URL:
                return {}
            if url in quota.GROUP_URLS:
                raise quota.QuotaError('Forbidden', 403)
            return response()
        result = quota.query(credential(), request)
        self.assertEqual(result['groups'], [])
        self.assertTrue(result['models'])
        self.assertEqual(result['status'], '周/5小时未获取')
        self.assertEqual(quota.window_summary(result, 'gemini', 'weekly'), '未知')

    def test_summary_fallback_does_not_repeat_throttled_requests(self):
        calls = []
        def request(url, payload, **kwargs):
            calls.append(url)
            if url == quota.CONTEXT_URL:
                return {}
            if url == quota.GROUP_URLS[0]:
                raise quota.QuotaError('Missing', 404)
            if url == quota.GROUP_URLS[1]:
                raise quota.QuotaError('Throttled', 429)
            return response()
        result = quota.query(credential(), request)
        self.assertNotIn(quota.GROUP_URLS[2], calls)
        self.assertTrue(result['models'])

    def test_other_audience_does_not_send_refresh_token(self):
        claims = base64.urlsafe_b64encode(json.dumps({'aud': 'other.apps.googleusercontent.com'}).encode()).decode().rstrip('=')
        record = credential(True)
        value, token, _ = quota.decode(record)
        token['id_token'] = 'x.' + claims + '.y'
        record['blob'] = base64.b64encode(json.dumps(value).encode()).decode()
        def request(*args, **kwargs):
            raise AssertionError('A mismatched refresh must not send a request')
        with self.assertRaises(quota.QuotaError):
            quota.query(record, request)

    def test_non_google_destination_rejected_before_network(self):
        with patch.object(quota.urllib.request, 'build_opener', side_effect=AssertionError('Network must not be reached')):
            with self.assertRaises(quota.QuotaError):
                quota.post('https://example.com/token', {'refresh_token': 'synthetic'})
        req = quota.urllib.request.Request(quota.TOKEN_URL)
        self.assertIsNone(quota.NoRedirect().redirect_request(req, None, 302, '', {}, 'https://example.com/'))


if __name__ == '__main__':
    unittest.main()
