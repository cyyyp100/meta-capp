# config/settings.py — Paramètres globaux MetaC-App
import os
import sys
from pathlib import Path

# Racine du projet (V2/) : config/ → nwol/ → V2/
_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _app_data_dir() -> Path:
    """Dossier de données utilisateur de l'OS (utilisé en app empaquetée)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "Meta-Capp"

# LLM
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma4:e4b"
# Plancher du budget socket d'une génération (voir `task_timeout_s` plus bas :
# le budget réel est DÉRIVÉ du num_predict de la tâche, jamais saisi à la main).
OLLAMA_TIMEOUT = 60
OLLAMA_OPTIONS = {
    "num_ctx": 4096,
    "num_predict": 512,
    "temperature": 0.2,
}

OLLAMA_KEEP_ALIVE = "30m"

# ── Fournisseur LLM ──────────────────────────────────────────────────────────
# Cette édition est 100 % locale : Ollama sur 127.0.0.1, point d'insertion
# unique dans services/llm_provider.py. Aucune génération ne quitte la machine.

# Options spécifiques par type de tâche LLM
# Permet d'économiser du compute sur les tâches courtes sans sacrifier la précision des tâches complexes.
OLLAMA_TASK_OPTIONS: dict[str, dict] = {
    "curiosity_hook":           {"num_ctx": 2048, "num_predict": 180, "temperature": 0.1},
    "flashcard_tags":           {"num_ctx": 2048, "num_predict": 140, "temperature": 0.1},
    "session_summary":          {"num_ctx": 3072, "num_predict": 360, "temperature": 0.1},
    "question":                 {"num_ctx": 4096, "num_predict": 700, "temperature": 0.1},
    "evaluation":               {"num_ctx": 4096, "num_predict": 680, "temperature": 0.1},
    "rephrasing":               {"num_ctx": 4096, "num_predict": 560, "temperature": 0.1},
    "follow_up":                {"num_ctx": 4096, "num_predict": 560, "temperature": 0.1},
    "chapter_summary":          {"num_ctx": 4096, "num_predict": 520, "temperature": 0.1},
    "meta_cognition_questions": {"num_ctx": 4096, "num_predict": 300, "temperature": 0.1},
    "meta_cognition_analysis":  {"num_ctx": 4096, "num_predict": 320, "temperature": 0.1},
    "profile_analysis":         {"num_ctx": 4096, "num_predict": 360, "temperature": 0.2},
    "math_render":              {"num_ctx": 4096, "num_predict": 900, "temperature": 0.1},
    # Fiche d'un document à l'import : matière + résumé + mots-clés en UN appel.
    # num_ctx 3072 : extrait de 2400 caractères (~700 tokens) + consigne + les 25
    # matières. num_predict 260 : la sortie utile tient en ~130 tokens, on garde
    # le double pour ne jamais tronquer. temperature 0.15 : la matière est une
    # classification, mais le résumé doit rester une phrase lisible.
    "document_digest":          {"num_ctx": 3072, "num_predict": 260, "temperature": 0.15},
    # num_ctx élargi : page visible (3500 car.) + passages RAG plein-document.
    "assistant_answer":         {"num_ctx": 6144, "num_predict": 560, "temperature": 0.1},
    "assistant_intervention":   {"num_ctx": 3072, "num_predict": 220, "temperature": 0.1},
    "flashcard_standalone":     {"num_ctx": 3072, "num_predict": 260, "temperature": 0.1},
    # Génération batch des distracteurs de QCM (~10 questions en un seul appel).
    "quiz_distractors":         {"num_ctx": 4096, "num_predict": 1200, "temperature": 0.3},
    "quiz_analysis":            {"num_ctx": 4096, "num_predict": 420, "temperature": 0.2},
    # ── Module langue ──────────────────────────────────────────────────────────
    "lang_curriculum":    {"num_ctx": 4096, "num_predict": 3000, "temperature": 0.15},
    "lang_curiosity":     {"num_ctx": 2048, "num_predict": 200,  "temperature": 0.15},
    "lang_lesson":        {"num_ctx": 4096, "num_predict": 2000, "temperature": 0.10},
    "lang_exercises":     {"num_ctx": 3072, "num_predict": 800,  "temperature": 0.10},
    "lang_correction":    {"num_ctx": 2048, "num_predict": 400,  "temperature": 0.10},
    "lang_revision_quiz": {"num_ctx": 3072, "num_predict": 800,  "temperature": 0.10},
    # ── Séquenceur adaptatif de sessions ───────────────────────────────────────
    # Choix du type de session : JSON minuscule (2 champs) -> appel très court.
    "lang_session_select":   {"num_ctx": 2048, "num_predict": 160,  "temperature": 0.10},
    # Plan d'une séance (10 slots, arc 4 temps) : thème + liste de types -> court.
    "lang_lesson_plan":      {"num_ctx": 2048, "num_predict": 320,  "temperature": 0.20},
    # Test de niveau (12-15 items, difficulté croissante). num_predict borné pour
    # tenir dans le timeout sur gemma4:e4b même à froid (le parser récupère un test
    # partiel si la génération est tronquée).
    "lang_placement":        {"num_ctx": 3072, "num_predict": 1300, "temperature": 0.15},
    # Estimation CEFR à partir des réponses au test -> JSON court.
    "lang_placement_eval":   {"num_ctx": 3072, "num_predict": 280,  "temperature": 0.10},
    # Génération du contenu d'UNE session, scope réduit, paramétré par render_kind.
    "lang_content_dialogue":   {"num_ctx": 4096, "num_predict": 1300, "temperature": 0.10},
    "lang_content_reading":    {"num_ctx": 4096, "num_predict": 1400, "temperature": 0.10},
    "lang_content_vocab":      {"num_ctx": 3072, "num_predict": 1000, "temperature": 0.10},
    "lang_content_phonetics":  {"num_ctx": 3072, "num_predict": 900,  "temperature": 0.10},
    "lang_content_translation":{"num_ctx": 3072, "num_predict": 900,  "temperature": 0.10},
    "lang_content_dictation":  {"num_ctx": 3072, "num_predict": 900,  "temperature": 0.10},
    "lang_content_production": {"num_ctx": 3072, "num_predict": 1000, "temperature": 0.15},
    # Intégration de l'écriture (scripts non-latins) : table de signes + mots + drill.
    "lang_content_writing":    {"num_ctx": 3072, "num_predict": 1100, "temperature": 0.10},
    # Types interactifs (correction côté client) : structures courtes, pas de gros budget.
    "lang_content_cloze":      {"num_ctx": 3072, "num_predict": 800,  "temperature": 0.10},
    "lang_content_ordering":   {"num_ctx": 3072, "num_predict": 800,  "temperature": 0.10},
    "lang_content_matching":   {"num_ctx": 2048, "num_predict": 700,  "temperature": 0.10},
    "lang_content_transform":  {"num_ctx": 3072, "num_predict": 900,  "temperature": 0.10},
    # ── Brainstorming (chat libre + RAG sur la base utilisateur) ────────────────
    # Décision de recherche : JSON court (faut-il chercher + mots-clés).
    "brainstorm_search_decide": {"num_ctx": 2048, "num_predict": 160, "temperature": 0.10},
    # Réponse conversationnelle (texte libre, contexte + sources citées).
    "brainstorm_answer":        {"num_ctx": 4096, "num_predict": 760, "temperature": 0.35},
    # Résumé glissant d'une discussion (mémoire longue compactée).
    "brainstorm_summary":       {"num_ctx": 4096, "num_predict": 360, "temperature": 0.15},
}

# ── Budget temps d'une génération ─────────────────────────────────────────────
# Le timeout d'une tâche est DÉRIVÉ de ce qu'elle demande au modèle, pas choisi
# à la main : un `num_predict` de 3000 ne peut pas tenir dans le même budget
# qu'un de 160. Saisir les deux nombres séparément, c'est garantir qu'ils
# divergent — et un timeout applicatif plus long que le timeout socket est une
# échéance que personne n'atteindra jamais.
#
# Débit mesuré sur gemma4:e4b (machine de dev, sans GPU dédié). Volontairement
# pessimiste : un budget trop court fait échouer une génération correcte, un
# budget trop long ne coûte que dans le cas déjà anormal.
OLLAMA_TOKENS_PER_S = 18.0
# Chargement du modèle à froid + évaluation du prompt, avant le premier token.
OLLAMA_TIMEOUT_OVERHEAD_S = 25.0
# Plafond dur : au-delà, l'utilisateur a déjà renoncé.
OLLAMA_TIMEOUT_MAX = 240.0


# Une génération JSON peut être rejouée (sortie non conforme -> prompt de
# réparation). Le budget TOTAL d'une tâche couvre ces tentatives : sans ça, la
# boucle de retry et l'appelant qui attend se contredisent, et une deuxième
# tentative sur le point d'aboutir est tuée par un appelant déjà parti.
OLLAMA_RETRY_BUDGET_FACTOR = 2.0
OLLAMA_WALL_TIMEOUT_MAX = 300.0


def task_timeout_s(task: str) -> float:
    """Budget d'UNE tentative, dérivé du `num_predict` de la tâche.

    C'est le timeout socket appliqué par `urlopen` (llm/ollama_client). Une
    tâche inconnue retombe sur les options par défaut."""
    options = OLLAMA_TASK_OPTIONS.get(task) or OLLAMA_OPTIONS
    tokens = float(options.get("num_predict") or OLLAMA_OPTIONS["num_predict"])
    budget = OLLAMA_TIMEOUT_OVERHEAD_S + tokens / OLLAMA_TOKENS_PER_S
    return min(OLLAMA_TIMEOUT_MAX, max(float(OLLAMA_TIMEOUT), budget))


def task_wall_timeout_s(task: str) -> float:
    """Budget TOTAL d'une tâche, tentatives comprises.

    Source unique de DEUX échéances qui doivent rester d'accord : la boucle de
    retry de `_generate_json` cesse de rejouer au-delà, et `run_llm_sync`
    attend exactement ça avant d'abandonner."""
    return min(OLLAMA_WALL_TIMEOUT_MAX, task_timeout_s(task) * OLLAMA_RETRY_BUDGET_FACTOR)

