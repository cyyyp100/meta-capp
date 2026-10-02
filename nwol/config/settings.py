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
# `127.0.0.1` et non `localhost` : Ollama n'écoute que sur l'IPv4 de bouclage.
# `localhost` essaie d'abord `::1`, et Windows met ~2 s à accepter ce refus (il
# retente le SYN) — à chaque génération, à chaque lot d'embeddings.
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
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

# Modèle d'embeddings (recherche sémantique du lecteur, services/pdf_rag) :
# EmbeddingGemma, 300 M de paramètres, multilingue — il relie « taux
# d'apprentissage » à « learning rate » là où la recherche lexicale ne peut pas.
# Optionnel : sans lui (`ollama pull embeddinggemma`), la recherche reste lexicale.
OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embed"
OLLAMA_EMBED_MODEL = "embeddinggemma"
OLLAMA_EMBED_TIMEOUT = 60          # par lot de chunks (le premier appel charge le modèle)

# ── Fournisseur LLM ──────────────────────────────────────────────────────────
# Cette édition est 100 % locale : Ollama sur 127.0.0.1, point d'insertion
# unique dans services/llm_provider.py. Aucune génération ne quitte la machine.

# Options spécifiques par type de tâche LLM
# Permet d'économiser du compute sur les tâches courtes sans sacrifier la précision des tâches complexes.
OLLAMA_TASK_OPTIONS: dict[str, dict] = {
    "curiosity_hook":           {"num_ctx": 2048, "num_predict": 180, "temperature": 0.1},
    "flashcard_tags":           {"num_ctx": 2048, "num_predict": 140, "temperature": 0.1},
    "session_summary":          {"num_ctx": 3072, "num_predict": 360, "temperature": 0.1},
    # num_ctx 6144 (mesuré sur gemma4:e4b, 2026-09-10) : squelette du prompt
    # (guide des types + règles + schéma) ~2300 tokens + paragraphe [:3500] ~950
    # + contexte dynamique (5 dernières réponses en JSON, profil, jauges,
    # difficultés, surlignages) jusqu'à ~1200 + image de page 268 + num_predict
    # 700 ≈ 5400. À 4096, l'image était refusée (exceed_context_size_error →
    # repli texte) ET, dès la 3e page d'une session, le prompt texte seul
    # dépassait aussi : Ollama tronque alors silencieusement le DÉBUT du prompt
    # (rôle, contexte, profil). Les autres tâches avec image gardent ≥ 1200
    # tokens de marge à 4096.
    "question":                 {"num_ctx": 6144, "num_predict": 700, "temperature": 0.1},
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
    # num_ctx élargi : page visible (3500 car. ≈ 1000 tokens) + jusqu'à
    # ASSISTANT_RAG_SEARCH_TOP_K passages de ASSISTANT_RAG_MAX_CHARS (≈ 1200)
    # + consignes (≈ 900) + échanges récents + image de page + num_predict.
    # num_predict 700 : une réponse qui cite les valeurs d'une table et leurs
    # pages dépasse les « 4 à 8 phrases » (mesuré ~420 tokens avec le JSON
    # autour) ; coupée, elle finit en pleine phrase.
    "assistant_answer":         {"num_ctx": 8192, "num_predict": 700, "temperature": 0.1},
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
    # ── Module langue, méthode « feuilleton » (services/lang_episodes.py) ─────────
    # Trois appels étroits par épisode, jamais pendant une séance : l'épisode N+1
    # est écrit pendant la séance N. Température HAUTE pour ce qui doit varier
    # d'un épisode à l'autre (bible, arc, texte : c'est la diversité qui manquait
    # au flux hérité, figé à 0.10), BASSE pour ce qui doit être exact (glossaire,
    # notes, analyse). num_ctx : cf. tests/services/test_lang_prompt_budget.py,
    # qui mesure les prompts sur les cas maximaux (dernier palier, bible complète)
    # et échoue si `prompt + num_predict > num_ctx` (C12, G2).
    "lang_story_bible":         {"num_ctx": 2048, "num_predict": 500,  "temperature": 0.70},
    # Six temps forts et leurs accroches en français : ~110 tokens par épisode
    # au banc (2026-09-24), où 400 coupait l'arc à chaque essai.
    "lang_story_arc":           {"num_ctx": 3072, "num_predict": 800,  "temperature": 0.70},
    # num_predict mesuré au banc (tools/lang_bench.py, 2026-09-24) : à 900, un
    # texte B1 de 17 à 23 répliques était coupé avant son résumé. Une réplique
    # et sa traduction coûtent ~60 tokens au palier le plus long. La génération
    # s'arrête à la fin du JSON : un texte A1 ne paie pas ce plafond.
    "lang_episode_text":        {"num_ctx": 4096, "num_predict": 1600, "temperature": 0.70},
    # Mandarin : les jetons (segmentation) allongent la sortie.
    "lang_episode_text_hanzi":  {"num_ctx": 4096, "num_predict": 1900, "temperature": 0.70},
    # Une entrée par mot inconnu de l'apprenant (au plus LANG_GLOSSARY_MAX_ENTRIES),
    # ~18 tokens chacune en liste compacte.
    "lang_episode_glossary":    {"num_ctx": 4096, "num_predict": 900,  "temperature": 0.20},
    # Notes + explication + micro-exercices : 700 coupait au banc dès l'A2.
    "lang_episode_notes_point": {"num_ctx": 4096, "num_predict": 1000, "temperature": 0.20},
    "lang_weekly_analysis":     {"num_ctx": 2048, "num_predict": 300,  "temperature": 0.20},
    # ── Brainstorming (chat libre + RAG sur la base utilisateur) ────────────────
    # Décision de recherche : JSON court (faut-il chercher + mots-clés).
    "brainstorm_search_decide": {"num_ctx": 2048, "num_predict": 160, "temperature": 0.10},
    # Réponse conversationnelle (texte libre, contexte + sources citées).
    "brainstorm_answer":        {"num_ctx": 4096, "num_predict": 760, "temperature": 0.35},
    # Résumé glissant d'une discussion (mémoire longue compactée).
    "brainstorm_summary":       {"num_ctx": 4096, "num_predict": 360, "temperature": 0.15},
    # Mesure du débit au démarrage (llm/ollama_client.calibrate_throughput) :
    # ~300 tokens lus, 64 écrits — assez pour mesurer, trop peu pour attendre.
    "calibration":              {"num_ctx": 2048, "num_predict": 64, "temperature": 0.1},
}

