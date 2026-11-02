"""
Django settings for Radient_Django project.
"""

import os
from os import path

from django.core.exceptions import ImproperlyConfigured

PROJECT_ROOT = path.dirname(path.abspath(path.dirname(__file__)))


def env_bool(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ('1', 'true', 'yes', 'on')


# Secure by default: DEBUG is off unless DJANGO_DEBUG=1 (development only).
DEBUG = env_bool('DJANGO_DEBUG', False)

# Refuse to start in production without an explicit host list.
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()]
if not ALLOWED_HOSTS:
    if DEBUG:
        ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
    else:
        raise ImproperlyConfigured(
            'DJANGO_ALLOWED_HOSTS is required when DJANGO_DEBUG is off '
            '(comma-separated host names, e.g. "viewer.example.org").')

ADMINS = (
    # ('Your Name', 'your_email@example.com'),
)

MANAGERS = ADMINS

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': path.join(PROJECT_ROOT, 'db.sqlite3'),
        'USER': '',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
    }
}

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# On Unix systems, a value of None will cause Django to use the same
# timezone as the operating system.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'America/Chicago'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# If you set this to False, Django will not use timezone-aware datetimes.
USE_TZ = True

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/home/media/media.lawrence.com/media/"
MEDIA_ROOT = ''

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash.
# Examples: "http://media.lawrence.com/media/", "http://example.com/media/"
MEDIA_URL = ''

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/home/media/media.lawrence.com/static/"
STATIC_ROOT = path.join(PROJECT_ROOT, 'staticfiles')

# WhiteNoise serves collected static files (gzip/brotli precompressed at collectstatic time).
# Slim images have no /etc/mime.types, so register the glTF type explicitly.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
WHITENOISE_MIMETYPES = {'.glb': 'model/gltf-binary'}
# Always serve the collected, precompressed files (WhiteNoise would otherwise follow DEBUG and
# bypass them). `runserver` serves static files itself, so development is unaffected.
WHITENOISE_USE_FINDERS = False
WHITENOISE_AUTOREFRESH = False

# URL prefix for static files.
# Example: "http://media.lawrence.com/static/"
STATIC_URL = '/static/'

# Additional locations of static files
STATICFILES_DIRS = [
    # Put strings here, like "/home/html/static" or "C:/www/django/static".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
]

# List of finder classes that know how to find static files in
# various locations.
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
#    'django.contrib.staticfiles.finders.DefaultStorageFinder',
]

# Loaded from the environment. The previous hardcoded key was committed to a
# public repo and must be considered compromised.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '').strip()
if not SECRET_KEY:
    raise ImproperlyConfigured('DJANGO_SECRET_KEY is required (see .env.example).')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'app.middleware.CSPMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# --- HTTP security headers / transport security ---------------------------------------------
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'no-referrer'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'

# Everything below is on by default outside DEBUG. For plain-HTTP local runs of the production
# image (docker compose on localhost) set DJANGO_HTTPS_ONLY=0; never do that in production.
HTTPS_ONLY = env_bool('DJANGO_HTTPS_ONLY', not DEBUG)
SECURE_SSL_REDIRECT = HTTPS_ONLY
SESSION_COOKIE_SECURE = HTTPS_ONLY
CSRF_COOKIE_SECURE = HTTPS_ONLY

# HSTS is opt-in. Browsers remember it for max-age and it cannot be undone remotely, and
# includeSubDomains also forces https on every subdomain, so both are off unless an operator asks.
# Preload is never enabled.
try:
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '').strip() or '0')
except ValueError:
    SECURE_HSTS_SECONDS = -1
if SECURE_HSTS_SECONDS < 0:
    raise ImproperlyConfigured('DJANGO_HSTS_SECONDS must be a non-negative integer.')
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_HSTS_INCLUDE_SUBDOMAINS', False)
SECURE_HSTS_PRELOAD = False
# Only trust X-Forwarded-Proto when explicitly told a TLS-terminating proxy sets it.
if env_bool('DJANGO_TRUST_PROXY_SSL', False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# check --deploy: W021 (preload), W004 (HSTS not set) and W005 (includeSubDomains) are deliberate:
# HSTS/includeSubDomains/preload are irreversible commitments for a domain (some deployments here use
# plain-HTTP subdomains or bare IPs), so they are opt-in. The HTTPS redirect and secure cookies are on.
SILENCED_SYSTEM_CHECKS = ['security.W004', 'security.W005', 'security.W021']

ROOT_URLCONF = 'Radient_Django.urls'

# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = 'Radient_Django.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'app',
]

# A sample logging configuration. The only tangible logging
# performed by this configuration is to send an email to
# the site admins on every HTTP 500 error when DEBUG=False.
# See http://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse'
        }
    },
    'handlers': {
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler'
        }
    },
    'loggers': {
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': True,
        },
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
