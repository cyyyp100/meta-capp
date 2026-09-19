# services/rag_lexicon.py — Équivalents FR ↔ EN pour la recherche lexicale.
#
# L'étudiant pose ses questions en français sur des documents souvent en anglais
# (articles, manuels). Le radical commun suffit pour « configuration » ou
# « implémentation », mais rien ne relie « taux » à « rate », « apprentissage »
# à « learning » ni « organe » à « organ ». Ce petit lexique du vocabulaire
# académique et scientifique courant comble cette lacune ; il n'est consulté
# qu'en REPLI, quand le mot de la question n'apparaît nulle part dans le
# document (cf. services/pdf_rag.resolve_terms), et fonctionne dans les deux sens.
#
# S'y ajoutent quelques familles de quasi-synonymes (`synonyms`) : la table
# des « configurations » d'un article répond à une question sur ses
# « hyperparamètres », et aucun radical ne relie les deux. Elles s'appliquent
# en EXPANSION, à poids réduit (cf. ASSISTANT_RAG_SYNONYM_WEIGHT) : le mot de
# l'étudiant reste le terme principal.
#
# Volontairement court et générique : c'est le vocabulaire d'un cours ou d'un
# article, pas une terminologie de domaine. Les mots dont le radical FR/EN est
# déjà commun (segmentation, gradient, distribution…) n'ont pas leur place ici.
from __future__ import annotations

from utils.text import fold

__all__ = ["translations", "synonyms"]

# FR (au singulier, sans accent — le pliage est appliqué à la lecture) → EN.
# Plusieurs équivalents possibles, du plus courant au plus rare.
_FR_EN: dict[str, tuple[str, ...]] = {
    # Structure d'un document
    "chapitre": ("chapter",),
    "tableau": ("table",),
    "legende": ("caption", "legend"),
    "annexe": ("appendix",),
    "resume": ("abstract", "summary"),
    "bibliographie": ("references", "bibliography"),
    "demonstration": ("proof",),
    "preuve": ("proof",),
    "theoreme": ("theorem",),
    "lemme": ("lemma",),
    "hypothese": ("hypothesis", "assumption"),
    "exemple": ("example",),
    "exercice": ("exercise", "problem"),
    "enonce": ("statement",),
    "resultat": ("result",),
    # Quantités et mesures
    "taux": ("rate",),
    "vitesse": ("speed", "velocity", "rate"),
    "taille": ("size",),
    "nombre": ("number",),
    "valeur": ("value",),
    "moyenne": ("mean", "average"),
    "mediane": ("median",),
    "ecart-type": ("std", "standard deviation"),
    "erreur": ("error",),
    "precision": ("accuracy", "precision"),
    "rappel": ("recall",),
    "cout": ("cost",),
    "temps": ("time",),
    "duree": ("duration", "time"),
    "memoire": ("memory",),
    "poids": ("weight",),
    "biais": ("bias",),
    "seuil": ("threshold",),
    "borne": ("bound",),
    "limite": ("limit", "limitation"),
    "pente": ("slope",),
    "surface": ("area", "surface"),
    "longueur": ("length",),
    "largeur": ("width",),
    "hauteur": ("height",),
    "profondeur": ("depth",),
    "frequence": ("frequency",),
    "puissance": ("power",),
    "energie": ("energy",),
    "masse": ("mass",),
    "charge": ("charge", "load"),
    "champ": ("field",),
    "onde": ("wave",),
    "particule": ("particle",),
    "cellule": ("cell",),
    "organe": ("organ",),
    "tissu": ("tissue",),
    "maladie": ("disease",),
    "patient": ("patient", "subject"),
    "echantillon": ("sample",),
    "mesure": ("measure", "measurement"),
    # Méthode et expérience
    "methode": ("method",),
    "approche": ("approach",),
    "modele": ("model",),
    "reseau": ("network",),
    "couche": ("layer",),
    "noyau": ("kernel",),
    "donnees": ("data",),
    "donnee": ("data",),
    "entrainement": ("training",),
    "apprentissage": ("learning", "training"),
    "sur-apprentissage": ("overfitting",),
    "surapprentissage": ("overfitting",),
    "parametrage": ("parameter", "setting"),
    "parametre": ("parameter",),
    "hyperparametre": ("hyperparameter",),
    "reglage": ("tuning", "setting"),
    "perte": ("loss",),
    "etape": ("step", "stage"),
    "epoque": ("epoch",),
    "lot": ("batch",),
    "graine": ("seed",),
    "tache": ("task",),
    "requete": ("query",),
    "etiquette": ("label",),
    "classe": ("class",),
    "essai": ("trial", "run"),
    "execution": ("run", "execution"),
    "experience": ("experiment",),
    "comparaison": ("comparison",),
    "evaluation": ("evaluation", "assessment"),
    "entree": ("input",),
    "sortie": ("output",),
    "cible": ("target",),
    "objectif": ("objective", "goal"),
    "contrainte": ("constraint",),
    "inconnue": ("unknown",),
    "derivee": ("derivative",),
    "integrale": ("integral",),
    "matrice": ("matrix",),
    "vecteur": ("vector",),
    "sous-ensemble": ("subset",),
    "serie": ("series",),
    "boucle": ("loop",),
    "arbre": ("tree",),
    "graphe": ("graph",),
    "chemin": ("path",),
    "noeud": ("node",),
    "arete": ("edge",),
    "sommet": ("vertex", "node"),
    "aleatoire": ("random",),
    "probabilite": ("probability",),
    "vraisemblance": ("likelihood",),
    "loi": ("law", "distribution"),
    "espece": ("species",),
    "milieu": ("medium", "environment"),
    "melange": ("mixture",),
    "liaison": ("bond",),
    "guerre": ("war",),
    "siecle": ("century",),
}


