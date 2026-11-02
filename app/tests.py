from django.test import TestCase


class ViewTest(TestCase):
    """Tests for the application views."""

    def test_home(self):
        """The home page serves the viewer."""
        response = self.client.get('/')
        self.assertContains(response, 'RADIENT 3D VIEWER', status_code=200)
