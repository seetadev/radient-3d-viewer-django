"""Settings for the test suite: real settings plus a throwaway secret key."""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-real-key")

from .settings import *  # noqa: E402,F401,F403
