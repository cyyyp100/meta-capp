# 07 — Polish & cohérence finale

## Contexte
Tous les écrans existent et fonctionnent. Cette étape est le passage « wow » qui
transforme « ça marche » en « c'est un beau logiciel pro ». C'est ce qui fait
**définitivement** oublier Tkinter.

## Vision finale (UX)
- **Cohérence totale** : audit écran par écran des espacements, alignements, tailles de texte, états. Un seul langage visuel partout (tokens du Plan 00).
- **Mouvement** : transitions de navigation, apparitions en cascade, feedback de clic, micro-interactions — tout à 60 fps, tout coupé par `reduced-motion`.
- **Dark mode** complet (tokens clair/sombre déjà posés au Plan 01) + bascule auto selon l'OS.
- **États systématiques** : chaque liste/écran a vide / chargement (skeleton) / erreur / succès soignés.
- **Chargements LLM** : jamais un spinner nu — la bulle Gemma « réfléchit », streaming visible, messages d'attente vivants.
- **Raccourcis clavier** : navigation, zoom (`Ctrl±`), ouvrir/fermer Gemma, recherche, retour. Palette de commandes optionnelle.
- **Onboarding** discret (premiers pas, tooltips contextuels la 1ʳᵉ fois).
- **Son/haptique** optionnels et subtils (succès de révision, fin de chapitre).

## Périmètre
- Passe d'audit transversale (pas de nouvelle feature) : design review de chaque route.
- Implémentation du thème sombre sur tous les composants.
- Système de raccourcis global + indices visuels.
- Bibliothèque d'illustrations/états vides cohérente.
- Perf : virtualisation des longues listes, lazy-loading des images, budget de rendu.

## Fichiers clés
- Transversal : `frontend/src/theme/*`, `frontend/src/components/*` (EmptyState, Skeleton, Toast, Shortcut).
- Hook global raccourcis : `frontend/src/hooks/useShortcuts.ts`.

## Dépendances
- Tous les écrans (Plans 03–06) en place.

## Vérification / DoD
- **Checklist « pro »** validée sur chaque écran : alignements, vide/chargement/erreur, dark mode, focus clavier, contrastes AA.
- Un testeur naïf ne devine pas l'origine Tkinter et cite les 3 héros comme « ce qui est cool ».
- Aucune régression de perf (scroll/zoom du reader fluides sur un gros PDF).