# ── Budget temps d'une génération ─────────────────────────────────────────────
# Le timeout d'une tâche est DÉRIVÉ de ce qu'elle demande au modèle, pas choisi
# à la main : un `num_predict` de 3000 ne peut pas tenir dans le même budget
# qu'un de 160. Saisir les deux nombres séparément, c'est garantir qu'ils
# divergent — et un timeout applicatif plus long que le timeout socket est une
# échéance que personne n'atteindra jamais.
#
# Débit de RÉFÉRENCE de gemma4:e4b, mesuré sur la machine de dev (Apple
# Silicon, GPU intégré via Metal : ~29 tokens/s écrits, ~265 tokens/s lus).
# Volontairement pessimiste : un budget trop court fait échouer une génération
# correcte, un budget trop long ne coûte que dans le cas déjà anormal.
#
# Ce n'est qu'un point de départ. Une machine plus LENTE (PC sans GPU, Mac
# Intel) est mesurée en cours de route (`llm/throughput.py`) et ses budgets
# sont étirés d'autant ; une machine plus rapide garde ceux-ci.
OLLAMA_TOKENS_PER_S = 18.0
# Lecture du prompt (« prompt eval ») sur la même machine, même marge.
OLLAMA_PROMPT_TOKENS_PER_S = 200.0
# Chargement du modèle à froid + évaluation du prompt, avant le premier token.
OLLAMA_TIMEOUT_OVERHEAD_S = 25.0
# Plafond dur : au-delà, l'utilisateur a déjà renoncé.
OLLAMA_TIMEOUT_MAX = 240.0
# Étirement maximal des budgets sur une machine lente (soit ~2 tokens/s écrits).
# Au-delà, une réponse prendrait plus de dix minutes : on échoue plutôt que de
# laisser l'écran attendre indéfiniment.
OLLAMA_MAX_SLOWDOWN = 8.0


# Une génération JSON peut être rejouée (sortie non conforme -> prompt de
# réparation). Le budget TOTAL d'une tâche couvre ces tentatives : sans ça, la
# boucle de retry et l'appelant qui attend se contredisent, et une deuxième
# tentative sur le point d'aboutir est tuée par un appelant déjà parti.
OLLAMA_RETRY_BUDGET_FACTOR = 2.0
OLLAMA_WALL_TIMEOUT_MAX = 300.0
# Tâche de FOND (épisode de langue, analyse hebdomadaire) : son budget ne court
# qu'une fois partie chez Ollama. Le temps passé en file derrière le lecteur
# (priorités plus hautes, un seul worker) est borné à part, par ce plafond :
# sans lui, un appel d'épisode pouvait expirer avant d'avoir commencé.
OLLAMA_BACKGROUND_QUEUE_WAIT_S = 1800.0


def _slowdown() -> tuple[float, float]:
    """(écriture, lecture) : lenteur MESURÉE de cette machine face à la
    référence, ≥ 1. Import tardif : `llm.throughput` lit les constantes de ce
    module."""
    from llm.throughput import slowdown

    return slowdown()


def task_timeout_s(task: str) -> float:
    """Budget d'UNE tentative, dérivé du `num_predict` de la tâche.

    C'est le timeout socket appliqué par `urlopen` (llm/ollama_client). Une
    tâche inconnue retombe sur les options par défaut. Sur une machine mesurée
    plus lente que la référence, le temps de lecture du prompt, celui
    d'écriture ET le plafond sont étirés du facteur mesuré."""
    options = OLLAMA_TASK_OPTIONS.get(task) or OLLAMA_OPTIONS
    tokens = float(options.get("num_predict") or OLLAMA_OPTIONS["num_predict"])
    gen_slow, prompt_slow = _slowdown()
    budget = OLLAMA_TIMEOUT_OVERHEAD_S * prompt_slow + tokens * gen_slow / OLLAMA_TOKENS_PER_S
    ceiling = OLLAMA_TIMEOUT_MAX * max(gen_slow, prompt_slow)
    return min(ceiling, max(float(OLLAMA_TIMEOUT), budget))


def task_wall_timeout_s(task: str) -> float:
    """Budget TOTAL d'une tâche, tentatives comprises.

    Source unique de DEUX échéances qui doivent rester d'accord : la boucle de
    retry de `_generate_json` cesse de rejouer au-delà, et `run_llm_sync`
    attend exactement ça avant d'abandonner."""
    ceiling = OLLAMA_WALL_TIMEOUT_MAX * max(_slowdown())
    return min(ceiling, task_timeout_s(task) * OLLAMA_RETRY_BUDGET_FACTOR)

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

