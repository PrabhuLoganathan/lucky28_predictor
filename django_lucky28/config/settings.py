from pathlib import Path
import sys
import os
from dotenv import load_dotenv
from datetime import datetime, timezone as datetime_timezone

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / '.env')
LOGGER_TOKEN_FILE = PROJECT_ROOT / '.local' / 'logger-token'
LOGGER_API_TOKEN = os.environ.get('LUCKY28_LOGGER_TOKEN', '')

# Add 'apps' to sys.path
sys.path.append(str(BASE_DIR / 'apps'))

SECRET_KEY = 'lucky28-temp-key'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'gameapp',
    'rest_framework',
    'games',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(PROJECT_ROOT / os.environ.get('LUCKY28_DB_PATH', 'lucky28.db')),
        # Acquire the write reservation before an atomic block reads state.
        # Deferred read-to-write upgrades can fail immediately when the worker
        # and a dashboard request reconcile alert state concurrently.
        'OPTIONS': {'transaction_mode': 'IMMEDIATE', 'timeout': 20},
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Alerts are evaluated locally; outbound delivery is an explicit opt-in.
SERVER_SESSION_STARTED_AT = datetime.now(datetime_timezone.utc)
ALERT_TELEGRAM_ENABLED = os.environ.get('ALERT_TELEGRAM_ENABLED', '').lower() == 'true'
ALERT_TELEGRAM_BOT_TOKEN = os.environ.get('ALERT_TELEGRAM_BOT_TOKEN', '')
ALERT_STATE_DIR = Path(os.environ.get('ALERT_STATE_DIR', str(PROJECT_ROOT / '.local' / 'alerts')))
ALERT_MAX_EVENT_AGE_SECONDS = 120
ALERT_HISTORY_LIMIT = 1002
ALERT_COLLECTION_TIMEOUT_MINUTES = 3

# Optional externally reachable origin for links in group absence notifications.
ALERT_PUBLIC_BASE_URL = os.environ.get('ALERT_PUBLIC_BASE_URL', '')
