# 08 — Packaging & distribution

## Contexte
Transformer le projet (frontend + FastAPI + Python) en **un vrai logiciel
installable**. La distribution n'est pas encore tranchée : on conçoit pour
pouvoir distribuer plus tard **sans refonte**, et on ne paie le coût que le
moment venu. La frontière FastAPI-local + bundle web ne change jamais ; seul
l'emballage diffère.

## Trois modes, un seul code
1. **Dev** : `uvicorn` + `npm run dev` (navigateur, rechargement à chaud). Pour développer uniquement.
2. **pywebview** (déjà au Plan 01) : fenêtre native + serveur local embarqué. **C'est déjà un logiciel utilisable**, idéal pour un usage perso / une première release interne. Empaquetable avec PyInstaller (un exécutable).
3. **Tauri** (cible distribution large) : coque Rust qui embarque le serveur Python figé (sidecar PyInstaller) + le bundle web. Installeurs `.dmg` / `.exe` / `.AppImage`, **signature de code**, **mises à jour automatiques**, binaires légers.

## Vision finale
L'utilisateur télécharge un installeur, double-clique, l'icône Meta-Capp
apparaît dans le dock/menu démarrer, l'appli s'ouvre comme n'importe quel
logiciel — Ollama tournant en local pour le LLM.

## Périmètre (à faire au moment de distribuer)
- **pywebview + PyInstaller** : recette de build mono-fichier par OS ; gestion des chemins de ressources (`frontend/dist`, modèles, DB utilisateur dans le dossier app-data).
- **Tauri** (si distribution large) : config sidecar Python, signature (Apple notarization / Windows codesign), updater.
- **Gestion d'état utilisateur** : DB et caches dans le bon dossier OS (pas dans le bundle).
- **Dépendance Ollama** : détection au lancement + écran d'aide si absent (l'appli reste utilisable en mode dégradé hors-LLM, comme aujourd'hui).
- Cache de rendu : éviction LRU (serveur long-vécu) pour ne pas grossir sans fin.

## Recette PyInstaller (en place)
Spec : `desktop/metacapp.spec`. Le serveur est rendu *frozen-aware* (`server/config.py`
sert `frontend/dist` depuis `sys._MEIPASS` en mode gelé).

```bash
conda activate nwol
pip install pyinstaller
cd frontend && npm run build      # produit frontend/dist
cd .. && pyinstaller desktop/metacapp.spec
# -> dist/Meta-Capp.app (macOS) / dist/Meta-Capp/ (Windows, Linux)
```

⚠️ Recette de départ : non figée/vérifiée sur ce poste (le freeze de PyMuPDF/
pywebview/uvicorn demande souvent une ou deux itérations sur `hiddenimports`).
La DB utilisateur reste hors bundle (`data/nwol.db` dans le dossier app-data).

## Fichiers clés
- En place : `desktop/metacapp.spec`, `desktop/pywebview_main.py`, `server/config.py` (frozen-aware).
- Plus tard (distribution large) : `src-tauri/` (Tauri + sidecar Python).

## Dépendances
- Toute la refonte (Plans 01–07). Le mode pywebview est utilisable bien avant, dès le Plan 03.

## Vérification / DoD
- Un installeur produit une appli qui se lance sans terminal ni navigateur sur une machine vierge (même OS).
- Données utilisateur persistées au bon endroit ; mise à jour ne les écrase pas.
- Écran clair si Ollama est absent.
