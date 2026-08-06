# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Meta-Capp is a local-first learning companion for educational PDFs. It renders a PDF as-is
(no reconstruction) and wraps it with an embodied AI assistant ("Gemma") plus a silent
metacognitive engine (cognitive gauges, adaptive questions, flashcards, session memory).
All LLM inference is local via **Ollama** (`gemma4:e4b`, see `config/settings.py:OLLAMA_MODEL`) —
no API keys, graceful degradation when offline.

The project is mid-migration from a **Tkinter desktop UI** to a **web UI** (FastAPI backend +
React/Vite frontend, embedded in a native `pywebview` window) using a strangler pattern. Both
UIs coexist; the shared business logic lives in `nwol/services/`.

## Environment & running

The app expects the **conda env `nwol`** (Python 3.11.9 + Tk runtime). `main.py` auto-re-execs
into that env's interpreter when `CONDA_DEFAULT_ENV=nwol`. Run everything from inside it:

```bash
conda activate nwol
pip install -r requirements.txt          # Python deps
cd frontend && npm install && cd ..      # frontend deps (first time only)
```

```bash
python main.py                  # legacy Tkinter UI (default)
python main.py path/to.pdf      # open a PDF directly
python main.py --web            # NEW web UI in a native pywebview window (auto-builds frontend)
python main.py --debug          # DEBUG logging
```

Run the backend or frontend standalone (for iteration):

```bash
cd nwol && python -m server.main         # FastAPI on 127.0.0.1:8756
cd frontend && npm run dev               # Vite on :5173, proxies /api -> :8756
cd frontend && npm run build             # type-check (tsc --noEmit) + bundle to frontend/dist
```

## Tests, checks, packaging

```bash
cd nwol && python -m pytest                       # all tests (rootdir = nwol/)
cd nwol && python -m pytest tests/server/test_api.py::test_health   # single test
python -m compileall nwol                          # static import/syntax check
python scripts/verify_block_refonte.py             # headless DB-migration + logic suite (no UI)
python scripts/smoke_ui_block.py path/to.pdf       # full Tk UI scenario (no PDF is versioned)
```

- Tests live under `nwol/tests/{server,services}`. `nwol/tests/conftest.py` puts `nwol/` on
  `sys.path` (same trick as `main.py`); `tests/server/conftest.py` provides a `client` fixture
  that spins up a FastAPI `TestClient` against a fresh isolated SQLite DB per test.
- Packaging: `pyinstaller desktop/metacapp.spec --noconfirm` (build the frontend first). Output
  in `dist_app/`.

## Architecture

### Import convention (important)
All app code uses **absolute imports rooted at `nwol/`** (`from db ...`, `from services ...`,
`from llm ...`, `from server ...`). Entry points (`main.py`, `desktop/pywebview_main.py`,
test conftests) insert `nwol/` onto `sys.path` before importing. There is no `nwol.` package
prefix in imports — treat `nwol/` as the source root.

### The strangler boundary: `nwol/services/`
This is the UI-agnostic core, extracted from the old Tkinter `ui/app.py`. Both the legacy Tk UI
and the new FastAPI server call into it. Key modules: `orchestrator.py` (PDF import, LLM status),
`assistant.py` (contextual answers + interventions), `session.py`, `library.py`, `flashcards.py`,
`quiz.py`, `stats.py`, `lang.py`, and `llm_bridge.py` (`run_llm_sync` — blocks a sync FastAPI
endpoint until the async Ollama callback fires). When adding behavior, put logic here, not in a UI.

### Web backend: `nwol/server/`
FastAPI app factory in `app.py` (`create_app`); routers under `routers/` are mounted under `/api`
(health, stats, flashcards, library, reading, quiz, session, lang). In production the same server
also mounts the compiled `frontend/dist` at `/` (same origin → no CORS). Mono-process by design:
one SQLite writer + the serialized LLM queue avoid contention. The **reader is a WebSocket**
(`routers/reading.py`, `/api/reader/{doc_id}/stream`): client sends `ask`/`rephrase`/`recap`/
`hook`/`viewport`/`mode`/`focus`; server streams `loading`/`answer`/`intervention`/`error`.
Autonomous interventions are gated by per-mode dwell + cooldown policy (`discret`/`normal`/`coach`).

### Desktop shell: `desktop/pywebview_main.py`
Starts uvicorn in a daemon thread, waits for `/api/health`, then opens a native window pointing at
it. `NativeApi.pick_pdf()` is exposed to JS as `window.pywebview.api.pick_pdf` — the frontend gets
an absolute path and the **backend reads the file server-side** (see `frontend/src/api/platform.ts`).

### Frontend: `frontend/` (React 18 + Vite + TS)
`src/api/client.ts` is the typed API layer (relative `/api` paths work in dev via proxy and in
prod via same-origin). React Query for data, Zustand for state, react-router for routes
(`routes/`), recharts for the stats radar, KaTeX for math. The reader UI is `features/reader/`.

### LLM: `nwol/llm/`
`ollama_client.py` (async calls, worker thread), `pdf_assistant_queue.py` (serializes heavy work),
`context_builder.py`, `prompts.py`, `schema_json.py`. Per-task model options
(`num_ctx`/`num_predict`/temperature) are centralized in `config/settings.py:OLLAMA_TASK_OPTIONS`.

### Reader & metacognition: `nwol/reader/`, `nwol/metacog/`
`reader/context_snapshot.py` captures the page-at-submit-time context fed to the LLM;
`reader/intervention.py` + `reader/session_memory.py` drive autonomous help. `metacog/` computes
the six hidden gauges (attention, comprehension, curiosity, retention, creativity, metacognition),
the long-term profile, reflection, and signals.

### Persistence: `nwol/db/`
SQLite (`data/nwol.db` in dev; OS app-data dir when frozen). `db/__init__.py:get_connection()` is
the single connection helper. **Schema is versioned**: `config/settings.py:DB_SCHEMA_VERSION` (25)
is the target; `db/migrations.py` applies incremental `current < N <= TARGET` steps idempotently
on startup (`initialize_schema`, called from the FastAPI lifespan and `NWoLApp.__init__`). Bump the
version and add a migration step when changing the schema — never edit existing tables in place.

### i18n
Two parallel dictionaries (FR/EN): backend `nwol/i18n.py`, frontend `frontend/src/i18n/index.ts`.
Keep keys in sync when adding user-facing strings.

## Editions

This repository is the **local edition**: 100 % offline, Ollama only, no account, no
activation, no network call beyond `127.0.0.1:11434`. It is the upstream of a separate
private repository that adds the paid cloud edition (hosted models, OCR reconstruction,
speech). Keep it that way: anything that talks to a remote service, verifies a
subscription, or gates a feature behind a plan does **not** belong here.

The reader renders each PDF page as an image (`pymupdf_scroll`); the block renderer
(`features/reader/blocks/`) is used for imported **source-code files**, which are paginated
into `code` blocks by `services/code_reader.py`.