# ── Systèmes d'écriture (module Langues) ──────────────────────────────────────
# Taxonomie des scripts : chaque entrée porte les propriétés qui PILOTENT le
# comportement pédagogique et la consigne (`hint`) injectée dans tous les prompts
# de langue pour forcer le bon alphabet + la translittération.
#   kind        : "alphabetic" | "syllabary" | "logographic" | "abjad" | "abugida"
#   rtl         : écriture de droite à gauche (rendu front + consigne LLM)
#   tonal       : tons phonémiques (pinyin tonsé, paires minimales de tons)
#   continuous  : caractères jamais « finis » (logographique) → enseignés en continu,
#                 même après la phase d'écriture (cf. services/lang_sequencer.plan_lesson)
#   romanization: libellé de la translittération attendue dans 'phonetic'/'translit'
LATIN_SCRIPT = "latin"
SCRIPTS: dict[str, dict] = {
    "latin": {
        "kind": "alphabetic", "rtl": False, "tonal": False, "continuous": False,
        "romanization": None, "hint": "",
    },
    "cyrillic": {
        "kind": "alphabetic", "rtl": False, "tonal": False, "continuous": False,
        "romanization": "translittération latine",
        "hint": (
            " La langue cible s'écrit en alphabet CYRILLIQUE : écris TOUT le texte cible "
            "(champs 'target'/'word'/'expected'/'a'/'b'/'sign') en cyrillique, jamais en "
            "translittération latine, et donne systématiquement la translittération "
            "latine dans le champ 'phonetic'/'translit' quand il existe."
        ),
    },
    "greek": {
        "kind": "alphabetic", "rtl": False, "tonal": False, "continuous": False,
        "romanization": "translittération latine",
        "hint": (
            " La langue cible s'écrit en alphabet GREC : écris TOUT le texte cible en "
            "caractères grecs, jamais en translittération latine, et donne la "
            "translittération latine dans le champ 'phonetic'/'translit' quand il existe."
        ),
    },
    "hangul": {
        "kind": "syllabary", "rtl": False, "tonal": False, "continuous": False,
        "romanization": "romanisation révisée",
        "hint": (
            " La langue cible s'écrit en HANGUL (jamo composés en blocs syllabiques) : "
            "écris TOUT le texte cible en hangul, jamais en romanisation latine, et donne "
            "la romanisation latine dans le champ 'phonetic'/'translit' quand il existe."
        ),
    },
    "hanzi": {
        "kind": "logographic", "rtl": False, "tonal": True, "continuous": True,
        "romanization": "pinyin (avec tons)",
        "hint": (
            " La langue cible (mandarin) s'écrit en caractères HAN (hanzi) : écris TOUT le "
            "texte cible en caractères chinois simplifiés, jamais en pinyin seul. Donne "
            "TOUJOURS le pinyin AVEC les marques de ton (mā má mǎ mà, jamais ma1/ma2) dans "
            "le champ 'phonetic'/'translit'. Le ton fait partie du mot : ne l'omets jamais."
        ),
    },
    "japanese": {
        "kind": "logographic", "rtl": False, "tonal": False, "continuous": True,
        "romanization": "rōmaji",
        "hint": (
            " La langue cible (japonais) mêle KANA (hiragana/katakana) et KANJI : écris le "
            "texte cible dans l'écriture japonaise normale (kana + kanji selon l'usage), "
            "jamais en rōmaji seul, et donne le rōmaji dans le champ 'phonetic'/'translit'. "
            "Pour l'intégration de l'écriture, présente d'ABORD les kana avant les kanji."
        ),
    },
    "arabic": {
        "kind": "abjad", "rtl": True, "tonal": False, "continuous": False,
        "romanization": "translittération latine",
        "hint": (
            " La langue cible s'écrit en alphabet ARABE, de DROITE À GAUCHE, avec des "
            "formes contextuelles des lettres (initiale/médiane/finale) : écris TOUT le "
            "texte cible en caractères arabes (avec les voyelles brèves/harakat pour un "
            "débutant), jamais en translittération latine, et donne la translittération "
            "latine dans le champ 'phonetic'/'translit' quand il existe."
        ),
    },
    "hebrew": {
        "kind": "abjad", "rtl": True, "tonal": False, "continuous": False,
        "romanization": "translittération latine",
        "hint": (
            " La langue cible s'écrit en alphabet HÉBREU, de DROITE À GAUCHE : écris TOUT "
            "le texte cible en caractères hébreux (avec les points-voyelles/nikoud pour un "
            "débutant), jamais en translittération latine, et donne la translittération "
            "latine dans le champ 'phonetic'/'translit' quand il existe."
        ),
    },
    "devanagari": {
        "kind": "abugida", "rtl": False, "tonal": False, "continuous": False,
        "romanization": "translittération latine (IAST)",
        "hint": (
            " La langue cible s'écrit en DEVANAGARI (abugida : consonne portant une "
            "voyelle inhérente + signes-voyelles) : écris TOUT le texte cible en "
            "devanagari, jamais en translittération latine, et donne la translittération "
            "latine dans le champ 'phonetic'/'translit' quand il existe."
        ),
    },
    "thai": {
        "kind": "abugida", "rtl": False, "tonal": True, "continuous": False,
        "romanization": "translittération latine",
        "hint": (
            " La langue cible (thaï) s'écrit en alphabet THAÏ (abugida, sans espaces entre "
            "les mots) et possède des TONS : écris TOUT le texte cible en caractères thaïs, "
            "jamais en translittération latine, et donne la translittération latine AVEC "
            "indication du ton dans le champ 'phonetic'/'translit'."
        ),
    },
}

