# 06 — Flashcards, Quiz, SAS & Langues

## Contexte
Migrer les surfaces d'apprentissage restantes pour pouvoir **retirer Tkinter**.
Le service `flashcards.py` est **déjà prêt** (Étape 0). Ces écrans introduisent
les premières écritures côté web (révisions, réponses) et des interactions
riches (flip de carte, quiz, réflexion métacognitive).

## Vision finale (UX)
- **Flashcards** : bibliothèque filtrable, **carte 3D flip** fluide (CSS transform), révision SR avec verdicts (incorrect/partiel/correct), création avec tags (auto via LLM, repli sans LLM). Remplace le flip dessiné au canvas.
- **Quiz** : sélecteur de matière, questions typées et **colorées par type**, score en direct, page de résultats avec répartition.
- **SAS d'entrée/sortie** : sas d'entrée (gate de concentration + hook de curiosité + révision éclair) ; sas de sortie = **bilan de session** (métriques animées + 3 questions de réflexion). Les métriques deviennent de vrais petits visuels.
- **Langues** : sélecteur, session par blocs (timer visuel), dialogue A/B avec phonétique/traduction.

## Périmètre
- Routes `Flashcards`, `Quiz`, `SessionEntry`, `SessionExit`, `Lang*`.
- Écritures via `POST /api/flashcards`, `/flashcards/{id}/review`, `/quiz/answer`, `/session/{sid}/finalize`.
- Génération de tags / corrections langue : flux streamés via WebSocket (réutilise l'infra Plan 05) ; repli sans LLM côté `services.flashcards.fallback_tags`.
- États vide/chargement/erreur partout.

## Fichiers clés
- Nouveaux : `frontend/src/routes/{Flashcards,Quiz,SessionEntry,SessionExit}.tsx`, `frontend/src/features/{flashcards/FlipCard, quiz/QuestionCard, sas/MetricReveal}.tsx`, `frontend/src/routes/lang/*`.
- Backend : `services/flashcards.py` (fait), + `services/quiz.py`, `services/lang.py`, `services/orchestrator.py` (finalize/SAS) (Plan 02).
- Référence : `nwol/ui/{flashcards_page,quiz_page,session_entry_sas,session_exit_sas,lang_session_page}.py`.

## Dépendances
- Plans 01 + 02. Flashcards peut suivre directement le Plan 03 (write léger, sans streaming).

## Retrait de Tkinter (fin de cette étape)
Une fois ces écrans validés, supprimer `nwol/ui/*`, garder `services/` + `server/` + `frontend/`, retirer Tk de `requirements.txt`.

## Vérification / DoD
- Une révision web met à jour la DB (visible ensuite partout).
- Quiz : score et niveaux de matière cohérents avec l'ancienne logique.
- SAS de sortie : réflexions enregistrées, profil métacog mis à jour.
- Plus aucune dépendance à `ui/*` ; l'appli tourne intégralement en pywebview.
