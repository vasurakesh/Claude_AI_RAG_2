# Knowledge Management AI Platform

A fully offline, Django-based Retrieval-Augmented Generation (RAG) platform running on
Windows 11 with local Ollama models, local OCR, and a local vector database.
No Docker, no Kubernetes, no cloud services.

This README currently documents **Phase 1: Project setup, virtual environment,
dependencies, and folder structure.** Later phases (models, auth, upload/OCR pipeline,
embeddings, RAG, chat, hardening) will extend this document as they land.

---

## 1. Design decisions (Phase 1)

- **Split settings module** (`config/settings/base.py`, `dev.py`, `prod.py`) instead of a
  single `settings.py`, so dev and production behavior (DEBUG, allowed hosts, security
  headers, log handlers) diverge cleanly without conditional branches in one file.
- **`django-environ`** loads all secrets/config from a `.env` file (see `.env.example`).
  Nothing environment-specific is hardcoded, which matters because the same codebase must
  run on a developer's laptop and later on a production Windows machine.
- **`apps/` package** holds all 11 Django apps from the spec (authentication,
  knowledge_base, document_upload, ocr_engine, embedding_service, vector_search, ai_agent,
  chat, audit_logs, settings_app, dashboard). `ocr` and `settings` were renamed to
  `ocr_engine` and `settings_app` to avoid shadowing Python's stdlib module and Django's own
  `settings` package.
- **`core/` package** holds architecture layers that cut across apps, per the spec's
  Repository/Service pattern requirement:
  - `core/services` — business logic (e.g., `DocumentIndexingService`)
  - `core/repositories` — data-access abstractions over Django ORM (Repository Pattern)
  - `core/ai` — Ollama client wrapper
  - `core/embeddings` — embedding generation + the vector-DB abstraction (so ChromaDB/FAISS
    can be swapped without touching calling code)
  - `core/ocr` — Tesseract/pdf2image wrappers
  - `core/agents` — the AI Agent layer (planning, retrieval, citation, hallucination
    guardrails)
  - `core/prompts` — prompt template definitions
  - `core/utilities` — shared helpers (hashing, text normalization, file validation)
- **SQLite** as specified — no external DB server, works out of the box on Windows.
- **`django-q2`** is queued for Phase 8 background/async processing instead of
  Celery+Redis, since the spec explicitly excludes Docker and the ERP-style
  Redis/Celery stack isn't appropriate for a single-machine Windows deployment.
- Verified end-to-end in this environment: `manage.py check` and `manage.py migrate`
  both run cleanly against SQLite with this settings structure.

## 2. Directory structure

```
kb_platform/
├── manage.py
├── requirements.txt
├── .env.example                # copy to .env
├── .gitignore
├── config/
│   ├── settings/
│   │   ├── base.py             # shared settings
│   │   ├── dev.py               # DEBUG=True, verbose logging
│   │   └── prod.py              # security headers, rotating file logs
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── apps/                        # Django apps (spec: "Django Modules")
│   ├── authentication/
│   ├── knowledge_base/
│   ├── document_upload/
│   ├── ocr_engine/
│   ├── embedding_service/
│   ├── vector_search/
│   ├── ai_agent/
│   ├── chat/
│   ├── audit_logs/
│   ├── settings_app/
│   └── dashboard/
├── core/                        # cross-app architecture layers
│   ├── services/
│   ├── repositories/
│   ├── utilities/
│   ├── prompts/
│   ├── ai/
│   ├── embeddings/
│   ├── ocr/
│   └── agents/
├── apiroutes/                   # DRF routers/serializers aggregation (Phase 6/8)
├── templates/
│   ├── base/
│   ├── authentication/
│   ├── dashboard/
│   ├── chat/
│   ├── knowledge_base/
│   └── partials/
├── static/
│   ├── css/ js/ img/ vendor/    # AdminLTE/Bootstrap assets land here (Phase 3)
├── media/
│   └── documents/
│       ├── originals/           # uploaded source files
│       └── ocr_text/            # extracted/OCR'd text
├── vector_store/                # ChromaDB/FAISS persistence directory
├── logs/                        # application logs (Phase 8)
├── tests/
│   ├── unit/ integration/ ocr/ embedding/ rag/ api/ ui/ performance/
└── docs/                        # architecture docs, diagrams (Phase 8)
```

## 3. Prerequisites (Windows 11)

Install these **before** touching the Python project:

1. **Python 3.12** — https://www.python.org/downloads/windows/
   During install, check "Add python.exe to PATH".
2. **Git for Windows** (optional but recommended) — https://git-scm.com/download/win
3. **Tesseract OCR** — https://github.com/UB-Mannheim/tesseract/wiki
   Install to the default path `C:\Program Files\Tesseract-OCR\`. This matches the
   `TESSERACT_CMD` default in `.env.example`; update it if you install elsewhere.
4. **Poppler for Windows** (required by `pdf2image` to rasterize PDF pages for OCR) —
   https://github.com/oschwartz10612/poppler-windows/releases
   Extract to `C:\poppler\`, so `C:\poppler\Library\bin\pdftoppm.exe` exists. This matches
   the `POPPLER_PATH` default.
5. **Ollama for Windows** — https://ollama.com/download/windows
   After installing, pull the models used by this project:
   ```powershell
   ollama pull nomic-embed-text
   ollama pull qwen3:14b-instruct
   ollama pull llama3.1:8b-instruct
   ```
   (Pull `deepseek-r1` and `qwen2.5-coder` too if you plan to use the reasoning/code model
   options — these are configured from Django Admin in a later phase, not hardcoded.)
   Ollama runs as a background service on `http://127.0.0.1:11434` once installed.

## 4. Installation

Open **PowerShell** in the project folder (the folder containing `manage.py`):

```powershell
# 1. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# If PowerShell blocks the activation script, run once (as the current user):
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 2. Upgrade pip and install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 3. Create your local .env file
copy .env.example .env
# Edit .env if your Tesseract/Poppler paths differ from the defaults, or if you
# want a different default LLM/embedding model.

# 4. Apply migrations (creates db.sqlite3)
python manage.py migrate

# 5. Create an admin user
python manage.py createsuperuser

# 6. Run the development server
python manage.py runserver
```

Visit `http://127.0.0.1:8000/admin/` and log in with the superuser you created.

## 5. How to test Phase 1 before moving to Phase 2

Run these checks from the project root (venv activated):

```powershell
# Confirms settings module loads and no configuration errors exist
python manage.py check

# Confirms SQLite connectivity and that all 11 apps are registered correctly
python manage.py migrate

# Confirms the dev server boots (Ctrl+C to stop)
python manage.py runserver
```

Expected results:
- `check` reports `System check identified no issues (0 silenced).`
- `migrate` creates `db.sqlite3` and applies Django's built-in auth/session/admin
  migrations without errors (no app-specific models exist yet — that's Phase 2).
- The dev server starts and `http://127.0.0.1:8000/admin/` renders the default Django
  admin login page.

Once you confirm all three, Phase 2 (database schema, models for documents/chunks/
embeddings/conversations, and migrations) can build directly on this skeleton.

## 6. Required commands reference

| Purpose | Command |
|---|---|
| Activate venv | `.\venv\Scripts\Activate.ps1` |
| Install deps | `pip install -r requirements.txt` |
| Check config | `python manage.py check` |
| Migrate DB | `python manage.py migrate` |
| Create admin | `python manage.py createsuperuser` |
| Run server | `python manage.py runserver` |
| Make migrations (Phase 2+) | `python manage.py makemigrations` |
| Run tests (Phase 8+) | `pytest` |
"# Claude_AI_RAG_2" 