# Script intrinsèque à chaque langue (clé = code langue, valeur = clé de SCRIPTS).
# Les scripts non-latins déclenchent la phase « intégration de l'écriture » et,
# pour les scripts logographiques (continuous), une introduction continue des
# caractères dans toutes les phases.
LANGUAGE_SCRIPTS: dict[str, str] = {
    "anglais": "latin",
    "espagnol": "latin",
    "allemand": "latin",
    "italien": "latin",
    "portugais": "latin",
    "néerlandais": "latin",
    "polonais": "latin",
    "suédois": "latin",
    "turc": "latin",
    "roumain": "latin",
    "indonésien": "latin",
    "vietnamien": "latin",
    "russe": "cyrillic",
    "grec": "greek",
    "coréen": "hangul",
    "mandarin": "hanzi",
    "japonais": "japanese",
    "arabe": "arabic",
    "hébreu": "hebrew",
    "hindi": "devanagari",
    "thaï": "thai",
}
# Langues à tons portés par la LANGUE et non par le script (latin tonal).
TONAL_LANGUAGES: set[str] = {"vietnamien"}
# Consignes de script dérivées (compat. ascendante de `_lang_script_hint`).
SCRIPT_HINTS: dict[str, str] = {key: meta["hint"] for key, meta in SCRIPTS.items()}

