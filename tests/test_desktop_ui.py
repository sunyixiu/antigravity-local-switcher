import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_ui


class DesktopBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = desktop_ui.create_server(demo=True)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=2)

    def request(self, method, path, body=None, authenticated=True, **headers):
        if authenticated:
            headers.setdefault('X-Local-Switcher', self.server.secret)
            headers.setdefault('Cookie', self.server.cookie_name + '=' + self.server.secret)
        if method == 'POST':
            headers.setdefault('Origin', self.server.origin)
            headers.setdefault('Content-Type', 'application/json')
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, dict(response.headers), response.read()
        connection.close()
        return result

    def test_root_is_private_frame_and_no_remote_assets(self):
        status, headers, body = self.request('GET', '/', authenticated=False)
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
        self.assertNotIn(b'<script src="http', body)
        self.assertNotIn(b'https://', body)

    def test_state_requires_cookie_and_control_header(self):
        self.assertEqual(self.request('GET', '/api/state', authenticated=False)[0], 404)
        self.assertEqual(self.request('GET', '/api/state', authenticated=False,
                                     **{'X-Local-Switcher': self.server.secret})[0], 404)
        self.assertEqual(self.request('GET', '/api/state', authenticated=False,
                                     Cookie=self.server.cookie_name + '=' + self.server.secret)[0], 404)
        status, _, body = self.request('GET', '/api/state')
        self.assertEqual(status, 200)
        value = json.loads(body)
        self.assertTrue(value['demo'])
        self.assertEqual(len(value['profiles']), 4)
        self.assertNotIn('access_token', body.decode())
        self.assertNotIn('refresh_token', body.decode())

    def test_bundled_icons_are_served_without_remote_requests(self):
        for path, signature in [('/favicon.ico', b'\x00\x00\x01\x00'), ('/assets/app-icon.png', b'\x89PNG'), ('/assets/google.svg', b'<svg')]:
            status, headers, body = self.request('GET', path, authenticated=False)
            self.assertEqual(status, 200)
            self.assertIn(signature, body[:100])
            self.assertTrue(headers['Content-Type'].startswith('image/'))
        self.assertEqual(self.request('GET', '/assets/../local_switcher.py', authenticated=False)[0], 404)

    def test_cross_origin_cannot_execute_actions(self):
        self.assertEqual(self.request('POST', '/api/save', '{}', Origin='https://example.com')[0], 403)
        self.assertEqual(self.request('POST', '/api/save', '{}', Origin='null')[0], 403)

    def test_wrong_host_rejected_before_page_or_action(self):
        self.assertEqual(self.request('GET', '/', Host='example.com')[0], 403)
        self.assertEqual(self.request('POST', '/api/save', '{}', Host='example.com')[0], 403)

    def test_foreign_session_and_arbitrary_inputs_rejected(self):
        self.assertEqual(self.request('POST', '/api/save', '{}', Cookie=self.server.cookie_name + '=foreign')[0], 403)
        self.assertEqual(self.request('POST', '/api/save', 'invalid')[0], 400)
        self.assertEqual(self.request('POST', '/api/save', '{"credential":"fake"}')[0], 400)
        self.assertEqual(self.request('POST', '/api/save', '"string"')[0], 400)
        self.assertEqual(self.request('POST', '/api/save', ' ' * 4097)[0], 400)

    def test_demo_never_captures_or_switches_real_credentials(self):
        status, _, body = self.request('POST', '/api/save', '{"label":"Synthetic"}')
        self.assertEqual(status, 400)
        self.assertIn('未接入真实账号', json.loads(body)['error'])
        self.assertFalse(hasattr(self.server.application, 'store'))
        self.assertFalse(hasattr(self.server.application, 'vault'))


if __name__ == '__main__':
    unittest.main()