# ── Module Langues, flux hérité (10 exercices, arc à 4 temps) ─────────────────
# Ces valeurs vivaient en littéraux dans services/lang*.py (défaut n° 9 de
# architecture/18-pipeline-lang.md). Le flux hérité ne sert plus qu'aux langues
# hors pilote ; il n'évolue pas, mais ses seuils suivent la règle du dépôt (C14).
LANG_LEGACY_REVISION_EVERY = 7          # une session de révision imposée toutes les N
LANG_LEGACY_LESSON_SIZE = 10            # exercices par séance
LANG_LEGACY_ARC_TEMPLATE: tuple[str, ...] = (
    ("ancrage",) + ("exposition",) * 3 + ("manipulation",) * 5 + ("cloture",)
)
# Paliers de phase, en séances TERMINÉES.
LANG_LEGACY_WRITING_TO_PASSIVE = 6              # alphabet fini (cyrillique, grec…)
LANG_LEGACY_WRITING_TO_PASSIVE_CONTINUOUS = 12  # script logographique (hanzi, kanji)
LANG_LEGACY_PASSIVE_TO_ACTIVE = 20
# Repli sans LLM du test de niveau : part de QCM réussis -> niveau CECR.
LANG_LEGACY_PLACEMENT_CEFR_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.85, "C1"), (0.70, "B2"), (0.55, "B1"), (0.35, "A2"),
)
LANG_LEGACY_CONTEXT_WORDS = 12          # mots de la séance transmis au prompt suivant
LANG_LEGACY_WEAK_POINTS = 5             # points faibles transmis au prompt
LANG_LEGACY_REVISION_DUE_CARDS = 8      # cartes dues ajoutées à un créneau de révision

# ── Module Langues, méthode « feuilleton » (langues du pilote) ────────────────
# Une séance = un épisode d'un feuilleton, écrit autour d'UN point du programme.
# Tout ce qui suit est lu par services/lang_{runs,episodes,progress,activity}.py
# et nulle part ailleurs redéfini. Valeurs de DÉPART, à calibrer pendant le
# pilote (plan § 6) : chaque constante dit ce qu'elle règle, pas pourquoi cette
# valeur — le pourquoi viendra des mesures (V19).
#
# C1 — périmètre. Les autres langues restent sur le flux hérité (K8).
LANG_PILOT_LANGUAGES: tuple[str, ...] = ("espagnol", "anglais", "allemand", "mandarin", "arabe")
# Famille d'écriture d'une langue du pilote : choisit l'échelle de difficulté,
# les aides à la lecture et les jeux propres au script.
LANG_SCRIPT_FAMILY: dict[str, str] = {
    "espagnol": "latin", "anglais": "latin", "allemand": "latin",
    "mandarin": "hanzi", "arabe": "arabe",
}
# Langue d'explication : celle dans laquelle Clikoda écrit pour l'apprenant
# (traductions, glossaire, notes, point du jour, résumés) et dans laquelle
# s'affichent les données écrites à la main qui ont une version traduite.
# Choisie au début du parcours d'après la langue de l'interface, puis figée dans
# le profil (`lang_profiles.explain_lang`) : un feuilleton ne change pas de
# langue en cours de route. La première de la liste est le repli, et une langue
# ne s'explique jamais dans elle-même (l'anglais s'apprend en français).
LANG_EXPLAIN_LANGUAGES: tuple[str, ...] = ("fr", "en")

# C2 — durées (secondes). Le plafond est strict : au-delà, les étapes non
# essentielles sont sautées et l'au revoir est toujours joué (R24).
LANG_RUN_TARGET_S = 900
LANG_RUN_MAX_S = 1200
LANG_RUN_SHORT_TARGET_S = 480
# Budget indicatif par étape : sert à ordonner ce qu'on saute quand le plafond
# approche, et à la barre de progression. Jamais un compte à rebours affiché.
LANG_STEP_BUDGET_S: dict[str, int] = {
    "rappel": 120, "episode_p1": 210, "episode_p2": 150, "notes": 60,
    "point": 150, "jeux": 180, "deuxieme_vague": 180, "au_revoir": 30,
    "accueil": 120, "phrases": 360, "ecriture": 180, "interets": 90,
    "recap": 240, "relecture": 360, "cartes": 180, "controle": 240, "jalon": 180,
}
# Étapes jamais sautées par le plafond de durée.
LANG_ESSENTIAL_STEPS: tuple[str, ...] = ("episode_p1", "au_revoir")
# Au-delà de ce silence (aucune interaction), le temps n'est plus « effectif ».
LANG_IDLE_CUTOFF_S = 90

# C3 — rythme. Une séance sur LANG_BILAN_EVERY est un bilan : il suit chaque
# bloc de LANG_BILAN_EVERY − 1 = 6 épisodes (un groupe du programme, S2).
LANG_BILAN_EVERY = 7
LANG_SECOND_WAVE_START = 50             # épisode à partir duquel la 2e vague commence
LANG_SECOND_WAVE_OFFSET = 49            # retraduire l'épisode N − 49
LANG_SECOND_WAVE_LINES = (3, 6)         # répliques proposées (min, max)
LANG_MILESTONES_EPISODE_1: tuple[int, ...] = (20, 50, 100)
LANG_ARC_LENGTH = 6                     # épisodes par arc narratif
LANG_RECAP_LONG_EPISODES = 3            # résumés concaténés en rappel long / reprise
LANG_RELECTURE_EPISODES = 2             # épisodes relus en mode relecture
LANG_REPRISE_CONTROLE_EPISODES = 3      # épisodes du mini-contrôle après 21 j
LANG_REWIND_EPISODES = 3                # recul proposé après un contrôle raté
LANG_REPRISE_CONTROLE_OK = 0.6          # part de « su » en dessous de laquelle on propose de reculer

