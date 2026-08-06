# Refonte UI/UX Meta-Capp — Jeu de plans vers la version finale

> **Meta-Capp reste un logiciel de bureau (desktop), pas un site web.**
> On garde le backend Python (~40K LOC : PDF/PyMuPDF, DB, Ollama, répétition
> espacée, métacognition). On remplace seulement la **peau Tkinter** par un
> moteur de rendu moderne (web tech) **embarqué dans une fenêtre native**
> (pywebview, puis Tauri pour la distribution). Aucun navigateur, aucune URL
> pour l'utilisateur final : il double-clique une icône, une appli s'ouvre.
> C'est l'architecture de VS Code / Notion / Figma desktop.

Ce dossier est la feuille de route **design-led** vers l'UI/UX finale. Le plan
**technique** du strangler (découplage, FastAPI, WebSocket) vit dans
`~/.claude/plans/si-on-envisage-une-delightful-turing.md` — les deux se
complètent : ici le « à quoi ça ressemble et ce qu'on ressent », là « comment
on câble ».

## Les 3 features héros (la promesse à l'utilisateur)
1. **Stats magnifiques** — graphiques pro (radar animé, courbes), fin du « dessiné à la main ».
2. **Zoom de lecture** — zoomer/dézoomer le texte lu, fluide et net.
3. **Gemma déplaçable** — panneau de discussion drag & resize, qui ne gêne jamais.
…plus le standard global : passer de « projet étudiant » à « logiciel pro ».

## Ordre de lecture des plans
| # | Plan | Rôle |
|---|------|------|
| 00 | [Vision & langage de design](00-vision-design-language.md) | Ce que « parfait » veut dire : design system, ressenti, principes |
| 01 | [Fondations : coque desktop & frontend](01-fondations-coque-et-frontend.md) | La fenêtre native, le squelette React, les design tokens |
| 02 | [Services & API locale](02-services-et-api.md) | Finir la couche `services/`, FastAPI, WebSocket |
| 03 | [Écran Stats](03-ecran-stats.md) | **Héros #1** — la démonstration de beauté |
| 04 | [Accueil & bibliothèque](04-bibliotheque-et-accueil.md) | La première impression, l'import PDF |
| 05 | [Le Reader](05-reader.md) | **Héros #2 + #3** — zoom, Gemma déplaçable, surlignage, streaming |
| 06 | [Flashcards, Quiz, SAS, Langues](06-flashcards-quiz-sas-langues.md) | Les surfaces d'apprentissage restantes |
| 07 | [Polish & cohérence finale](07-polish-et-coherence.md) | Le passage « wow » : motion, états vides, dark mode, raccourcis |
| 08 | [Packaging & distribution](08-packaging-distribution.md) | pywebview → Tauri, installeurs signés |

## Principe de migration (strangler)
Chaque écran migré consomme la **même couche `services/`** que Tkinter pendant
la transition → aucune logique dupliquée, Tkinter reste utilisable jusqu'au
dernier écran migré, puis on le retire.

## État actuel (15 juin 2026)
- ✅ **Étape 0 faite** : `services/stats.py`, `services/flashcards.py`, pages Tk
  refactorées, `nwol/tests/services/` (9 tests verts).
- ⏭️ Prochaine : Plan 01 (fondations) + Plan 02 (FastAPI lecture seule).