# Familles de quasi-synonymes, en anglais (langue de la plupart des documents ;
# les radicaux communs les font aussi porter sur un document français). Un mot
# français y accède par sa traduction. Deux radicaux emboîtés (« parameter »
# dans « hyperparameter ») ne sont jamais retenus ensemble : cf. pdf_rag.expand_terms.
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("configuration", "setting", "parameter", "hyperparameter"),
    ("result", "performance", "score"),
    ("method", "approach", "technique"),
    ("model", "network", "architecture"),
    ("training", "learning"),
    ("loss", "objective"),
    ("dataset", "data", "corpus"),
    ("example", "instance", "sample"),
    ("figure", "plot", "curve"),
    ("proof", "demonstration"),
    ("limitation", "weakness", "drawback"),
    ("advantage", "benefit", "strength"),
    ("difference", "comparison"),
    ("definition", "meaning", "notion"),
)


def _build() -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    table: dict[str, tuple[str, ...]] = {}
    for fr, ens in _FR_EN.items():
        table.setdefault(fold(fr), tuple(fold(e) for e in ens))
        for en in ens:
            en = fold(en)
            table.setdefault(en, ())
            if fr not in table[en]:
                table[en] = table[en] + (fold(fr),)
    groups: dict[str, tuple[str, ...]] = {}
    for group in _SYNONYM_GROUPS:
        for word in group:
            groups[word] = tuple(w for w in group if w != word)
    return table, groups


_TABLE, _GROUPS = _build()


def _lookup(table: dict[str, tuple[str, ...]], word: str) -> tuple[str, ...] | None:
    """Entrée d'un mot plié, pluriel toléré (« réseaux », « noyaux » compris)."""
    hit = table.get(word)
    if hit is None and word.endswith("s"):
        hit = table.get(word[:-1])
    if hit is None and word.endswith("x"):
        hit = table.get(word[:-1]) or table.get(word[:-2] + "l")
    return hit


def translations(word: str) -> tuple[str, ...]:
    """Équivalents dans l'autre langue d'un mot plié (« taux » → ("rate",)).
    Vide si le mot est inconnu du lexique."""
    return _lookup(_TABLE, fold(word)) or ()


def synonyms(word: str) -> tuple[str, ...]:
    """Quasi-synonymes d'un mot plié, FR ou EN (« hyperparamètres » →
    ("configuration", "setting", "parameter")). Vide si aucune famille."""
    word = fold(word)
    found: list[str] = []
    for key in (word, *translations(word)):
        for synonym in _lookup(_GROUPS, key) or ():
            if synonym != word and synonym not in found:
                found.append(synonym)
    return tuple(found)
