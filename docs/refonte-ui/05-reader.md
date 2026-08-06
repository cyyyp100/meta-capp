# 05 — Le Reader (Héros #2 + #3)

## Contexte
La pièce maîtresse, migrée **en dernier** car la plus riche : rendu des pages,
zoom, surlignage, panneau Gemma déplaçable, streaming des réponses, et le
ticker d'intervention 5 s côté serveur. C'est ici que vivent les héros #2
(zoom) et #3 (Gemma déplaçable). On extrait ~60 % de `ui/scroll_reader.py`
(1608 lignes) vers les services ; le front ne fait que rendre + interagir.

## Vision finale (UX)
- **Lecture plein cadre**, scroll vertical fluide, pages en images nettes, marges calmes.
- **Zoom (héros #2)** : molette + `Ctrl +/-` + pincement trackpad → zoom **continu** (CSS transform, instantané) puis **re-rendu HD** au repos (net). Indicateur de niveau, double-clic = reset. Le surlignage suit le zoom automatiquement.
- **Gemma (héros #3)** : panneau **déplaçable & redimensionnable** (`react-rnd`), position/ taille **mémorisées** (réutilise `save_bubble_position`), modes discret/normal/coach, repli en bulle. Ne recouvre jamais la lecture sans intention. Réponses **streamées token par token**.
- **Surlignage** : citations LLM dessinées en overlay SVG translucide (jaune=clé, bleu=explication, vert=référence), auto-scroll vers la 1ʳᵉ.
- **Interventions** : toasts non bloquants (question, révision de carte, pause, fin de chapitre) poussés par le serveur.

## Périmètre
### Sous-étapes (ordre de construction)
1. **Rendu statique** : liste virtualisée de pages via `GET /api/library/doc/{id}/page/{n}.png?zoom=`, rapport de viewport (`POST /session/{sid}/viewport`), zoom CSS + palier HD.
2. **Spine WebSocket** `/api/session/{sid}/stream` : `viewport`, `mode`, `focus`.
3. **Surlignage** : overlay SVG depuis rects en **points PDF** (résolution serveur via `services/highlights.py`).
4. **Gemma Q&A libre** : panneau `react-rnd` + `ask_question` streamé + persistance de l'échange.
5. **Ticker 5 s serveur** → toasts d'intervention (le changement comportemental le plus sensible → derrière un flag + comparaison vs Tk).
6. **Boucle Q&R pédagogique** via événements `AdaptiveCompanion` (question→réponse→feedback→reformulation), recap de chapitre, hook de curiosité, révision de carte.

### Extraction backend (depuis `ui/scroll_reader.py`)
- Calcul surlignage → `services/highlights.py` (rects en points PDF, plus de coords pixel).
- Ticker, focus, mémoire de session, snapshot, détection fin de chapitre → `services/reading_session.py`.
- Q&A / rephrase / recap / hook → `services/assistant.py` (réutilise `AdaptiveCompanion`).
- **Dwell** piloté par les `/viewport` du client (le client détecte la page dominante).

## Fichiers clés
- Nouveaux : `frontend/src/features/reader/{ReaderCanvas,PageImage,HighlightLayer,ZoomControls,GemmaPanel,InterventionToast,QABlock}.tsx`, `frontend/src/api/ws.ts`.
- Backend : `services/{reading_session,assistant,highlights}.py`, `nwol/server/{events,scheduler}.py`.
- Réutiliser : `nwol/core/companion.py`, `nwol/reader/intervention.py`, `nwol/reader/session_memory.py`, `nwol/llm/ollama_client.py`, `nwol/pdf_viewer/*`, `nwol/db/user.py` (`save_bubble_position`).

## Dépendances
- Plans 01 + 02 (WebSocket, endpoints image). Idéalement après 03/04 (patterns rodés).

## Vérification / DoD
- Tk reader et web reader sur le **même PDF/session** : mêmes interventions déclenchées, mêmes surlignages, mêmes jauges en DB.
- Zoom continu **et** net au repos testé sur un passage **inter-colonnes** et un **raccord de page** (points durs connus).
- Panneau Gemma : déplacé/redimensionné → position rechargée à la session suivante.
- Réponse LLM visible en streaming, pas en bloc.