# C4 — échelle de difficulté (§ 9.1). Chaque famille déclare des PALIERS
# d'ancrage ; entre deux paliers, les bornes numériques sont interpolées cran par
# cran (LANG_LADDER_STEPS_PER_TIER crans), les valeurs qualitatives (traduction,
# formes de texte) restent celles du palier inférieur. `None` = libre.
#   lines          : répliques (min, max)
#   words_per_line : mots par réplique (min, max)
#   new_words      : mots nouveaux par épisode (min, max) — caractères pour le hanzi
#   translation    : "toujours" | "masquable" | "masquee_p2" | "tap"
#   formats        : formes de texte autorisées à ce palier (famille latine ;
#                    LANG_TEXT_FORMATS peut les remplacer par langue)
LANG_LADDER_STEPS_PER_TIER = 6
LANG_DIFFICULTY_LADDER: dict[str, tuple[dict, ...]] = {
    "latin": (
        {"tier": "A1", "lines": (6, 8), "words_per_line": (3, 6), "new_words": (5, 7), "translation": "toujours"},
        {"tier": "A1-A2", "lines": (10, 12), "words_per_line": (5, 9), "new_words": (7, 9), "translation": "masquable"},
        {"tier": "A2-B1", "lines": (12, 16), "words_per_line": (8, 12), "new_words": (8, 10), "translation": "masquee_p2"},
        {"tier": "B1-B2", "lines": (15, 20), "words_per_line": None, "new_words": (10, 12), "translation": "tap"},
        {"tier": "B2-C1", "lines": (18, 24), "words_per_line": None, "new_words": (12, 16), "translation": "tap"},
    ),
    # Mandarin : l'axe principal est le nombre de CARACTÈRES nouveaux ; la
    # longueur d'une réplique se compte en caractères.
    "hanzi": (
        {"tier": "A1", "lines": (6, 8), "words_per_line": (4, 10), "new_words": (5, 8), "translation": "toujours"},
        {"tier": "A1-A2", "lines": (8, 10), "words_per_line": (6, 14), "new_words": (6, 9), "translation": "masquable"},
        {"tier": "A2-B1", "lines": (10, 14), "words_per_line": (8, 18), "new_words": (8, 10), "translation": "masquee_p2"},
        {"tier": "B1-B2", "lines": (12, 16), "words_per_line": None, "new_words": (9, 12), "translation": "tap"},
        {"tier": "B2-C1", "lines": (14, 20), "words_per_line": None, "new_words": (10, 14), "translation": "tap"},
    ),
    # Arabe : la longueur suit l'échelle générale ; l'effacement de la
    # vocalisation suit LANG_AR_VOCALIZATION_LEVELS.
    "arabe": (
        {"tier": "A1", "lines": (5, 7), "words_per_line": (2, 5), "new_words": (4, 6), "translation": "toujours"},
        {"tier": "A1-A2", "lines": (8, 10), "words_per_line": (4, 8), "new_words": (6, 8), "translation": "masquable"},
        {"tier": "A2-B1", "lines": (10, 14), "words_per_line": (6, 11), "new_words": (7, 9), "translation": "masquee_p2"},
        {"tier": "B1-B2", "lines": (12, 18), "words_per_line": None, "new_words": (9, 11), "translation": "tap"},
        {"tier": "B2-C1", "lines": (16, 22), "words_per_line": None, "new_words": (10, 14), "translation": "tap"},
    ),
}
# Palier d'ancrage associé à un niveau CECR du programme : un point A1 vit
# entre les paliers 0 et 1, un point B2 entre 3 et 4, etc.
LANG_CEFR_TIER_INDEX: dict[str, int] = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4}
LANG_CEFR_ORDER: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1")
# Le cran réel ne s'écarte jamais de plus de N crans de celui qu'impose la
# position dans le programme : un texte A1 ne porte pas un point B1.
LANG_LADDER_BAND = 3

# C5 — adaptation (signaux déterministes, § 9.2).
LANG_REVEAL_RATE_HIGH = 12.0    # taps / 100 jetons au passage 2 : au-delà, trop dur
LANG_REVEAL_RATE_LOW = 3.0      # en deçà, facile
LANG_GAMES_SUCCESS_EASY = 0.85  # réussite aux jeux et micro-items (items non répondus exclus)
LANG_GAMES_SUCCESS_HARD = 0.5
LANG_SECOND_WAVE_WEIGHT = 0.5   # poids de l'auto-évaluation « su » dans la réussite du jour
LANG_EASY_STREAK_TO_STEP_UP = 2  # « tout facile » deux fois de suite -> un cran de plus
LANG_LADDER_MAX_STEP_PER_EPISODE = 1
LANG_MAX_CONSECUTIVE_RESPIRATION = 2
# Épisode de respiration : moins de mots nouveaux (facteur sur la borne du
# palier), davantage de mots recyclés.
LANG_RESPIRATION_NEW_WORDS_FACTOR = 0.6
LANG_RECYCLE_WORDS = (5, 8)             # mots vus mais non acquis réinjectés dans le texte
LANG_RECYCLE_WORDS_RESPIRATION = (8, 10)
LANG_FORMAT_AVOID_LAST = 2              # ne pas reprendre le format des N derniers épisodes
# Tolérance des validateurs sur les bornes du palier (G4) : un petit modèle rate
# souvent d'une ou deux répliques, et chaque rejet coûte un appel complet.
# (en dessous du minimum, au-dessus du maximum).
LANG_LINES_SLACK = (1, 2)
LANG_WORDS_SLACK = (1, 3)
# Aux paliers « longueur libre », une réplique reste une phrase : au-delà, le
# glossaire et les notes ne tiennent plus dans leur fenêtre de contexte (G2).
LANG_MAX_UNITS_PER_LINE = 40
# Un personnage secondaire hors bible est toléré (le serveur, une touriste),
# pour au plus cette part des répliques.
LANG_EXTRA_SPEAKERS_MAX = 1
LANG_EXTRA_SPEAKER_SHARE = 0.34
# Longueur totale d'un épisode (mots ; caractères pour le hanzi), tous paliers :
# c'est elle qui garantit que glossaire et notes, qui relisent le texte ET sa
# traduction, tiennent dans num_ctx 4096 (G2). Un mot arabe vocalisé (clitiques
# et voyelles compris) coûte près de deux fois les tokens d'un mot espagnol.
# Au-delà, il faudrait élargir num_ctx — et Ollama recharge le modèle à chaque
# changement de fenêtre.
LANG_MAX_UNITS_PER_EPISODE: dict[str, int] = {"latin": 450, "hanzi": 700, "arabe": 300}
# Mots nouveaux (G4/G7) : le contrôle ne s'applique qu'une fois le lexique
# amorcé — au premier épisode, tout est nouveau — et avec une marge.
LANG_NEW_WORDS_CHECK_MIN_LEXICON = 60
LANG_NEW_WORDS_TOLERANCE = 1.5
# Glossaire : mots inconnus de l'apprenant demandés à Clikoda par épisode, par
# palier d'ancrage (index 0-4). Les mots déjà au lexique sont glosés depuis
# le lexique ; au-delà de la borne, le tap montre la traduction de la réplique.
LANG_GLOSSARY_MAX_ENTRIES = (35, 40, 45, 45, 45)
# Mesuré au banc : sur une longue liste, Clikoda s'arrête parfois après UNE
# entrée. Les mots sont donc demandés par lots, et chaque tentative ne
# redemande que ceux qui manquent encore (les entrées valides s'additionnent).
LANG_GLOSSARY_CHUNK = 20
# Part des mots demandés qui peut rester sans entrée (le tap montre alors la
# traduction de la réplique).
LANG_GLOSSARY_MAX_MISSING = 0.1
# Cartes créées par épisode (P12) : les mots touchés au passage 2 d'abord, puis
# les mots nouveaux non transparents. Au-delà, la pile déborde.
LANG_CARDS_PER_EPISODE = 8
LANG_GAMES_AVOID_LAST_RUNS = 2          # ne pas reprendre les jeux des N séances précédentes
LANG_GAMES_PER_RUN = 2
LANG_POINT_MICRO_ITEMS = 3

