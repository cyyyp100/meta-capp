# 02 — Services & API locale

## Contexte
Le frontend ne doit jamais toucher la DB ni le LLM directement. Tout passe par
la couche `services/` (Python pur) exposée via une **API locale FastAPI**
(127.0.0.1, embarquée dans l'appli). C'est la frontière qui rend la nouvelle UI
possible **et** qui découple la logique de Tkinter pendant la transition.

## Objectif
1. Compléter la couche `services/` (au-delà de l'Étape 0 déjà faite).
2. Monter le serveur FastAPI : endpoints REST lecture seule d'abord, puis écriture, puis WebSocket.

## État de départ
- ✅ Déjà fait : `services/stats.py`, `services/flashcards.py` + tests.
- ⏭️ À créer : `services/library.py`, `services/orchestrator.py`, `services/reading_session.py`, `services/assistant.py`, `services/highlights.py`, `services/quiz.py`, `services/lang.py`.

## Périmètre
### Couche services (Python pur, dicts JSON, ni Tkinter ni FastAPI)
- `library.py` : `list_recent_documents`, `get_document` (+ `page_sizes_pts`), `render_page(doc_id, page, zoom)→png`, `page_text`, `search_page`. Enveloppe `db.documents`, `db.chapters`, `pdf_viewer.page_renderer`.
- `orchestrator.py` : import PDF, cycle de session (start/end/finalize), `llm_status`. Extrait de `ui/app.py`.
- `reading_session.py` / `assistant.py` / `highlights.py` : extraits de `ui/scroll_reader.py` (voir Plan 05).
- Réutiliser le modèle **callbacks injectables** de `core/companion.py` + `reader/intervention.py`.

### Serveur (`nwol/server/`)
- `app.py` (factory + CORS dev + lifespan `initialize_schema`/`ensure_default_user`), `routers/*`, `events.py` (bus + WebSocket + `push_threadsafe`), `scheduler.py` (ticker 5 s), `models.py` (Pydantic = contrat), `main.py` (uvicorn).
- **REST** : `/api/health`, `/api/stats/*`, `/api/flashcards…`, `/api/library/recent|doc/{id}|page/{n}.png?zoom=`, `/api/session/*`, `/api/quiz/*`.
- **WebSocket** `/api/session/{sid}/stream` : tokens LLM, interventions poussées, surlignages, fin de chapitre (détaillé Plan 05).

### Pont threading critique
Le worker Ollama est un thread démon → callbacks vers la boucle asyncio via
`loop.call_soon_threadsafe(queue.put_nowait, evt)` (helper testé dans `events.py`).
C'est l'analogue de l'actuel `self.after(0, ...)`.

## Fichiers clés
- Nouveaux : `nwol/services/{library,orchestrator,reading_session,assistant,highlights,quiz,lang}.py`, `nwol/server/*`.
- Réutiliser : `nwol/core/companion.py`, `nwol/reader/intervention.py`, `nwol/llm/ollama_client.py`, `nwol/pdf_viewer/page_renderer.py`, `nwol/db/*`.
- Dépendances à installer : `fastapi`, `uvicorn[standard]`, `websockets` (ajouter à `requirements.txt`).

## Garde-fou : SQLite mono-writer
Pendant la transition, **jamais** Tkinter ET uvicorn n'écrivent la même
`data/nwol.db` simultanément. `PRAGMA busy_timeout`, uvicorn **mono-process**.

## Vérification / DoD
- `tests/services/` couvre chaque nouveau service (filet de parité, comme l'Étape 0).
- `curl` (ou client HTTP) sur chaque endpoint REST renvoie le JSON attendu.
- Le WebSocket émet un événement `token` de bout en bout sur une question test.
