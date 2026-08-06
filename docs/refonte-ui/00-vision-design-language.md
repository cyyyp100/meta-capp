# 00 — Vision & langage de design

## Contexte
Définir, avant toute ligne de code UI, ce que « UI/UX parfaite » signifie
concrètement pour Meta-Capp. Tous les plans suivants s'y réfèrent. Objectif :
un logiciel de bureau qui **respire le pro** — calme, lisible, fluide,
confiant — au service d'une seule mission : **lire et apprendre sans friction**.

## Ressenti cible (le « brief » émotionnel)
- **Calme et focalisé** : la lecture est reine ; tout le reste s'efface.
- **Vivant mais sobre** : micro-animations à 60 fps, jamais gratuites.
- **Crédible** : densité d'info maîtrisée, alignements parfaits, zéro élément « bricolé ».
- **Réactif** : tout retour < 100 ms ; les attentes LLM sont *montrées* (streaming, états de chargement soignés), jamais subies.

## Langage de design

### Couleurs (tokens, hérités/raffinés depuis `nwol/ui/theme.py`)
On repart de la palette teal/gris-bleu existante, nettoyée en échelle :
- **Neutres** : `--bg`, `--surface`, `--surface-soft`, `--border`, `--border-strong`, échelle de texte `--text` / `--text-soft` / `--muted`.
- **Accent unique** : teal (`--accent`, `--accent-hover`, `--accent-soft`) — un seul accent, utilisé avec parcimonie.
- **Sémantiques** : `--success`, `--warning`, `--danger` (+ variantes `-soft`).
- **Surlignage lecture** : `key` (jaune), `explain` (bleu), `reference` (vert) — repris tels quels.
- **Dark mode** : chaque token a une valeur claire **et** sombre (voir Plan 07). Décidé dès les fondations pour ne pas refactorer après coup.

### Typographie
- **Échelle modulaire** (ex. 12/14/16/20/26/34) avec interlignage généreux.
- **UI** : sans-serif système (SF Pro / Segoe / Inter). **Lecture** : la page PDF reste une image — la typo UI n'affecte pas le texte lu.
- Poids limités à 400 / 600 / 700.

### Espacement & rythme
- Grille 4 px (`xs=4, sm=8, md=14, lg=22, xl=34` — déjà dans le thème).
- Marges généreuses, peu d'éléments par écran, beaucoup de blanc.

### Profondeur & matière
- Élévation par **ombres douces + flou** (cartes, panneaux flottants, bulle Gemma), pas par bordures dures.
- Coins arrondis cohérents (`sm=10, md=16, lg=22, xl=30`).

### Mouvement
- Easing maison (`ease_out_cubic`, `ease_in_out_cubic` — déjà conceptualisés dans le thème).
- Durées : `fast=120ms`, `normal=180ms`, `slow=280ms`, `festive=420ms`.
- Respecter `prefers-reduced-motion` (option déjà prévue côté thème).

## Standards transverses (la barre « pro »)
- **États vides** soignés (jamais une liste vide brute) — illustration + action.
- **Squelettes de chargement** (skeleton) plutôt que spinners nus.
- **États d'erreur** clairs + action de reprise (surtout LLM indispo).
- **Accessibilité** : contrastes AA, focus visibles, navigation clavier complète.
- **Cohérence i18n** FR/EN sans redémarrage (système `i18n` existant porté en tokens front).
- **Densité responsive** : la fenêtre se redimensionne proprement (≥ 1024×680).

## Les 3 features héros — vision finale
1. **Stats** : un radar animé net + courbes d'évolution lisibles + cartes par critère/matière. Sentiment : « je vois ma progression d'un coup d'œil, c'est beau ».
2. **Zoom lecture** : molette/`Ctrl+±`/pincement → zoom continu fluide, puis re-rendu HD net au repos. Le surlignage suit le zoom.
3. **Gemma déplaçable** : panneau drag & resize, position mémorisée, mode discret/normal/coach, jamais par-dessus ce qu'on lit sans le vouloir.

## Définition de « fini » (pour toute la refonte)
- Un nouvel utilisateur ne devine **pas** que c'était du Tkinter.
- Les 3 features héros sont fluides et évidentes.
- Tout écran a : état plein soigné, état vide, état chargement, état erreur.
- L'appli se lance comme un logiciel natif (Plan 08).