# Vitesse de lecture progressive par défaut (ms/caractère), servie par
# db.user.get_user_speed quand l'utilisateur n'en a pas choisi une.
READING_SPEED_INITIAL_MS = 500

# Chapitres heuristiques (si pas de TOC)
DEFAULT_PAGES_PER_CHAPTER = 10

# ── Bibliothèque : dossiers utilisateur et classification automatique ────────
# Profondeur maximale de l'arbre : au-delà, le rail latéral n'est plus lisible
# et un déplacement à la souris devient irrattrapable.
LIBRARY_MAX_FOLDER_DEPTH = 6
LIBRARY_FOLDER_NAME_MAX = 80
# Plafonds de listage. La bibliothèque est locale et mono-utilisateur : on sert
# tout le catalogue d'un coup et le rail filtre côté client (un déplacement à la
# souris doit être instantané, sans aller-retour réseau).
LIBRARY_MAX_DOCUMENTS = 1000
# Recherche : `LIKE` SQL ne sait pas plier les accents (« equations » doit
# trouver « Équations »). On charge un lot borné et on filtre EN PYTHON, comme
# services/brainstorm_search.
LIBRARY_SEARCH_POOL = 500
LIBRARY_SEARCH_LIMIT = 60
# Poids de pertinence. Le nom de fichier est le signal le plus fort (ce que
# l'utilisateur tape quand il SAIT), les mots-clés viennent juste après (ce
# qu'il tape quand il ne sait pas), le résumé et la matière départagent.
LIBRARY_SEARCH_WEIGHT_FILENAME = 3
LIBRARY_SEARCH_WEIGHT_KEYWORD = 2
LIBRARY_SEARCH_WEIGHT_SUMMARY = 1
LIBRARY_SEARCH_WEIGHT_SUBJECT = 1

