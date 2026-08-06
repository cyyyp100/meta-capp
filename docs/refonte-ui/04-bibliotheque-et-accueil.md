# 04 — Accueil & bibliothèque

## Contexte
La première impression. Aujourd'hui : `ui/home.py` (titre, streak, 4 tuiles).
On en fait un véritable **hub** : reprendre une lecture, importer un PDF,
accéder aux modules — avec le dialogue fichier **natif** (preuve « logiciel »).

## Vision finale (UX)
- **Accueil** : salutation + streak (🔥), **« Continuer la lecture »** (dernier document, vignette + progression), grille de **documents récents** (vignette 1ʳᵉ page, titre, % lu), entrée **Importer un PDF**, accès Flashcards / Quiz / Langues / Stats / Profil.
- **Import PDF** : bouton → dialogue fichier **OS natif** → barre de progression de reconstruction → ouverture directe du Reader.
- **Bibliothèque** : liste/grille filtrable des documents, reprise au bon endroit.

## Périmètre
- Route `Home` + `Library` consommant `GET /api/library/recent`, `GET /api/library/doc/{id}` (+ vignette = `page/1.png?zoom=`).
- `POST /api/library/import` branché sur le **sélecteur natif** via `frontend/src/api/platform.ts` (Plan 01).
- Vignettes servies par l'endpoint image (cache disque existant côté `pdf_viewer`).
- États : aucune bibliothèque (onboarding « importe ton premier PDF »), import en cours, import en échec.

## Fichiers clés
- Nouveaux : `frontend/src/routes/{Home,Library}.tsx`, `frontend/src/features/library/{DocumentCard,ImportButton,ContinueReading}.tsx`.
- À créer côté service : `services/library.py` + `services/orchestrator.py::import_pdf` (Plan 02).
- Référence : `nwol/ui/home.py`, `nwol/ui/app.py` (flux d'import).

## Dépendances
- Plans 01 + 02 (endpoints library + import + sélecteur natif).

## Vérification / DoD
- Importer un PDF via le **dialogue natif** → chapitres construits → Reader s'ouvre.
- « Continuer la lecture » rouvre au bon document.
- États onboarding/progression/échec présents.
