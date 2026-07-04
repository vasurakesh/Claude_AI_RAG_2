"""
Development settings. Activate with:
    set DJANGO_SETTINGS_MODULE=config.settings.dev   (Windows cmd)
    $env:DJANGO_SETTINGS_MODULE="config.settings.dev" (PowerShell)
or pass --settings=config.settings.dev to manage.py.
"""

from .base import *  # noqa: F401,F403
from .base import LOGGING, LOG_DIR

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Verbose console logging while developing locally (but keep raw SQL query
# spam off by default - set django.db.backends to DEBUG yourself if you need it)
LOGGING["loggers"]["django"]["level"] = "DEBUG"
LOGGING["root"]["level"] = "DEBUG"

# Ensure local runtime directories exist for development convenience
for _dir in (LOG_DIR,):
    _dir.mkdir(parents=True, exist_ok=True)

# Django Debug Toolbar / other dev-only tooling can be wired in here later.
