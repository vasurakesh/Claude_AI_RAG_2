"""
Base settings for the Knowledge Management AI Platform.
Shared across all environments (dev / prod). Do not put secrets here directly -
use environment variables (.env file, loaded via django-environ).
"""

from pathlib import Path
import environ

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# config/settings/base.py -> parents[2] == project root (where manage.py lives)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
env = environ.Env(
    DEBUG=(bool, False),
)
# Reads a .env file placed at the project root (BASE_DIR/.env)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-change-me-in-prod")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    # "django_htmx",   # enabled in Phase 3 (AdminLTE + HTMX integration)
    "rest_framework",
]

LOCAL_APPS = [
    "apps.authentication",
    "apps.knowledge_base",
    "apps.document_upload",
    "apps.ocr_engine",
    "apps.embedding_service",
    "apps.vector_search",
    "apps.ai_agent",
    "apps.chat",
    "apps.audit_logs",
    "apps.settings_app",
    "apps.dashboard",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Phase 3: Session timeout + RBAC
    "apps.authentication.middleware.SessionActivityMiddleware",
    "apps.authentication.middleware.RBACMiddleware",
    # Phase 8: Audit logging middleware added here
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database - SQLite (per spec: no external DB server, fully offline)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Where uploaded source documents and generated artifacts live, under MEDIA_ROOT
DOCUMENT_UPLOAD_SUBDIR = "documents/originals"
OCR_OUTPUT_SUBDIR = "documents/ocr_text"

# ---------------------------------------------------------------------------
# Session security (spec: Session Timeout)
# ---------------------------------------------------------------------------
SESSION_COOKIE_AGE = env.int("SESSION_TIMEOUT_SECONDS", default=1800)  # 30 minutes
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True

# ---------------------------------------------------------------------------
# File upload limits (spec: Upload Limits / Maximum Upload Size)
# Administrator can override the effective value via Django Admin -> Settings app;
# this is only the hard framework-level ceiling.
# ---------------------------------------------------------------------------
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int("DATA_UPLOAD_MAX_MEMORY_SIZE", default=1024 * 1024 * 50)  # 50 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int("FILE_UPLOAD_MAX_MEMORY_SIZE", default=1024 * 1024 * 50)

ALLOWED_UPLOAD_EXTENSIONS = [
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt", ".html",
    ".rtf", ".pptx", ".zip", ".png", ".jpg", ".jpeg", ".tiff",
]

# ---------------------------------------------------------------------------
# Ollama / AI configuration defaults (overridable from Django Admin in later phases)
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", default="http://127.0.0.1:11434")
DEFAULT_EMBEDDING_MODEL = env("DEFAULT_EMBEDDING_MODEL", default="nomic-embed-text")
DEFAULT_LLM_MODEL = env("DEFAULT_LLM_MODEL", default="qwen3:14b-instruct")

# ---------------------------------------------------------------------------
# Vector database configuration
# ---------------------------------------------------------------------------
VECTOR_DB_BACKEND = env("VECTOR_DB_BACKEND", default="chromadb")  # "chromadb" or "faiss"
VECTOR_DB_PERSIST_DIR = str(BASE_DIR / "vector_store")

# ---------------------------------------------------------------------------
# OCR configuration (Tesseract on Windows requires an explicit path)
# ---------------------------------------------------------------------------
TESSERACT_CMD = env(
    "TESSERACT_CMD",
    default=r"C:\Program Files\Tesseract-OCR\tesseract.exe",
)
POPPLER_PATH = env("POPPLER_PATH", default=r"C:\poppler\Library\bin")

# ---------------------------------------------------------------------------
# Chunking defaults (Administrator-configurable overrides live in Settings app)
# ---------------------------------------------------------------------------
DEFAULT_CHUNK_SIZE_TOKENS = env.int("DEFAULT_CHUNK_SIZE_TOKENS", default=1024)
DEFAULT_CHUNK_OVERLAP_TOKENS = env.int("DEFAULT_CHUNK_OVERLAP_TOKENS", default=150)
DEFAULT_CHUNKING_STRATEGY = env("DEFAULT_CHUNKING_STRATEGY", default="recursive")

# ---------------------------------------------------------------------------
# Logging (spec: Uploads/OCR/Embedding/Search/LLM Calls/Errors/User Activity)
# File handlers are finalized in Phase 8; console logging is active from Phase 1.
# ---------------------------------------------------------------------------
LOG_DIR = BASE_DIR / "logs"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} — {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # Silences the SQL-query-per-line spam under DEBUG; flip to "DEBUG" locally
        # in dev.py (or here) when you actually need to see raw SQL.
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

LOGIN_URL = "authentication:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "authentication:login"

# ---------------------------------------------------------------------------
# Django REST Framework (Phase 7)
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "200/hour",
    },
}
