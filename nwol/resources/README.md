# `nwol/resources/` — ressources embarquées, en lecture seule

Contrairement à `nwol/assets/` (caches d'exécution, gitignoré, absent des
checkouts CI), ce dossier **est versionné** et embarqué sans condition dans le
bundle PyInstaller (`desktop/metacapp.spec`). L'application le lit sous
`sys._MEIPASS` quand elle est gelée, ici sinon — voir
`services/onboarding.py:RESOURCES_DIR`.

## Le document de démonstration de la visite guidée

| Fichier | Rôle |
|---|---|
| `demo_fr.pdf` | l'article prêté à la bibliothèque pendant la visite, en français |
| `demo_en.pdf` | sa version anglaise (à défaut, `demo_fr.pdf` sert dans les deux langues) |

La visite guidée l'emprunte au démarrage (`POST /api/onboarding/demo`), le
montre dans la bibliothèque puis dans le lecteur, et le rend à la fin
(`DELETE /api/onboarding/demo`). Il ne reste jamais dans la bibliothèque de
quelqu'un : un garde-fou le jette aussi au démarrage suivant s'il a survécu à
une fermeture brutale.

### Ce que le fichier doit respecter

1. **Un vrai calque texte.** C'est la seule contrainte non négociable. Le calque
   de sélection, la recherche et les surlignages passent tous par
   `PdfDocument._indexed_text()` / `get_charbox` (cf. `CLAUDE.md` § Le moteur
   PDF). Un PDF fait d'images scannées afficherait des pages, mais on ne
   pourrait ni sélectionner, ni surligner, ni citer — c'est-à-dire que la moitié
   de ce que la visite explique ne se verrait pas.
2. **3 à 6 pages.** Le chapitre lecture de la visite ne défile pas au-delà de la
   première page ; au-dessus de quelques pages, c'est du poids de bundle pour
   rien.
3. **Une première page présentable.** Elle sert de vignette dans la
   bibliothèque, et c'est la page qu'on explique.
4. **Redistribuable.** Un article écrit pour l'occasion, ou une œuvre sous
   licence qui autorise explicitement la redistribution (CC-BY, domaine public).
   Attention : la licence arXiv par défaut (« perpetual, non-exclusive ») permet
   à arXiv de distribuer l'article, **pas à un tiers de le réembarquer**. C'est
   la même discipline que pypdfium2 plutôt que PyMuPDF.

Aucune contrainte de nom interne, de police ou de mise en page : le titre affiché
dans la bibliothèque ne vient pas du PDF mais de `i18n.py`
(`onboarding.doc_title`), tout comme la matière, le résumé et les mots-clés de
la carte.

### Le fichier actuellement embarqué

`demo_fr.pdf` est un **extrait de 4 pages** (pages 12 à 15, le début du chapitre
« Your computer (Hardware) ») d'un rapport d'informatique écrit par l'auteur du
projet : redistribuable sans réserve, calque texte intact, et une page 1 qui
ouvre un chapitre au lieu d'être une page de titre — c'est elle qu'on explique
et qui porte les deux phrases de `DEMO_QUOTES`. Le rapport complet (131 pages)
n'est pas versionné : il vit dans `doc_test/`, et l'extrait se régénère avec
`import_pages(src, [11, 12, 13, 14])` (cf. pypdfium2).

Il n'y a **pas de `demo_en.pdf`** : le texte du rapport est déjà en anglais et
`_bundled_pdf()` retombe sur `demo_fr.pdf` dans les deux langues. Ce sont les
bulles de la visite qui sont traduites, pas le document.

### Les citations mises en avant par Clikoda

Pendant le chapitre lecture, la fausse session fait « surligner » deux phrases
par Clikoda. Elles sont déclarées côté frontend, en un seul endroit :

    frontend/src/features/reader/demoScript.ts  →  DEMO_QUOTES

Pour que les surlignages apparaissent, ces chaînes doivent exister **mot pour
mot** dans la première page du PDF. Si elles n'y sont pas, la recherche ne
trouve rien et il ne se passe simplement rien de visible : la visite continue,
sans surlignage. Après avoir déposé le PDF, ajuster `DEMO_QUOTES` en recopiant
deux phrases de sa première page.