# Fiche LLM d'un document (matière + résumé + mots-clés), jouée une seule fois à
# l'import. Remplace l'ancienne détection de matière seule.
DOCUMENT_DIGEST_EXCERPT_PAGES = 3
DOCUMENT_DIGEST_EXCERPT_CHARS = 4000
DOCUMENT_DIGEST_PROMPT_CHARS = 2400
DOCUMENT_SUMMARY_MAX_CHARS = 220
DOCUMENT_KEYWORDS_MAX = 6

# Base de données, logs et assets : en app empaquetée (gelée) -> données
# utilisateur de l'OS (persistent entre mises à jour, _MEIPASS est en lecture
# seule) ; en dev -> arborescence du projet (inchangé). [F1]
if getattr(sys, "frozen", False):
    _DATA_DIR = _app_data_dir()
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH = str(_DATA_DIR / "nwol.db")
    LOG_FILE = str(_DATA_DIR / "logs" / "nwol.log")
    ASSETS_DIR = str(_DATA_DIR / "assets")
else:
    DB_PATH = str(_PROJECT_ROOT / "data" / "nwol.db")
    LOG_FILE = str(_PROJECT_ROOT / "logs" / "nwol.log")
    ASSETS_DIR = str(_PROJECT_ROOT / "nwol" / "assets")

