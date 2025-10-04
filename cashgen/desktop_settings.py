"""
Desktop-specific Django settings for CG Price Suggestor
Inherits from main settings and overrides for desktop app use
"""

import os
import sys
from pathlib import Path

# Determine base directories
if getattr(sys, 'frozen', False):
    # Running in PyInstaller bundle
    BASE_DIR = Path(sys._MEIPASS) / 'cashgen'
else:
    # Running in development
    BASE_DIR = Path(__file__).resolve().parent.parent

# Import main settings
from .settings import *

# Desktop app should not be in debug mode
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'  # ✅ pre-collected static files
STATICFILES_DIRS = []  # no need, serving only collected files

# Middleware for desktop app
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'pricing' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# -----------------------------
# Playwright Configuration for Desktop App
# -----------------------------
if getattr(sys, 'frozen', False):
    # Set Playwright browser executable path for PyInstaller
    import os
    playwright_browser_dir = Path(sys._MEIPASS) / 'playwright' / 'driver' / 'package' / '.local-browsers'
    if playwright_browser_dir.exists():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(playwright_browser_dir)
        print(f"Playwright browsers path set to: {playwright_browser_dir}")
    else:
        print(f"Playwright browsers directory not found at: {playwright_browser_dir}")



# Security
SECURE_SSL_REDIRECT = False
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Session
SESSION_COOKIE_AGE = 86400 * 7
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# Disable desktop-irrelevant checks
SILENCED_SYSTEM_CHECKS = [
    'security.W004',
    'security.W008',
    'security.W012',
    'security.W016',
]

# Logging
LOG_DIR = Path.home() / 'CGPriceSuggestor' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file_path = LOG_DIR / 'desktop_app.log'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {'level': 'INFO', 'class': 'logging.FileHandler', 'filename': str(log_file_path)},
        'console': {'level': 'INFO', 'class': 'logging.StreamHandler'},
    },
    'loggers': {
        'django': {'handlers': ['file', 'console'], 'level': 'INFO', 'propagate': True},
        'cashgen': {'handlers': ['file', 'console'], 'level': 'INFO', 'propagate': True},
    },
}

print(f"Desktop settings loaded. BASE_DIR: {BASE_DIR}")
print(f"STATIC_ROOT: {STATIC_ROOT}")
print(f"Database path: {DATABASES['default']['NAME']}")
