"""Static serving through Django's real staticfiles handler (live server, raw request paths)."""
import http.client

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, TestCase, override_settings

MODELS = ['spacesuit', 'lamborghini', 'leeperrysmith', 'factory', 'elephant']


class StaticServingTest(StaticLiveServerTestCase):
    def raw_get(self, path):
        # http.client sends the path verbatim (no '..' normalisation), unlike the test client
        c = http.client.HTTPConnection(self.live_server_url.split('//')[1])
        c.request('GET', path)
        r = c.getresponse()
        return r.status, r.read()

    def test_models_served_as_glb(self):
        for m in MODELS:
            status, body = self.raw_get('/static/models/%s.glb' % m)
            self.assertEqual(status, 200, m)
            self.assertEqual(body[:4], b'glTF', m)

    def test_viewer_js_and_vendored_three_served(self):
        for p in ('app.js', 'vendor/three/build/three.module.js', 'vendor/three/build/three.core.js',
                  'vendor/three/addons/loaders/GLTFLoader.js', 'vendor/bootstrap/bootstrap.min.css',
                  'cubemap/px.jpg', 'styles.css', 'custom-slider.css'):
            self.assertEqual(self.raw_get('/static/' + p)[0], 200, p)

    def test_path_traversal_is_blocked(self):
        attempts = ['/static/../manage.py', '/static/%2e%2e/manage.py', '/static/..%2fmanage.py',
                    '/static/../../etc/passwd', '/static/models/../../../manage.py',
                    '/static/....//manage.py', '/static//etc/passwd']
        for path in attempts:
            status, body = self.raw_get(path)
            self.assertNotEqual(status, 200, path)
            self.assertNotIn(b'execute_from_command_line', body, path)   # manage.py content
            self.assertNotIn(b'root:', body, path)                       # /etc/passwd content

    def test_legacy_json_models_and_old_libs_are_gone(self):
        for p in ('spacesuit.js', 'three.min.js', 'jquery-2.2.0.min.js', 'scripts.js'):
            self.assertEqual(self.raw_get('/static/' + p)[0], 404, p)


class WhiteNoiseTest(TestCase):
    """The production image serves static files through WhiteNoise, not runserver."""

    def test_whitenoise_middleware_is_first(self):
        from django.conf import settings
        self.assertEqual(settings.MIDDLEWARE[0], 'whitenoise.middleware.WhiteNoiseMiddleware')

    def test_whitenoise_serves_static_with_debug_off(self):
        with override_settings(DEBUG=False, WHITENOISE_USE_FINDERS=True, WHITENOISE_AUTOREFRESH=True):
            r = Client().get('/static/models/spacesuit.glb')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'model/gltf-binary')

    def test_glb_mimetype_registered_explicitly(self):
        from django.conf import settings
        self.assertEqual(settings.WHITENOISE_MIMETYPES['.glb'], 'model/gltf-binary')