# C6 — acquisition (mot, puis signe d'écriture). Un mot est acquis après N
# reconnaissances (lu au passage 2 sans le toucher, ou bien répondu dans un jeu)
# réparties sur au moins M épisodes distincts.
LANG_ACQUIRED_RECOGNITIONS = 3
LANG_ACQUIRED_MIN_EPISODES = 2
LANG_SCRIPT_ACQUIRED_RECOGNITIONS = 4
LANG_SCRIPT_ACQUIRED_MIN_EPISODES = 2

# C7 — absence (jours depuis le dernier jour d'étude de CETTE langue).
# (borne haute incluse, palier) ; None = au-delà.
LANG_ABSENCE_TIERS: tuple[tuple[int | None, str], ...] = (
    (2, "normal"), (6, "rappel_long"), (20, "reprise"), (None, "reprise_controle"),
)
LANG_DUE_CARDS_CAP = 15                 # cartes dues servies par séance, les plus anciennes d'abord

# C8 — jour d'étude (décompte par langue, backend seulement, jamais affiché en série).
LANG_STUDY_DAY_CUTOFF_HOUR = 4
LANG_STUDY_DAY_MIN_S = 300

# C9 — pré-génération. L'épisode N+1 part à l'étape LANG_PREGEN_TRIGGER_STEP de
# la séance N, avec les signaux du jour (taps du passage 2 déjà connus).
LANG_PREGEN_BUFFER = 1
LANG_PREGEN_TRIGGER_STEP = "notes"
LANG_GEN_MAX_ATTEMPTS_PER_CALL = 3
# G9 : similarité (Jaccard sur les mots) du titre + résumé avec les N derniers
# épisodes, au-dessus de laquelle l'épisode est rejeté comme redite.
LANG_REPEAT_WINDOW = 20
LANG_REPEAT_MAX_JACCARD = 0.6
# G8 : longueurs maximales des sorties Clikoda (caractères).
LANG_NOTE_MAX_CHARS = 260
LANG_EXPLANATION_MAX_CHARS = 420
LANG_TITLE_MAX_CHARS = 80
LANG_SUMMARY_MAX_CHARS = 220
LANG_TEASER_MAX_CHARS = 160
LANG_NOTES_PER_EPISODE = (3, 5)
LANG_POINT_EXAMPLES = (2, 4)
# G6 : part minimale des lettres arabes portant une voyelle brève ou un sukūn
# (texte « entièrement vocalisé » ; les lettres de prolongation et l'article
# en sont dispensés par le calcul).
LANG_AR_MIN_VOCALIZED_RATIO = 0.8
# Test de niveau : marge de sécurité, en points du programme, en deçà du dernier
# point réussi de façon consécutive (R25).
LANG_PLACEMENT_SAFETY_MARGIN = 3

# C10 — formes de texte par palier d'ancrage (index 0-4), par langue. La fuṣḥā
# n'a pas de conversation naturelle au café : lettres, annonces, récits et
# journal dès le début.
LANG_TEXT_FORMATS: dict[str, tuple[tuple[str, ...], ...]] = {
    "_default": (
        ("dialogue",),
        ("dialogue",),
        ("dialogue", "sms", "lettre"),
        ("dialogue", "sms", "lettre", "article", "journal"),
        ("dialogue", "sms", "lettre", "article", "journal", "recit"),
    ),
    "arabe": (
        ("dialogue", "lettre", "annonce", "recit", "journal"),
        ("dialogue", "lettre", "annonce", "recit", "journal"),
        ("dialogue", "lettre", "annonce", "recit", "journal", "recette"),
        ("dialogue", "lettre", "annonce", "recit", "journal", "recette", "article"),
        ("dialogue", "lettre", "annonce", "recit", "journal", "recette", "article"),
    ),
}
LANG_ALL_TEXT_FORMATS: tuple[str, ...] = (
    "dialogue", "sms", "lettre", "annonce", "recette", "journal", "article", "recit",
)

