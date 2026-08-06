# 01 — Fondations : coque desktop & frontend

## Contexte
Poser le socle qui garantit que Meta-Capp **reste un logiciel** : une fenêtre
native (pas un navigateur) qui charge un frontend moderne, lequel parle à un
backend Python local. Tout le reste de la refonte s'appuie dessus.

## Objectif
1. Le frontend React+Vite+TS qui compile et tourne.
2. Le **design system** (tokens du Plan 00) implémenté une fois, réutilisé partout.
3. La **coque desktop** (pywebview) : double-clic → fenêtre native, serveur local invisible.

## Pourquoi ça reste un logiciel (rappel d'archi)
```
┌───────────────────────── Fenêtre native (pywebview / Tauri) ─────────────────────────┐
│   WebView OS (rend le frontend)  ⇄  bridge fichiers natifs                            │
│                         │ HTTP/WS sur 127.0.0.1 (interne, invisible)                  │
│                  FastAPI (uvicorn) lancé DANS le process de l'appli                    │
│                         │                                                              │
│                  nwol/services/* → db / llm / pdf  (backend Python conservé)          │
└────────────────────────────────────────────────────────────────────────────────────┘
```
L'utilisateur ne voit ni terminal, ni navigateur, ni URL.

## Périmètre
### Frontend (`frontend/`)
- Vite + React + TypeScript. Proxy dev `/api` → `127.0.0.1:<port>`.
- `src/theme/` : tokens (Plan 00) en **variables CSS** + clair/sombre. Source unique de vérité, portée depuis `nwol/ui/theme.py`.
- `src/components/` : primitives partagées (Button, Card, Surface, Pill/ProgressBar, Toast, Modal, Skeleton, EmptyState) — l'équivalent moderne de `ui/components.py` + `ui/theme.py`.
- `src/api/client.ts` : fetch typés. `src/api/ws.ts` : hook WebSocket (Plan 02/05).
- État : **Zustand** (état live) + **TanStack Query** (écrans read-mostly).
- Routing : une route par écran (Home, Stats, Flashcards, Reader, Quiz, Lang).

### Coque desktop (`desktop/`)
- `desktop/pywebview_main.py` (~30–40 lignes) : démarre uvicorn dans un thread, ouvre une fenêtre pywebview sur le bundle `frontend/dist`, expose le **dialogue fichier natif** (`webview.create_file_dialog`).
- `frontend/src/api/platform.ts` : seule abstraction qui touche l'OS (ouvrir un PDF). En dev = `<input type=file>` ; en coque = bridge natif. Tout le reste est identique.

## Fichiers clés
- À créer : `frontend/` (squelette Vite), `frontend/src/theme/tokens.css`, `frontend/src/components/*`, `desktop/pywebview_main.py`, `frontend/src/api/platform.ts`.
- À réutiliser comme **référence visuelle** (couleurs, rayons, easings, libellés) : `nwol/ui/theme.py`, `nwol/ui/components.py`, `nwol/i18n.py`.

## Dépendances
- Aucune côté écrans. C'est le préalable de **tous** les plans 03–07.
- Peut démarrer en parallèle du Plan 02 (le frontend tape des endpoints mockés tant que FastAPI n'est pas prêt).

## Vérification / DoD
- `npm run dev` affiche une page « design system » listant tous les composants/tokens (clair **et** sombre).
- `python desktop/pywebview_main.py` ouvre une **fenêtre native** affichant cette page — preuve que c'est un logiciel, pas un onglet.
- Redimensionnement propre ≥ 1024×680 ; `prefers-reduced-motion` respecté.
