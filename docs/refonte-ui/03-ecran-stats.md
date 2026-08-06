# 03 — Écran Stats (Héros #1)

## Contexte
Premier écran migré en web : **lecture seule** (zéro écriture → zéro risque
double-writer) et c'est là que la beauté saute aux yeux. Sert de **preuve de
concept** de toute la stack (Vite → FastAPI → service → JSON → React → charts)
avec le plus petit rayon d'impact. Le service `stats.py` est **déjà prêt**.

## Vision finale (UX)
Une page « tableau de bord de progression » qui donne envie de revenir :
- **En-tête** : nom, nombre de sessions, score global avec badge de tendance animé.
- **Radar** des 6 critères métacognitifs — net, animé à l'apparition, lisible.
- **Cartes par critère** : valeur, mini-barre, delta, description.
- **Courbes d'évolution** (sparklines → vraies courbes lissées) par critère.
- **Cartes par matière** : niveau, courbe, recommandation, détail dépliable.
- Tout apparaît en cascade douce (stagger), respecte `reduced-motion`.

## Périmètre
- Route `Stats` consommant `GET /api/stats/{profile,history,subjects}` (ou un seul `/overview` mappé sur `services.stats.get_metacog_overview`).
- **Charts : Recharts** — `RadarChart`, `LineChart`/sparklines. Remplace `RadarChartCanvas` + `MetricSparkline` dessinés main dans `nwol/ui/components.py`.
- Mapping catégories→libellés/couleurs côté front (le service renvoie déjà `trend.category`, `recommendation`, etc.).
- États : plein, vide (« pas encore de données — lis un chapitre »), chargement (skeleton), erreur.

## Cohabitation
La page Stats Tkinter (`ui/metacog_page.py`) **reste active en parallèle** :
les deux consomment `services.stats`. Aucune duplication de logique.

## Fichiers clés
- Nouveaux : `frontend/src/routes/Stats.tsx`, `frontend/src/features/stats/{RadarChart,EvolutionChart,CriterionCard,SubjectCard}.tsx`.
- Réutiliser : `nwol/services/stats.py` (fait), endpoints du Plan 02.
- Référence visuelle : `nwol/ui/metacog_page.py`, `nwol/ui/components.py`.

## Dépendances
- Plans 01 (fondations) + 02 (endpoint stats). Service `stats.py` déjà fait.

## Vérification / DoD
- Les chiffres du radar web == radar Tk pour le même profil (capture côte à côte).
- Cascade d'animation fluide ; reduced-motion coupe proprement.
- États vide/chargement/erreur présents.
- **Lancé dans la fenêtre pywebview** (Plan 01) → preuve « logiciel ».
