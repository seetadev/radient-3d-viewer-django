"""Security regression tests: env-driven settings, fail-closed startup, headers/CSP, HTTPS-only, check --deploy."""
import os
import re
import subprocess
import sys
from pathlib import Path

from django.test import Client, TestCase, override_settings

ROOT = Path(__file__).resolve().parent.parent
STRONG_KEY = 'k7#Qz!p2Vw9xLr4sTn8^bYd3Hc6Jf1Mg5Ua0Ze7Wo2Xi9Pt4Rl8Sv3Nq6Dy1Bm'  # >=50 chars, many unique


def run_settings(code, **env):
    """Import settings in a fresh interpreter with exactly the given environment."""
    base = {'PATH': os.environ['PATH'], 'DJANGO_SETTINGS_MODULE': 'Radient_Django.settings'}
    base.update({k: v for k, v in env.items() if v is not None})
    return subprocess.run([sys.executable, '-c', 'import django.conf as c; s=c.settings; ' + code],
                          cwd=ROOT, env=base, capture_output=True, text=True)


class EnvSettingsTest(TestCase):
    def test_debug_is_off_by_default(self):
        r = run_settings('print(s.DEBUG)', DJANGO_SECRET_KEY=STRONG_KEY, DJANGO_ALLOWED_HOSTS='viewer.example.org')
        self.assertEqual(r.stdout.strip(), 'False', r.stderr)

    def test_refuses_to_start_in_production_without_allowed_hosts(self):
        r = run_settings('s.ALLOWED_HOSTS', DJANGO_SECRET_KEY=STRONG_KEY)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_ALLOWED_HOSTS is required', r.stderr)

    def test_refuses_to_start_without_or_with_blank_secret_key(self):
        for key in (None, '', '   '):
            r = run_settings('s.SECRET_KEY', DJANGO_SECRET_KEY=key, DJANGO_ALLOWED_HOSTS='viewer.example.org')
            self.assertNotEqual(r.returncode, 0, repr(key))
            self.assertIn('DJANGO_SECRET_KEY is required', r.stderr)

    def test_debug_mode_defaults_to_local_hosts_and_no_https_enforcement(self):
        r = run_settings('print(s.DEBUG, s.ALLOWED_HOSTS, s.SECURE_SSL_REDIRECT)', DJANGO_SECRET_KEY='x', DJANGO_DEBUG='1')
        self.assertEqual(r.stdout.strip(), "True ['localhost', '127.0.0.1', '[::1]'] False", r.stderr)

    def test_wildcard_is_not_a_default(self):
        r = run_settings('print(s.ALLOWED_HOSTS)', DJANGO_SECRET_KEY='x', DJANGO_DEBUG='1')
        self.assertNotIn('*', r.stdout)

    def test_production_defaults_enable_https_only(self):
        r = run_settings('print(s.SECURE_SSL_REDIRECT, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_HSTS_SECONDS)',
                         DJANGO_SECRET_KEY=STRONG_KEY, DJANGO_ALLOWED_HOSTS='viewer.example.org')
        self.assertEqual(r.stdout.strip(), 'True True True 31536000', r.stderr)

    def test_proxy_ssl_header_is_only_trusted_when_opted_in(self):
        base = dict(DJANGO_SECRET_KEY=STRONG_KEY, DJANGO_ALLOWED_HOSTS='viewer.example.org')
        self.assertEqual(run_settings('print(s.SECURE_PROXY_SSL_HEADER)', **base).stdout.strip(), 'None')
        self.assertIn('X_FORWARDED_PROTO', run_settings('print(s.SECURE_PROXY_SSL_HEADER)', DJANGO_TRUST_PROXY_SSL='1', **base).stdout)

    def test_check_deploy_is_clean(self):
        env = {'PATH': os.environ['PATH'], 'DJANGO_SECRET_KEY': STRONG_KEY, 'DJANGO_ALLOWED_HOSTS': 'viewer.example.org',
               'DJANGO_TRUST_PROXY_SSL': '1'}
        r = subprocess.run([sys.executable, 'manage.py', 'check', '--deploy', '--fail-level', 'WARNING'],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('no issues', r.stdout)


class HeadersTest(TestCase):
    def test_security_headers_on_page(self):
        r = self.client.get('/')
        self.assertEqual(r['X-Frame-Options'], 'DENY')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(r['Referrer-Policy'], 'no-referrer')
        self.assertEqual(r['Cross-Origin-Opener-Policy'], 'same-origin')

    def test_page_csp_is_strict_and_nonce_matches_import_map(self):
        nonces = []
        for _ in range(2):
            r = self.client.get('/')
            csp = r['Content-Security-Policy']
            self.assertNotIn('unsafe-inline', csp)
            self.assertNotIn('unsafe-eval', csp)
            self.assertNotIn('*', csp)
            for d in ("default-src 'none'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'"):
                self.assertIn(d, csp)
            nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
            self.assertIn('<script type="importmap" nonce="%s">' % nonce, r.content.decode())
            nonces.append(nonce)
        self.assertNotEqual(nonces[0], nonces[1])

    def test_no_inline_handlers_and_only_the_import_map_is_inline(self):
        body = self.client.get('/').content.decode()
        self.assertIsNone(re.search(r'\son(click|mousedown|change|load)=', body))
        inline = re.findall(r'<script(?![^>]*\ssrc=)[^>]*>', body)
        self.assertEqual(len(inline), 1)
        self.assertIn('importmap', inline[0])

    def test_non_html_responses_get_the_strict_base_policy(self):
        with override_settings(WHITENOISE_USE_FINDERS=True, WHITENOISE_AUTOREFRESH=True):
            r = Client().get('/static/models/spacesuit.glb')
        self.assertEqual(r.status_code, 200)
        self.assertIn("default-src 'none'", r['Content-Security-Policy'])
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        r404 = self.client.get('/nope')
        self.assertIn("frame-ancestors 'none'", r404['Content-Security-Policy'])

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_HSTS_SECONDS=31536000, SECURE_HSTS_INCLUDE_SUBDOMAINS=True)
    def test_https_only_redirects_http_and_sends_hsts(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r['Location'].startswith('https://'))
        r = self.client.get('/', secure=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Strict-Transport-Security'], 'max-age=31536000; includeSubDomains')

    def test_disallowed_host_is_rejected(self):
        self.assertEqual(self.client.get('/', HTTP_HOST='evil.example.com').status_code, 400)