# C11 — aides à la lecture. Arabe : (niveau CECR, part du niveau déjà parcourue,
# niveau d'aide), lu du plus avancé au moins avancé (§ 13.2) :
#   1 = translittération sous les lettres non acquises + vocalisation complète
#   2 = vocalisation complète        3 = vocalisation des mots non acquis
#   4 = vocalisation au tap
LANG_AR_VOCALIZATION_LEVELS: tuple[tuple[str, float, int], ...] = (
    ("A1", 0.0, 1), ("A1", 0.5, 2), ("A2", 0.0, 3), ("B1", 0.0, 4),
)
LANG_ZH_TONE_COLORS = True      # couleurs de tons (désactivables dans l'écran d'épisode)
LANG_DE_GENDER_COLORS = True    # code couleur der/die/das
# N1 : distance d'édition normalisée lemme ↔ traduction sous laquelle un mot
# est « transparent » ; signalé pendant les N premiers épisodes seulement.
LANG_TRANSPARENT_MAX_DISTANCE = 0.34
LANG_TRANSPARENT_FLAG_UNTIL_EPISODE = 15

# T8-T11 — analyse hebdomadaire : usage interne (ton des messages de rappel et
# de reprise). La montrer à l'apprenant est une décision ouverte (plan § 19.1).
LANG_WEEKLY_ANALYSIS_VISIBLE = False
LANG_WEEKLY_WINDOWS_DAYS = (7, 28)

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
# Titre d'un document renommé depuis la bibliothèque (clic droit → Renommer).
# Même plafond qu'un nom de dossier : les deux s'affichent dans les mêmes
# colonnes (rail, cartes, recherche).
LIBRARY_DOCUMENT_TITLE_MAX = 120
# Plafonds de listage. La bibliothèque est locale et mono-utilisateur : on sert
# tout le catalogue d'un coup et le rail filtre côté client (un déplacement à la
# souris doit être instantané, sans aller-retour réseau).
LIBRARY_MAX_DOCUMENTS = 1000
# Recherche : `LIKE` SQL ne sait pas plier les accents (« equations » doit
# trouver « Équations »). On charge un lot borné et on filtre EN PYTHON, comme
# services/brainstorm_search.
LIBRARY_SEARCH_POOL = 500
LIBRARY_SEARCH_LIMIT = 60
# Document ENVOYÉ par le navigateur (mode sans fenêtre native, services/uploads) :
# copié dans le dossier de données. Plafond large — un manuel scanné dépasse
# vite 100 Mo — mais borné : le corps de la requête arrive en mémoire disque.
UPLOAD_MAX_BYTES = 512 * 1024 * 1024

# Mode navigateur (services/lifecycle) : fermer l'onglet ne dit rien au
# serveur, et sans terminal personne ne peut faire Ctrl+C. Il s'arrête quand
# AUCUN onglet n'est ouvert depuis ce délai — assez long pour un rechargement,
# une navigation ou un navigateur lent à s'ouvrir au premier lancement…
BROWSER_AUTO_STOP_S = 180.0
# …et que Clikoda ne travaille plus depuis celui-ci : une génération de fond
# (épisode de langue) enchaîne plusieurs appels, la file est vide un instant
# entre deux. On ne coupe pas au milieu.
BROWSER_LLM_QUIET_S = 60.0
BROWSER_WATCH_INTERVAL_S = 10.0
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

DB_SCHEMA_VERSION = 36

# Logs
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5

# ── Assistant (bulle Clikoda) : SOURCE DE VÉRITÉ UNIQUE de la cadence ──────────
# Ces constantes sont lues par `services/intervention.py`, l'unique moteur de
# décision d'intervention. Ne jamais redéfinir ces valeurs ailleurs (routeur,
# service) : c'est ce qui avait produit deux politiques divergentes entre l'UI
# Tk et l'UI web. Un test verrouille cette lecture
# (tests/services/test_intervention.py).
ASSISTANT_MODES = ("discret", "normal", "coach")
ASSISTANT_DEFAULT_MODE = "normal"
# Cadence relevée de deux minutes (retour terrain : les questions arrivaient
# trop serrées, même en coach) — le cooldown global est le temps minimal entre
# deux interventions, quelle que soit la page.
ASSISTANT_GLOBAL_COOLDOWN = {"normal": 360.0, "coach": 240.0}
ASSISTANT_PAGE_COOLDOWN = {"normal": 720.0, "coach": 480.0}
ASSISTANT_DWELL_TRIGGER_S = {"normal": 150.0, "coach": 75.0}
# Warm-up : délai d'entrée dans le document pendant lequel aucune intervention
# autonome ne part (les déclencheurs « doux » sont sinon armés dès 30 s de dwell).
# Une minute de plus que la cadence de croisière ne le suggère : on laisse
# l'étudiant s'installer dans sa lecture avant la première question.
ASSISTANT_WARMUP_S = {"normal": 240.0, "coach": 150.0}
ASSISTANT_REVISIT_TRIGGER = 3       # retours sur une même page
ASSISTANT_LOW_ATTENTION = 40.0      # seuil de jauge attention
ASSISTANT_QUESTIONS_TRIGGER = 2     # questions utilisateur sur la même page
ASSISTANT_MAX_INTERVENTIONS = 6     # par session