# Redirection de la base par l'environnement. Les tests pytest monkeypatchent
# `db.DB_PATH` en mémoire, ce qui suppose de vivre dans le même processus ; les
# parcours Playwright lancent un VRAI serveur, et écriraient donc dans la
# bibliothèque de l'utilisateur. Même mécanisme que NWOL_IMPORT_ROOTS.
# Jamais honoré en app empaquetée : là, l'emplacement des données est imposé.
if not getattr(sys, "frozen", False):
    _db_override = os.environ.get("NWOL_DB_PATH")
    if _db_override:
        DB_PATH = str(Path(_db_override).expanduser().resolve())

DB_SCHEMA_VERSION = 26

# Logs
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5

# ── Assistant (bulle Gemma) : SOURCE DE VÉRITÉ UNIQUE de la cadence ──────────
# Ces constantes sont lues par `services/intervention.py`, l'unique moteur de
# décision d'intervention. Ne jamais redéfinir ces valeurs ailleurs (routeur,
# service) : c'est ce qui avait produit deux politiques divergentes entre l'UI
# Tk et l'UI web. Un test verrouille cette lecture
# (tests/services/test_intervention.py).
ASSISTANT_MODES = ("discret", "normal", "coach")
ASSISTANT_DEFAULT_MODE = "normal"
ASSISTANT_GLOBAL_COOLDOWN = {"normal": 240.0, "coach": 120.0}
ASSISTANT_PAGE_COOLDOWN = {"normal": 600.0, "coach": 360.0}
ASSISTANT_DWELL_TRIGGER_S = {"normal": 150.0, "coach": 75.0}
# Warm-up : délai d'entrée dans le document pendant lequel aucune intervention
# autonome ne part (les déclencheurs « doux » sont sinon armés dès 30 s de dwell).
ASSISTANT_WARMUP_S = {"normal": 180.0, "coach": 90.0}
ASSISTANT_REVISIT_TRIGGER = 3       # retours sur une même page
ASSISTANT_LOW_ATTENTION = 40.0      # seuil de jauge attention
ASSISTANT_QUESTIONS_TRIGGER = 2     # questions utilisateur sur la même page
ASSISTANT_MAX_INTERVENTIONS = 6     # par session

# Mode focus : interventions coupées pendant N minutes (déclenché depuis le panneau)
FOCUS_DEFAULT_MIN = 25

# ── Questions de lecture ────────────────────────────────────────────────────
# La grille des types vit dans config/question_types.py (registre canonique).
# Ici, seulement le levier de mise au point : forcer un type pour vérifier son
# rendu de bout en bout. Vide = tirage adaptatif normal.
#   MC_FORCE_QUESTION_TYPE=ordering python main.py mon.pdf
FORCE_QUESTION_TYPE = os.getenv("MC_FORCE_QUESTION_TYPE", "").strip().lower()
