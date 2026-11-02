import os
import subprocess
import sys
from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).resolve().parent.parent


class RoutesTest(TestCase):
    def test_home_ok(self):
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_dropped_routes_are_404(self):
        # contact/about/login were dropped (their templates never existed)
        for path in ('/contact', '/about', '/login/', '/logout'):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_unknown_path_404(self):
        self.assertEqual(self.client.get('/nope').status_code, 404)


class SecretKeyTest(TestCase):
    def test_settings_refuse_to_load_without_secret_key(self):
        env = {k: v for k, v in os.environ.items() if k != 'DJANGO_SECRET_KEY'}
        env['DJANGO_SETTINGS_MODULE'] = 'Radient_Django.settings'
        r = subprocess.run([sys.executable, '-c', 'import django.conf; django.conf.settings.SECRET_KEY'],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DJANGO_SECRET_KEY', r.stderr)

    def test_old_leaked_key_not_in_tree(self):
        leaked = 'n(bd1f1c%e8=_xad02x5qtfn'
        for p in ROOT.rglob('*.py'):
            if '.venv' in p.parts or 'node_modules' in p.parts or p == Path(__file__):
                continue
            self.assertNotIn(leaked, p.read_text(errors='ignore'), str(p))
