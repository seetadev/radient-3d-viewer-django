from django.contrib.staticfiles import finders
from django.test import TestCase

MODELS = ['spacesuit', 'lamborghini', 'leeperrysmith', 'factory', 'elephant']


class ViewTest(TestCase):
    """Tests for the application views."""

    def test_home(self):
        """The home page serves the viewer as an ES module with an import map."""
        response = self.client.get('/')
        self.assertContains(response, 'RADIENT 3D VIEWER', status_code=200)
        self.assertContains(response, 'type="importmap"')
        self.assertContains(response, 'type="module" src="/static/app.js"')
        self.assertContains(response, 'data-models-url="/static/models/"')

    def test_model_buttons_match_models(self):
        response = self.client.get('/')
        for name in MODELS:
            self.assertContains(response, '>%s</button>' % name)


class AssetTest(TestCase):
    """The viewer's JS, vendored libs and GLB models must be resolvable as static files."""

    def test_viewer_assets_exist(self):
        paths = ['app.js', 'vendor/three/build/three.module.js', 'vendor/three/build/three.core.js',
                 'vendor/three/addons/loaders/GLTFLoader.js', 'vendor/bootstrap/bootstrap.min.css',
                 'cubemap/px.jpg'] + ['models/%s.glb' % m for m in MODELS]
        for p in paths:
            self.assertIsNotNone(finders.find(p), 'missing static file: ' + p)

    def test_models_are_glb(self):
        for m in MODELS:
            with open(finders.find('models/%s.glb' % m), 'rb') as f:
                self.assertEqual(f.read(4), b'glTF', m)