# Fatigue de production : les réponses de l'étudiant rétrécissent d'une question
# à l'autre. C'est le signal « il n'apprend plus », qui appelle une pause et non
# une question de plus. Lu par `services/intervention.detect_answer_fatigue`.
ASSISTANT_FATIGUE_WINDOW = 3          # réponses consécutives observées
ASSISTANT_FATIGUE_SHRINK_RATIO = 0.55  # dernière / première réponse de la fenêtre
ASSISTANT_FATIGUE_MIN_CHARS = 60      # départ trop court -> on ne conclut rien

# Formules à venir : la page SUIVANTE est dense en mathématiques. Prévenir avant
# d'y arriver est tout l'intérêt du signal, donc il n'est pas soumis au plancher
# de dwell des déclencheurs « doux » — seulement à ce court temps de lecture, qui
# évite de parler pendant un défilement rapide.
ASSISTANT_MATH_AHEAD_DWELL_S = 15.0

# ── Pauses ───────────────────────────────────────────────────────────────────
# Une pause n'est pas du décrochage : l'élève la prend (bouton « Pause ») ou
# accepte celle que Clikoda conseille, et tant qu'il n'a pas repris, TOUT est
# figé — ni dérive passive d'attention, ni dwell, ni intervention, ni horloge de
# cooldown (cf. services/pause.py). La pause est ouverte : elle dure jusqu'au
# retour de l'élève. Seules sa durée et ce qui l'a précédée sont mesurés.
#
# PAUSE_DEFAULT_MIN / PAUSE_MAX_MIN : durée CONSEILLÉE par la carte de Clikoda
# (bornée côté serveur), qui sert de référence au crédit ci-dessous.
PAUSE_DEFAULT_MIN = 5
PAUSE_MAX_MIN = 20
# Crédit d'attention versé au retour d'une pause CONSEILLÉE, au prorata du temps
# pris sur la durée conseillée. Une pause manuelle est neutre pour les jauges.
PAUSE_ATTENTION_RECOVERY = 12.0
# Une pause « suit une recommandation » si une intervention du LLM (ou un
# conseil de séance) est arrivée moins de N secondes avant son début. Le type et
# le délai sont enregistrés tels quels : la fenêtre peut être revue après coup.
PAUSE_RECOMMENDATION_WINDOW_S = 600.0

# Mode focus : interventions coupées pendant N minutes (déclenché depuis le panneau)
FOCUS_DEFAULT_MIN = 25

# ── Attention passive : la jauge bouge PENDANT la lecture ────────────────────
# Avant, `attention` ne bougeait qu'au retour d'une évaluation LLM : elle ne
# mesurait donc que la performance, jamais l'attention. Ces constantes règlent la
# dérive appliquée à chaque tick du lecteur à partir de ce qu'on observe vraiment
# (fenêtre au premier plan, progression dans le document, stagnation sur une page).
# Lues uniquement par `services/session.LiveGauges.apply_reading_behaviour`.
ATTENTION_IDLE_GRACE_S = 90.0        # immobilité (même page, aucun geste) tolérée avant dérive
ATTENTION_ENGAGED_REPORT_S = 10.0    # cadence max. du signal « engaged » envoyé par le lecteur
ATTENTION_DRIFT_PER_MIN = 2.0        # points/min perdus au-delà de la grâce
ATTENTION_AWAY_PER_MIN = 6.0         # points/min perdus fenêtre masquée / hors focus
ATTENTION_PROGRESS_BONUS = 1.2       # points gagnés par nouvelle page lue
ATTENTION_PASSIVE_FLOOR = 15.0       # plancher de la seule dérive passive
ATTENTION_PERSIST_EVERY_S = 60.0     # cadence d'écriture des jauges passives en base

# ── Questions de lecture ────────────────────────────────────────────────────
# La grille des types vit dans config/question_types.py (registre canonique).
# Ici, seulement le levier de mise au point : forcer un type pour vérifier son
# rendu de bout en bout. Vide = tirage adaptatif normal.
#   MC_FORCE_QUESTION_TYPE=ordering python main.py mon.pdf
FORCE_QUESTION_TYPE = os.getenv("MC_FORCE_QUESTION_TYPE", "").strip().lower()

# ── Quiz ─────────────────────────────────────────────────────────────────────
# Longueur d'une session, saisie au nombre près par l'apprenant dans l'écran de
# lancement. Bornes serveur ET frontend : le champ numérique applique MIN/MAX
# (servis par /api/quiz/options), `services.quiz.clamp_quiz_length` re-borne ce
# qui arrive vraiment.
QUIZ_DEFAULT_QUESTIONS = 10
QUIZ_MIN_QUESTIONS = 3
QUIZ_MAX_QUESTIONS = 30
# Filtre par sujet libre (« capitales », « révolution française »). Comme la
# recherche de bibliothèque, `LIKE` ne sait pas plier les accents : on charge un
# lot borné et on filtre EN PYTHON (utils.text.fold).
QUIZ_SEARCH_POOL = 400
QUIZ_SEARCH_MAX_TERMS = 6

# ── Sélection : ne pas resservir toujours les mêmes lignes ───────────────────
# Lues par `services/selection.py` et ses appelants (quiz, sas d'entrée,
# brainstorming). Toutes suivent la même règle : AMORTIR une ligne récemment
# servie, jamais l'EXCLURE — sinon une notion ratée ne pourrait plus revenir vite.
#
# Quiz : une question servie retombe à QUIZ_EXPOSURE_FLOOR de son poids, et
# remonte vers 1.0 en QUIZ_EXPOSURE_HALF_LIFE_DAYS. C'est ce qui fait que deux
# sessions d'affilée sur la même matière ne donnent pas la même liste.
QUIZ_EXPOSURE_HALF_LIFE_DAYS = 3.0
QUIZ_EXPOSURE_FLOOR = 0.15
# Une question déjà ratée reste prioritaire MALGRÉ l'amortissement : le bonus est
# choisi assez grand pour dominer un cooldown frais (2.0 > 1/0.15 n'est pas requis,
# mais 2.0 suffit à la faire ressortir face à ses voisines non ratées).
QUIZ_FAILED_BONUS = 2.0
# Fraîcheur du matériel : le cours de la semaine garde un avantage, mais borné —
# sans plancher, le neuf écrase l'ancien et le stock ne tourne jamais.
QUIZ_FRESHNESS_HALF_LIFE_DAYS = 30.0
QUIZ_FRESHNESS_FLOOR = 0.5

