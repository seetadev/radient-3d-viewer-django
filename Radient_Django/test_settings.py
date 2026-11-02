"""Settings for the test suite: real settings plus throwaway env values."""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-real-key")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost")

from .settings import *  # noqa: E402,F401,F403

# The test client speaks plain http; the HTTPS-only behaviour is tested explicitly with
# override_settings / subprocesses in tests/test_security.py.
SECURE_SSL_REDIRECT = False