# Sas d'entrée : vivier chargé avant pondération (remplace un `LIMIT 60` qui
# rendait toute carte hors des 60 plus récentes définitivement inatteignable).
FLASHCARD_POOL = 400
FLASHCARD_RECENCY_HALF_LIFE_DAYS = 30.0
FLASHCARD_RECENCY_FLOOR = 0.35
FLASHCARD_SUBJECT_BONUS = 2.0
# `last_reviewed` est déjà écrit par l'échauffement lui-même (WarmUp appelle
# /review) : c'est le signal « vue à la session précédente », jusqu'ici ignoré.
FLASHCARD_REVIEW_COOLDOWN_DAYS = 5.0
FLASHCARD_REVIEW_FLOOR = 0.2

# Brainstorming : plafond d'extraits par type de source (surlignage, flashcard, erreur,
# Q&R, document) et amortissement d'une source DÉJÀ CITÉE dans la discussion.
BRAINSTORM_PER_TYPE_CAP = 2
BRAINSTORM_CITED_FLOOR = 0.2
# Poids d'un terme DISTINCT retrouvé, en base d'exponentielle : un extrait qui
# touche deux mots de la requête pèse 9 contre 3. Il faut une pente franche —
# additive, la pertinence était noyée dès que quelques dizaines de lignes
# matchaient, et seul le hasard départageait.
BRAINSTORM_RELEVANCE_BASE = 3.0
BRAINSTORM_RECENCY_HALF_LIFE_DAYS = 45.0
BRAINSTORM_RECENCY_FLOOR = 0.4
# Discussions épinglées en tête de liste, au plus. La limite est tenue par un
# UPDATE conditionnel (`db/brainstorm.pin_discussion`), pas par l'interface.
BRAINSTORM_MAX_PINNED = 5
# Discussion liée à un dossier : titres de documents du sous-arbre nommés à
# Clikoda dans le prompt (le reste est résumé en « +N »).
BRAINSTORM_SCOPE_TITLES_MAX = 12

# Assistant lecteur : cartes liées proposées au prompt, tirées dans un vivier
# plus large que les 3 finalement citées (sinon toujours les 3 mêmes).
ASSISTANT_FLASHCARD_POOL = 40

# ── RAG plein-document de l'assistant (services/pdf_rag.py) ─────────────────
# Recherche LEXICALE (BM25-lite en Python, < 1 ms) : aucun appel LLM ni modèle
# d'embeddings. Seul coût : le prompt s'allonge des passages cités.
ASSISTANT_RAG_TOP_K = 4            # passages cités pour une question ordinaire
ASSISTANT_RAG_SEARCH_TOP_K = 6     # … quand l'étudiant demande de chercher partout
ASSISTANT_RAG_MAX_CHARS = 700      # longueur max d'un passage dans le prompt
ASSISTANT_RAG_CHUNK_CHARS = 900    # taille cible d'un chunk (phrases entières)
# Un bloc tabulaire (lignes courtes denses en chiffres) est gardé entier jusqu'à
# cette taille : une table coupée en deux ne sert plus à rien au LLM.
ASSISTANT_RAG_TABLE_CHUNK_CHARS = 1800
# Poids des termes des questions précédentes, ajoutés quand la question courante
# est un suivi (« cherche dans tout l'article ») ou trop pauvre en mots-clés.
ASSISTANT_RAG_HISTORY_WEIGHT = 0.5
# La page visible a toujours la priorité : tant qu'elle contient au moins cette
# part des mots-clés de la question, la recherche reste un complément
# (ASSISTANT_RAG_TOP_K). En dessous, la réponse est probablement ailleurs et la
# recherche s'élargit comme sur une demande explicite (ASSISTANT_RAG_SEARCH_TOP_K).
ASSISTANT_RAG_PAGE_COVERAGE = 0.67
# Poids des quasi-synonymes ajoutés à la requête (services/rag_lexicon :
# « hyperparamètres » → « configuration ») : le mot de l'étudiant reste premier.
ASSISTANT_RAG_SYNONYM_WEIGHT = 0.5
# Couche sémantique (embeddings via OLLAMA_EMBED_MODEL), fusionnée au lexical
# par rangs réciproques : score = Σ 1 / (RRF_K + rang). K = 60 est la valeur
# canonique (Cormack et al., 2009) — assez grand pour qu'un passage bien classé
# par une seule des deux listes ne soit pas écrasé par la première place de l'autre.
ASSISTANT_RAG_RRF_K = 60
ASSISTANT_RAG_EMBED_BATCH = 32     # chunks par appel /api/embed à l'indexation
# Similarité cosinus minimale d'un passage pour entrer dans le classement
# sémantique : une question hors sujet (« la capitale de la France ») plafonne
# vers 0.1 sur un article scientifique, une vraie réponse dépasse 0.23.
ASSISTANT_RAG_MIN_SIMILARITY = 0.2
# Après un échec d'embedding (modèle absent, Ollama arrêté), on n'insiste pas
# avant ce délai : chaque question ne doit pas payer un timeout.
ASSISTANT_RAG_EMBED_RETRY_S = 600
