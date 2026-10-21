# config/settings.py — Paramètres globaux MetaC-App
import os
import sys
from dataclasses import dataclass
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
# Modèle de DERNIER RECOURS, et non le modèle en dur qu'il fut : celui qui tourne
# est une préférence (`llm_model`, défaut « auto »), résolue par
# `services/llm_models.py` d'après les modèles qu'Ollama a en magasin et la RAM de
# la machine. Ce nom-ci répond à deux questions : quel modèle citer quand Ollama
# n'en liste aucun (« ollama pull … » a besoin d'un nom), et quel profil sert de
# RÉFÉRENCE aux débits mesurés (LLM_REFERENCE_PROFILE, plus bas).
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
    # num_ctx 6144, comme `question` (mesuré le 2026-10-12) : avec l'image de la
    # page, le prompt atteint 3558 tokens ; + 680 réservés en sortie, il
    # dépassait 4096 et Ollama en tronquait le DÉBUT sans rien dire. Même
    # contexte que la question qui la précède : pas de rechargement du modèle.
    "evaluation":               {"num_ctx": 6144, "num_predict": 680, "temperature": 0.1},
    "rephrasing":               {"num_ctx": 4096, "num_predict": 560, "temperature": 0.1},
    "chapter_summary":          {"num_ctx": 4096, "num_predict": 520, "temperature": 0.1},
    "meta_cognition_analysis":  {"num_ctx": 4096, "num_predict": 320, "temperature": 0.1},
    "profile_analysis":         {"num_ctx": 4096, "num_predict": 360, "temperature": 0.2},
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
    # num_predict 320 (mesuré le 2026-10-12) : 2 réponses sur 8 atteignaient le
    # plafond de 220 et arrivaient coupées en plein JSON. Prompt ~1700 tokens.
    "assistant_intervention":   {"num_ctx": 3072, "num_predict": 320, "temperature": 0.1},
    "flashcard_standalone":     {"num_ctx": 3072, "num_predict": 260, "temperature": 0.1},
    # Règles de langue d'une carte manuelle (services/flashcards) : six champs
    # courts en JSON structuré, ~60 tokens — le double pour ne jamais couper.
    # Prompt ~500 tokens au pire (deux faces de MANUAL_CARD_LANG_MAX_CHARS).
    "flashcard_lang_rules":     {"num_ctx": 2048, "num_predict": 160, "temperature": 0.1},
    # Génération batch des distracteurs de QCM (~10 questions en un seul appel).
    "quiz_distractors":         {"num_ctx": 4096, "num_predict": 1200, "temperature": 0.3},
    "quiz_analysis":            {"num_ctx": 4096, "num_predict": 420, "temperature": 0.2},
    # ── Module langue ──────────────────────────────────────────────────────────
    "lang_correction":    {"num_ctx": 2048, "num_predict": 400,  "temperature": 0.10},
    "lang_revision_quiz": {"num_ctx": 3072, "num_predict": 800,  "temperature": 0.10},
    # ── Séances du flux hérité ─────────────────────────────────────────────────
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
    # num_ctx 5120 pour les cinq tâches de contenu d'un épisode (texte,
    # glossaire, notes) et la leçon qui le suit : mesuré le 2026-10-13, un
    # épisode arabe maximal laissait 46 tokens de marge RÉELLE au glossaire dans
    # 4096, et l'estimation pessimiste corrigée (l'arabe vocalisé coûte 0,6
    # token par caractère, pas 0,5) ne l'y faisait plus tenir. Les six partagent
    # la même fenêtre : aucun rechargement du modèle entre elles. Un modèle qui
    # ne tient pas 5120 (le palier minuscule, 4096) est plafonné par
    # `task_options`, et ses épisodes sont raccourcis en conséquence
    # (`max_units_per_episode`).
    # num_predict mesuré au banc (tools/lang_bench.py, 2026-09-24) : à 900, un
    # texte B1 de 17 à 23 répliques était coupé avant son résumé. Une réplique
    # et sa traduction coûtent ~60 tokens au palier le plus long. La génération
    # s'arrête à la fin du JSON : un texte A1 ne paie pas ce plafond.
    "lang_episode_text":        {"num_ctx": 5120, "num_predict": 1600, "temperature": 0.70},
    # Mandarin : les jetons (segmentation) allongent la sortie.
    "lang_episode_text_hanzi":  {"num_ctx": 5120, "num_predict": 1900, "temperature": 0.70},
    # Une entrée par mot inconnu de l'apprenant (au plus LANG_GLOSSARY_CHUNK par
    # appel), ~20 tokens chacune en liste compacte, sens du lemme compris.
    "lang_episode_glossary":    {"num_ctx": 5120, "num_predict": 900,  "temperature": 0.20},
    # Langues latines : ~10 tokens de plus par entrée pour la prononciation en API
    # qu'écrit Clikoda (le pinyin et la translittération arabe sont calculés).
    # Banc du 12 octobre (lots de 20 mots, sens du lemme compris) : 549 tokens en
    # moyenne, 937 au plus — un lot dont les « expressions » étaient des phrases
    # entières, chacune écrite cinq fois. 1 100 est le plafond qui garde le prompt
    # du pire cas dans num_ctx (tests/services/test_lang_prompt_budget.py) ; une
    # coupure ne toucherait que les expressions, écrites après les entrées.
    "lang_episode_glossary_pron": {"num_ctx": 5120, "num_predict": 1100, "temperature": 0.20},
    # Notes + explication + micro-exercices : 700 coupait au banc dès l'A2.
    "lang_episode_notes_point": {"num_ctx": 5120, "num_predict": 1000, "temperature": 0.20},
    "lang_weekly_analysis":     {"num_ctx": 2048, "num_predict": 300,  "temperature": 0.20},
    # Leçon d'un point, une fois par point et par langue d'explication, après
    # l'épisode qui l'introduit : règle, formes, emplois, pièges, exemples.
    "lang_point_lesson":        {"num_ctx": 5120, "num_predict": 1500, "temperature": 0.30},
    # Correction d'une expression écrite : trois erreurs au plus et le texte corrigé.
    "lang_writing_feedback":    {"num_ctx": 4096, "num_predict": 1000, "temperature": 0.20},
    # Accroche du sas d'entrée, écrite pendant le sas : une phrase (~60 tokens
    # JSON compris), le double pour ne jamais la couper. Un peu de température :
    # elle doit donner envie, pas résumer.
    "lang_episode_hook":        {"num_ctx": 2048, "num_predict": 160,  "temperature": 0.40},
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

# ── Catalogue des modèles ─────────────────────────────────────────────────────
# Le modèle n'est plus un nom en dur : c'est une donnée. Cette table est le SEUL
# endroit où un modèle existe — ce qu'il pèse à télécharger, la RAM qu'il exige,
# ce qu'il écrit par seconde, le contexte qu'il tient. La politique (« lequel
# faire tourner ? ») vit dans `services/llm_models.py` ; ici, les faits.
#
# `min_ram_gb` est la RAM de la MACHINE, pas la taille du fichier : Ollama garde
# les poids résidents, le cache KV de 8192 tokens coûte 0,5 à 1,5 Go de plus, et
# l'OS plus le webview en prennent ~3. D'où 9,6 Go de poids → 12 Go exigés, et
# 18-20 → 32. Un 26b sur un Mac de 24 Go swappe et son premier token prend des
# minutes : que le choix automatique le refuse est précisément le but.
#
# `rank` est l'ordre de PRÉFÉRENCE, et il ne se déduit d'aucun autre champ :
# `gemma4:12b` se télécharge plus petit que `gemma4:e4b` (8,0 contre 9,6) tout en
# répondant mieux et en écrivant moins vite — e4b est une tranche MatFormer à
# 4 B actifs, 12b un dense de 12 B. « Le plus gros qui tient » trie donc sur
# `rank`, jamais sur `download_gb` ni sur la RAM.
#
# Pas de champ `label` : l'étiquette lue à l'écran se construit côté interface
# depuis `tier` et `download_gb`, pour que les mots vivent dans les deux
# dictionnaires i18n et non dans un dict Python.
#
# Le palier « tiny » est hors gemma4, et ce n'est pas un choix de goût : aucune
# variante de gemma4 ne tient dans 4 Gio (`gemma4:e2b` pèse 7,2 Go — le « e »
# réduit le calcul, pas les poids résidents). `qwen3:1.7b` (1,4 Go) a été retenu
# pour son avance en suivi de consignes sur `gemma3:1b` ; le payload envoie déjà
# `"think": false`, qui coupe son mode raisonnement. Mesuré le 2026-10-13 sur un
# Apple M4 : 70 tokens/s écrits, ~740 lus, 0,6 s de chargement à froid, et un
# JSON exploitable sur la question, l'évaluation, la réponse et l'accroche du
# lecteur (8 essais sur 8). La table en retient 42 et 540, pessimistes comme les
# autres lignes. Son contexte est plafonné à 4096 : c'est ce qui lui permet de
# tenir dans `min_ram_gb` (1,75 Gio chargé à 4096, mesuré par `/api/ps`).
#
# `tokenizer` : le même texte ne coûte pas le même nombre de tokens à tous les
# modèles (qwen3 compte ~18 % de plus que Gemma en français, 33 % de plus en
# arabe vocalisé). Les budgets de prompt s'estiment par tokenizer
# (PROMPT_TOKEN_WEIGHTS, plus bas), sans quoi un budget vérifié pour Gemma
# déborderait en silence sur qwen3.
LLM_MODEL_AUTO = "auto"


@dataclass(frozen=True)
class ModelProfile:
    """Ce qu'il faut savoir d'un modèle pour décider s'il peut tourner et
    combien de temps lui accorder.

    Les débits sont ceux de la machine de RÉFÉRENCE (Apple Silicon, GPU intégré
    via Metal), volontairement pessimistes. La lenteur de la machine réelle est
    mesurée à part (`llm/throughput.py`) et se multiplie à ceux-ci : la taille du
    modèle et la vitesse de la machine sont deux facteurs distincts, et les
    confondre dépensait pour la première le plafond prévu pour la seconde."""

    name: str
    rank: int                   # ordre de préférence (le plus grand gagne en AUTO)
    tier: str                   # "tiny" | "small" | "standard" | "large"
    download_gb: float          # ce que « ollama pull » télécharge
    min_ram_gb: float           # RAM TOTALE de la machine, cf. ci-dessus
    tokens_per_s: float         # écriture, sur la machine de référence
    prompt_tokens_per_s: float  # lecture du prompt, idem
    load_overhead_s: float      # chargement à froid + évaluation du prompt
    max_num_ctx: int            # plafond appliqué au num_ctx de chaque tâche
    supports_images: bool       # page du PDF envoyée au modèle, ou écartée
    tokenizer: str              # clé de PROMPT_TOKEN_WEIGHTS


LLM_MODELS: dict[str, ModelProfile] = {
    name: ModelProfile(name, *fields)
    for name, fields in {
        #  nom          rank  tier          dl    ram  tok/s  prompt charge  ctx  images tokenizer
        "qwen3:1.7b": (1, "tiny",      1.4,  4.0, 42.0, 540.0, 10.0, 4096, False, "qwen"),
        "gemma4:e2b": (2, "small",     7.2,  8.0, 22.0, 240.0, 20.0, 8192, True,  "gemma"),
        "gemma4:e4b": (3, "standard",  9.6, 12.0, 18.0, 200.0, 25.0, 8192, True,  "gemma"),
        # Débits MESURÉS le 2026-10-15 sur l'Apple M4 de 16 Go (journal du
        # calibrage) : 11,9 tokens/s écrits et 89 lus, contre 29,7 et 255 pour
        # e4b. L'ancienne ligne (14 / 170) le croyait plus rapide qu'il n'est :
        # choisi explicitement, il déclenchait l'annonce « machine lente », alors
        # que c'est le modèle qui est lent. Pessimiste comme les autres lignes.
        "gemma4:12b": (4, "standard",  8.0, 12.0, 11.0,  85.0, 30.0, 8192, True,  "gemma"),
        "gemma4:26b": (5, "large",    18.0, 32.0,  7.0, 110.0, 45.0, 8192, True,  "gemma"),
        "gemma4:31b": (6, "large",    20.0, 32.0,  6.0, 100.0, 50.0, 8192, True,  "gemma"),
    }.items()
}
# Vocabulaire FERMÉ de la préférence `llm_model` (services/preferences.py) :
# aucun réglage n'est du texte libre. L'ordre est celui de l'affichage.
LLM_MODEL_CHOICES: tuple[str, ...] = (LLM_MODEL_AUTO, *LLM_MODELS)
# Profil de RÉFÉRENCE : celui du modèle de dernier recours, par construction une
# clé de la table. Il sert de repli à tout modèle inconnu (un modèle installé que
# cette table ignore garde des budgets définis plutôt que rien) et de base aux
# débits de référence ci-dessous.
LLM_REFERENCE_PROFILE = LLM_MODELS[OLLAMA_MODEL]
# Durée de vie du catalogue demandé à Ollama (`/api/tags`). Le modèle actif est
# résolu à CHAQUE génération et à chaque calcul de budget : un aller-retour HTTP
# par appel serait payé par l'étudiant qui attend.
LLM_TAGS_CACHE_TTL_S = 30.0
# « Automatique » prend le plus capable qui reste FLUIDE ici. La RAM ne suffit
# pas à le dire : e4b et 12b exigent les mêmes 12 Go, et sur l'Apple M4 de 16 Go
# le 12b écrit à 11,9 tokens/s (89 lus) contre 29,7 (255) pour e4b — mesuré le
# 2026-10-15. Une réponse de lecteur y prend deux fois et demie plus longtemps,
# et une lecture de prompt de 15 à 30 s. Un modèle dont l'écriture mesurée au
# calibrage passe sous ce plancher est écarté du choix automatique
# (services/llm_models.judge_fluency) ; un choix explicite, lui, est respecté.
# Le plancher porte sur l'écriture seule : c'est elle que l'étudiant attend.
LLM_AUTO_MIN_OUTPUT_TOKENS_PER_S = 15.0
# Un verdict de lenteur vaut pour la machine qui l'a mesuré (même RAM) et pour
# ce délai : une mesure prise en mode économie d'énergie ne doit pas écarter un
# modèle pour toujours. Il tombe aussi dès qu'une mesure repasse le plancher.
LLM_AUTO_VERDICT_TTL_DAYS = 14
# Coût en tokens d'un caractère, par tokenizer et par classe de caractères
# (`llm.prompts.estimate_prompt_tokens`). Ollama ne signale pas un prompt
# tronqué : les budgets se vérifient AVANT, sur les cas maximaux, avec une
# estimation PESSIMISTE (tests/services/test_*_prompt_budget.py). Calibré le
# 2026-10-13 sur 60 cas mesurés (`prompt_eval_count` de gemma4:e4b et
# qwen3:1.7b : les prompts maximaux des bancs, plus des textes purs en
# français, anglais, espagnol, allemand, arabe et chinois) ; chaque estimation
# dépasse le réel, de 2,4 % au pire, de 24 à 28 % en médiane.
#   - han    : un caractère chinois, un token (exact sur un caractère répété) ;
#   - arabic : l'arabe VOCALISÉ coûte 0,60 token par caractère chez Gemma, 0,80
#              chez qwen3 — l'ancienne estimation unique (0,5) le sous-estimait
#              chez les deux, et le banc de budget ne passait que grâce à la
#              marge du français autour ;
#   - digit  : les chiffres se tokenisent un par un (les agrégats JSON de
#              l'analyse hebdomadaire étaient sous-estimés de 12 %) ;
#   - punct  : ponctuation ASCII, guillemets et accolades du JSON compris ;
#   - rest   : lettres et espaces — qwen3 compte 0,31 token par caractère en
#              espagnol, Gemma 0,26.
PROMPT_TOKEN_WEIGHTS: dict[str, dict[str, float]] = {
    "gemma": {"han": 1.0, "arabic": 0.65, "digit": 1.0, "punct": 0.7, "rest": 0.30},
    "qwen": {"han": 1.0, "arabic": 0.9, "digit": 1.0, "punct": 0.6, "rest": 0.32},
}


# ── Budget temps d'une génération ─────────────────────────────────────────────
# Le timeout d'une tâche est DÉRIVÉ de ce qu'elle demande au modèle, pas choisi
# à la main : un `num_predict` de 3000 ne peut pas tenir dans le même budget
# qu'un de 160. Saisir les deux nombres séparément, c'est garantir qu'ils
# divergent — et un timeout applicatif plus long que le timeout socket est une
# échéance que personne n'atteindra jamais.
#
# Débit de RÉFÉRENCE : celui du modèle de référence sur la machine de dev (Apple
# Silicon, GPU intégré via Metal : ~29 tokens/s écrits, ~265 tokens/s lus ;
# la table en retient 18 et 200, volontairement pessimistes — un budget trop
# court fait échouer une génération correcte, un budget trop long ne coûte que
# dans le cas déjà anormal). DÉRIVÉS de LLM_MODELS : ces deux nombres y étaient
# écrits une seconde fois, et deux copies d'un même nombre divergent.
#
# Ce n'est qu'un point de départ. Un modèle plus lourd a son propre débit dans
# la table ; une machine plus LENTE (PC sans GPU, Mac Intel) est mesurée en
# cours de route (`llm/throughput.py`). Les budgets étirent l'un ET l'autre, et
# le chargement à froid du modèle est son `load_overhead_s` (ex-constante
# OLLAMA_TIMEOUT_OVERHEAD_S, désormais par modèle).
OLLAMA_TOKENS_PER_S = LLM_REFERENCE_PROFILE.tokens_per_s
OLLAMA_PROMPT_TOKENS_PER_S = LLM_REFERENCE_PROFILE.prompt_tokens_per_s
# Plafond dur : au-delà, l'utilisateur a déjà renoncé.
OLLAMA_TIMEOUT_MAX = 240.0
# Étirement maximal des budgets sur une machine lente (soit ~2 tokens/s écrits).
# Au-delà, une réponse prendrait plus de dix minutes : on échoue plutôt que de
# laisser l'écran attendre indéfiniment. Il borne la lenteur de la MACHINE et
# elle seule : le coût d'un modèle plus lourd est un facteur à part
# (`_model_factors`), sinon tourner en 31b consommait à lui seul la moitié de ce
# plafond et il ne restait rien pour la machine qu'il est censé couvrir.
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


# ── Mode économe ──────────────────────────────────────────────────────────────
# Une machine de 4 Gio ne fait tourner que le palier minuscule, sur son seul
# processeur : 2 à 6 tokens écrits par seconde, une lecture de prompt dix fois
# plus lente que sur la machine de référence, et une mémoire où le modèle, l'OS
# et le webview se disputent chaque gigaoctet. Le mode économe y rend Clikoda
# lente mais réelle, plutôt que muette :
#   - un contexte UNIQUE pour toutes les tâches (ECONOMY_NUM_CTX) et un lot de
#     lecture réduit (ECONOMY_NUM_BATCH) : Ollama recharge le modèle à CHAQUE
#     changement de `num_ctx` ou de `num_batch` (mesuré le 2026-10-13 sur
#     qwen3:1.7b : chaque alternance 2048/4096 coûte un chargement complet) ;
#   - des prompts compacts (PROMPT_LIMITS_COMPACT, plus bas), qui tiennent dans
#     ce contexte sans que rien n'en soit tronqué ;
#   - des budgets temps qui couvrent une machine jusqu'à ~0,9 token/s, bornés à
#     un quart d'heure par réponse : au-delà, une réponse n'en est plus une ;
#   - un modèle déchargé après cinq minutes sans demande, pour rendre la mémoire
#     au reste de la machine ;
#   - aucun travail de fond (OLLAMA_BACKGROUND_TASKS), aucune aide autonome
#     (services/intervention.py), aucun embedding (services/pdf_rag.py : la
#     recherche du lecteur reste lexicale) — Clikoda ne parle que quand on lui
#     parle, et l'unique worker reste libre pour la question de l'étudiant.
#
# La DÉCISION vit dans `services/llm_models.economy()` (préférence `llm_economy` :
# auto / on / off, il faut pouvoir forcer dans les deux sens) ; ce module n'en
# lit que le résultat. Ce que le mode NE fait PAS : réduire `num_predict`. Au
# banc du 2026-10-13, qwen3:1.7b écrivait 110 à 450 tokens sur des plafonds de
# 180 à 700 — couper le plafond ne raccourcissait aucune réponse, et tronquait
# celles dont la taille est structurelle (dix questions de QCM, un glossaire).
# Sur cette machine, chaque nouvelle tentative coûte des minutes.
LLM_ECONOMY_AUTO = "auto"
LLM_ECONOMY_CHOICES: tuple[str, ...] = (LLM_ECONOMY_AUTO, "on", "off")
# « auto » l'active pour le palier minuscule, ou sous la RAM qu'exige le plus
# petit gemma4 de la table : en dessous, même un modèle qui « tient » laisse
# l'OS swapper dès que le webview grossit.
LLM_ECONOMY_RAM_GB = 8.0
# Étirement maximal des budgets (≈ 0,9 token/s écrit : 18 / 20). Le plafond de
# la lecture du prompt et celui de l'écriture sont le MÊME nombre, lu par
# `max_slowdown()` à la fois ici et dans `llm/throughput` (plancher des débits
# mesurés) : deux copies divergeraient d'un facteur 2,5.
OLLAMA_MAX_SLOWDOWN_ECONOMY = 20.0
# Plafonds durs d'une tentative et d'une tâche, tentatives comprises.
OLLAMA_TIMEOUT_MAX_ECONOMY = 900.0
OLLAMA_WALL_TIMEOUT_MAX_ECONOMY = 1200.0
OLLAMA_KEEP_ALIVE_ECONOMY = "5m"
ECONOMY_NUM_CTX = 4096
ECONOMY_NUM_BATCH = 128
# Le lecteur annonce l'attente (« au plus ~N min », avec un bouton Annuler) en
# mode économe, ou dès que la machine s'est révélée au moins aussi lente que ce
# facteur face à la référence de son modèle (llm/throughput). En deçà, la
# réponse arrive avant qu'on ait lu l'annonce.
LLM_SLOW_MACHINE_FACTOR = 1.5
# Tâches de fond suspendues en mode économe (`llm/ollama_client`, la file est le
# seul endroit qui voit passer toutes les tâches avec leur label). Liste
# EXPLICITE et non un préfixe : `lang_episode_hook` (l'accroche du sas, attendue
# à l'écran) et `lang_writing_feedback` (la correction de fin de séance) restent
# servies, comme le calibrage du débit.
OLLAMA_BACKGROUND_TASKS: frozenset[str] = frozenset({
    "document_digest", "flashcard_lang_rules",
    "lang_story_bible", "lang_story_arc",
    "lang_episode_text", "lang_episode_text_hanzi",
    "lang_episode_glossary", "lang_episode_glossary_pron", "lang_episode_notes_point",
    "lang_point_lesson", "lang_weekly_analysis",
})


def _slowdown() -> tuple[float, float]:
    """(écriture, lecture) : lenteur MESURÉE de cette machine face à la
    référence, ≥ 1. Import tardif : `llm.throughput` lit les constantes de ce
    module."""
    from llm.throughput import slowdown

    return slowdown()


def _active_profile() -> ModelProfile:
    """Profil du modèle qui tourne vraiment.

    Import tardif, pour la même raison que `_slowdown()` : « quel modèle ? » est
    une politique qui lit une préférence en base, donc elle vit dans un service
    (cf. CLAUDE.md), et un service est au-dessus de ce module. Personne ne doit
    « nettoyer » ceci en import de module : le cycle est réel, il est fermé
    exprès dans un corps de fonction. `llm_models.active_profile()` ne lève
    jamais — un budget temps n'a pas le droit d'échouer."""
    from services.llm_models import active_profile

    return active_profile()


def _economy() -> bool:
    """Le mode économe est-il actif ? Import tardif, même cycle et même raison
    que `_active_profile()` : la décision lit une préférence en base, elle vit
    dans `services/llm_models`, et elle ne lève jamais."""
    from services.llm_models import economy

    return economy()


def max_slowdown() -> float:
    """Étirement maximal des budgets par la lenteur de la machine. Lu ICI et
    dans `llm/throughput` (plancher des débits mesurés) : un seul nombre."""
    return OLLAMA_MAX_SLOWDOWN_ECONOMY if _economy() else OLLAMA_MAX_SLOWDOWN


def keep_alive() -> str:
    """Durée pendant laquelle Ollama garde le modèle chargé après un appel."""
    return OLLAMA_KEEP_ALIVE_ECONOMY if _economy() else OLLAMA_KEEP_ALIVE


def context_ceiling() -> int:
    """Le plus grand `num_ctx` qu'une tâche peut recevoir en ce moment : le
    plafond du modèle actif, et en mode économe le contexte unique."""
    cap = _active_profile().max_num_ctx
    return min(cap, ECONOMY_NUM_CTX) if _economy() else cap


def compact_context() -> bool:
    """Les prompts doivent-ils tenir dans le contexte du mode économe ?

    Vrai en mode économe, ET pour un modèle qui ne tient pas davantage (le
    palier minuscule) même mode économe coupé : c'est la taille du contexte qui
    décide de la taille du prompt, pas le réglage qui l'a produite. Lu par les
    constructeurs de prompts du lecteur (`prompt_limits`) et par la recherche
    plein-document (services/pdf_rag)."""
    return context_ceiling() <= ECONOMY_NUM_CTX


def _model_factors(profile: ModelProfile) -> tuple[float, float]:
    """(écriture, lecture) : ce que CE modèle coûte face au modèle de référence.

    Jamais sous 1 : un modèle plus rapide que la référence ne RACCOURCIT aucun
    budget — même raison que `llm/throughput`. Facteur distinct de la lenteur
    machine, pour que `OLLAMA_MAX_SLOWDOWN` continue de borner celle-ci seule."""
    return (
        max(1.0, OLLAMA_TOKENS_PER_S / profile.tokens_per_s),
        max(1.0, OLLAMA_PROMPT_TOKENS_PER_S / profile.prompt_tokens_per_s),
    )


def task_options(task: str) -> dict:
    """Options Ollama d'une tâche, `num_ctx` plafonné par ce que le modèle tient.

    Point UNIQUE de lecture d'`OLLAMA_TASK_OPTIONS` : trois endroits le lisaient
    (deux fois la même expression dans `llm/ollama_client`, plus le calibrage),
    et un plafond par modèle appliqué à deux d'entre eux seulement est un
    plafond qui ne protège rien. Ollama ne REFUSE pas un prompt plus long que
    `num_ctx` : il en tronque silencieusement le DÉBUT (rôle, consignes,
    profil).

    En mode économe, toutes les tâches reçoivent le MÊME contexte et le même
    lot de lecture : c'est ce qui évite un rechargement du modèle entre deux
    tâches. Les prompts, eux, sont compacts (`prompt_limits`) pour y tenir."""
    options = OLLAMA_TASK_OPTIONS.get(task) or OLLAMA_OPTIONS
    cap = _active_profile().max_num_ctx
    if _economy():
        return {**options, "num_ctx": min(cap, ECONOMY_NUM_CTX), "num_batch": ECONOMY_NUM_BATCH}
    if int(options.get("num_ctx") or 0) <= cap:
        return options
    return {**options, "num_ctx": cap}


def prompt_budget_tokens(task: str) -> int:
    """Tokens que le prompt d'une tâche peut occuper (consigne système
    comprise) : son contexte effectif moins la sortie réservée. C'est la borne
    que vérifient les bancs de budget (tests/services/test_*_prompt_budget.py)."""
    options = task_options(task)
    return int(options.get("num_ctx") or 0) - int(options.get("num_predict") or 0)


def task_timeout_s(task: str) -> float:
    """Budget d'UNE tentative, dérivé du `num_predict` de la tâche.

    C'est le timeout socket appliqué à l'appel (llm/ollama_client). Une tâche
    inconnue retombe sur les options par défaut. Deux facteurs l'étirent, et ils
    restent séparés : la lenteur MESURÉE de la machine (`_slowdown`, bornée par
    `OLLAMA_MAX_SLOWDOWN`) et le coût du MODÈLE actif face à la référence
    (`_model_factors`). Sur le modèle de référence, les seconds valent 1,0 et la
    formule est celle d'avant, au nombre près."""
    options = task_options(task)
    tokens = float(options.get("num_predict") or OLLAMA_OPTIONS["num_predict"])
    profile = _active_profile()
    gen_slow, prompt_slow = _slowdown()
    model_gen, model_prompt = _model_factors(profile)
    budget = profile.load_overhead_s * prompt_slow + tokens * gen_slow * model_gen / OLLAMA_TOKENS_PER_S
    ceiling = OLLAMA_TIMEOUT_MAX * max(gen_slow * model_gen, prompt_slow * model_prompt)
    if _economy():
        # La lenteur admise monte à OLLAMA_MAX_SLOWDOWN_ECONOMY ; le quart
        # d'heure, lui, ne s'étire pas.
        ceiling = min(ceiling, OLLAMA_TIMEOUT_MAX_ECONOMY)
    return min(ceiling, max(float(OLLAMA_TIMEOUT), budget))


def task_wall_timeout_s(task: str) -> float:
    """Budget TOTAL d'une tâche, tentatives comprises.

    Source unique de DEUX échéances qui doivent rester d'accord : la boucle de
    retry de `_generate_json` cesse de rejouer au-delà, et `run_llm_sync`
    attend exactement ça avant d'abandonner. C'est aussi l'attente annoncée à
    l'étudiant (« au plus ~N min », services/llm_models.wait_estimate_s) : le
    lecteur n'a pas d'autre chiffre, et l'interface n'en recalcule aucun."""
    gen_slow, prompt_slow = _slowdown()
    model_gen, model_prompt = _model_factors(_active_profile())
    ceiling = OLLAMA_WALL_TIMEOUT_MAX * max(gen_slow * model_gen, prompt_slow * model_prompt)
    if _economy():
        ceiling = min(ceiling, OLLAMA_WALL_TIMEOUT_MAX_ECONOMY)
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
# essentielles sont sautées et la séance va à la première étape essentielle
# non faite — l'au revoir est toujours joué (R24). Une séance « épisode » :
# rappel 120 + lecture 300 + leçon 240 + expression 210 + jeux 210 + au revoir 30
# ≈ 18,5 min (sas d'entrée en plus) ; 2e vague et jalon compris, ≤ 1 470 s.
LANG_RUN_TARGET_S = 1080
LANG_RUN_MAX_S = 1500
# Budget indicatif par étape : sert à ordonner ce qu'on saute quand le plafond
# approche, et à la barre de progression. Jamais un compte à rebours affiché.
LANG_STEP_BUDGET_S: dict[str, int] = {
    "rappel": 120, "lecture": 300, "lecon": 240, "expression": 210, "jeux": 210,
    "deuxieme_vague": 180, "au_revoir": 30,
    "accueil": 120, "phrases": 360, "ecriture": 180, "interets": 90,
    "recap": 240, "relecture": 360, "cartes": 180, "controle": 240, "jalon": 180,
}
# Étapes jamais sautées par le plafond de durée : la lecture de l'épisode, ce
# que l'apprenant en écrit, et l'au revoir.
LANG_ESSENTIAL_STEPS: tuple[str, ...] = ("lecture", "expression", "au_revoir")
# Au-delà de ce silence (aucun geste, cf. LANG_ACTIVITY_*), le temps n'est plus « effectif ».
LANG_IDLE_CUTOFF_S = 90
# Attention d'une séance de langue. Elle ne baisse que si l'apprenant tourne une
# page, ou passe d'une question à la suivante sur une même page, après un temps
# trop long — et seulement pour la part de ce temps passée sans un geste
# (metacog.gauges.stall_attention_drop). Une réponse fausse ou lente n'est pas un
# décrochage. Une page est trop longue au-delà de LANG_ATTENTION_PAGE_SLACK × son
# budget (LANG_STEP_BUDGET_S) — jusqu'à sa première réponse quand elle en a ;
# d'une réponse à la suivante, puis à la page suivante, au-delà de
# LANG_ATTENTION_QUESTION_GAP_S. Lus par services/lang_runs._run_measures.
LANG_ATTENTION_PAGE_SLACK = 2.0
LANG_ATTENTION_QUESTION_GAP_S = 60
# Ce qu'est un geste : un clic, une touche, un défilement — ou la souris qui
# bouge, car on lit aussi en suivant le texte du pointeur, comme d'autres font
# défiler pour garder la ligne à hauteur d'yeux. Les mouvements sont échantillonnés
# (au plus un toutes les LANG_ACTIVITY_MOVE_SAMPLE_MS) et comptés sur une fenêtre
# glissante de LANG_ACTIVITY_WINDOW_S : ils valent un geste à partir de
# LANG_ACTIVITY_MIN_MOVES, pour qu'un effleurement ne passe pas pour une lecture.
# Une seconde est active s'il y a eu un geste dans la fenêtre ; fenêtre masquée,
# elle ne l'est jamais. Envoyés au client avec le plan (`run_view`, `activity`).
LANG_ACTIVITY_WINDOW_S = 15
LANG_ACTIVITY_MIN_MOVES = 5
LANG_ACTIVITY_MOVE_SAMPLE_MS = 100

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
LANG_REVEAL_RATE_HIGH = 12.0    # taps / 100 mots lus sans traduction : au-delà, trop dur
LANG_REVEAL_RATE_LOW = 3.0      # en deçà, facile
# En dessous de ce nombre de mots lus SANS traduction, le taux de taps ne dit
# rien (une réplique ou deux) : il vaut None, jamais « facile ».
LANG_REVEAL_MIN_TOKENS = 20
# Part des répliques dont la traduction a été montrée pendant la lecture, par
# palier d'ancrage (index 0-4) : au-delà de HARD le texte était trop dur (aux
# paliers A1 et A1-A2, « Tout traduire » est une aide prévue, jamais un échec) ;
# « facile » demande d'être resté en deçà de EASY.
LANG_TRANSLATED_SHARE_HARD: tuple[float | None, ...] = (None, None, 0.75, 0.6, 0.5)
LANG_TRANSLATED_SHARE_EASY: tuple[float, ...] = (0.5, 0.35, 0.25, 0.15, 0.1)
# Paliers dont la lecture propose « Tout traduire » (valeur `translation` du
# palier, LANG_DIFFICULTY_LADDER) ; au-delà, la traduction se demande réplique
# par réplique.
LANG_TRANSLATE_ALL_MODES: tuple[str, ...] = ("toujours", "masquable")
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
# traduction, tiennent dans leur fenêtre (G2). Un mot arabe vocalisé (clitiques
# et voyelles compris) coûte près de deux fois les tokens d'un mot espagnol.
# Au-delà, il faudrait élargir num_ctx — et Ollama recharge le modèle à chaque
# changement de fenêtre.
#
# PAR TOKENIZER, parce que la garantie l'est : qwen3 compte l'arabe vocalisé un
# tiers plus cher que Gemma, dans une fenêtre plafonnée à 4096 au lieu de
# 5120. Le plafond arabe y descend donc à 180 mots (mesuré le 2026-10-13 : à
# 300, son glossaire débordait de 650 tokens réels). Lu par
# `max_units_per_episode`, jamais directement — le banc de budget
# (tests/services/test_lang_prompt_budget.py) le vérifie pour chaque tokenizer.
LANG_MAX_UNITS_PER_EPISODE: dict[str, dict[str, int]] = {
    "gemma": {"latin": 450, "hanzi": 700, "arabe": 300},
    "qwen": {"latin": 450, "hanzi": 700, "arabe": 180},
}


def max_units_per_episode(family: str, tokenizer: str | None = None) -> int:
    """Plafond de longueur d'un épisode pour le tokenizer du modèle actif (ou
    celui donné : les bancs de budget les parcourent tous)."""
    caps = LANG_MAX_UNITS_PER_EPISODE.get(tokenizer or _active_profile().tokenizer)
    return (caps or LANG_MAX_UNITS_PER_EPISODE["gemma"])[family]


# Mots nouveaux (G4/G7) : le contrôle ne s'applique qu'une fois le lexique
# amorcé — au premier épisode, tout est nouveau — et avec une marge.
LANG_NEW_WORDS_CHECK_MIN_LEXICON = 60
LANG_NEW_WORDS_TOLERANCE = 1.5
# … et seulement là où le lexique dit ce que l'apprenant sait : aux paliers
# A1 et A1-A2 (index ≤ N), pour un apprenant parti du début du programme
# (point de départ ≤ N). Un apprenant placé par le test de niveau sait bien plus
# que son lexique — deux profils placés (A1, C1) voyaient chaque épisode refusé.
LANG_NEW_WORDS_CHECK_MAX_TIER = 1
LANG_NEW_WORDS_CHECK_MAX_START_ORDER = 1
# Un dépassement de mots nouveaux est un problème « doux » : relancé au plus N
# fois (le modèle ne les réduit pas quand on le lui redemande), puis la
# meilleure tentative est acceptée et journalisée. Une erreur dure échoue.
LANG_SOFT_PROBLEM_RETRIES = 1
# Mots que l'apprenant connaît déjà, donnés au prompt du texte (acquis d'abord) :
# budget en tokens estimés (`llm.prompts.estimate_prompt_tokens`).
LANG_KNOWN_WORDS_PROMPT_TOKENS = 300
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
# Ne pas reprendre les jeux des N séances précédentes : à 2, il ne resterait
# plus aucun jeu neuf en langue latine (quatre jeux hors micro-items, trois par séance).
LANG_GAMES_AVOID_LAST_RUNS = 1
LANG_GAMES_PER_RUN = 3
LANG_POINT_MICRO_ITEMS = 3

# C12 — la leçon du point (services/lang_point_lesson.py). Écrite par Clikoda
# une fois par point et par langue d'explication, gardée en base, lue d'abord
# dans nwol/data/lang/lessons/<langue>.json quand une leçon y est écrite à la main.
LANG_LESSON_ITEMS = 3                    # micro-items tirés de la leçon (en plus des 3 du texte)
LANG_LESSON_RULE_MAX_CHARS = 600
LANG_LESSON_REMEMBER_MAX_CHARS = 180
LANG_LESSON_TEXT_MAX_CHARS = 160         # un exemple, une forme fautive, une traduction
LANG_LESSON_NOTE_MAX_CHARS = 220         # un emploi, une explication de piège
LANG_LESSON_FORMS_MAX = (8, 4)           # tableau de formes : lignes, colonnes (en-tête compris)
LANG_LESSON_CELL_MAX_CHARS = 40
LANG_LESSON_USES = (1, 4)
LANG_LESSON_PITFALLS = (0, 3)
LANG_LESSON_EXAMPLES = (2, 4)
# Appels refusés au-delà desquels la leçon d'un point n'est plus redemandée
# (deux générations complètes) : l'étape garde son repli, l'épisode n'est jamais touché.
LANG_LESSON_MAX_ATTEMPTS = 6

# C13 — l'expression écrite (services/lang_writing.py). Corrigée par Clikoda en
# arrière-plan : la séance n'attend jamais la correction.
LANG_WRITING_MAX_CHARS = 1200
# Longueur demandée (min, max), par famille d'écriture puis par palier
# d'ancrage (index 0-4) : en mots, en caractères pour le mandarin.
LANG_WRITING_LENGTH: dict[str, tuple[tuple[int, int], ...]] = {
    "latin": ((15, 40), (25, 60), (40, 90), (60, 120), (80, 150)),
    "hanzi": ((15, 40), (25, 60), (40, 100), (60, 140), (80, 180)),
    "arabe": ((8, 25), (15, 40), (25, 60), (40, 90), (55, 120)),
}
LANG_WRITING_TARGET_WORDS = 3            # mots du jour à employer
LANG_WRITING_BANK_WORDS = 8              # banque de mots proposée à côté de la consigne
LANG_WRITING_MAX_ERRORS = 3              # erreurs relevées par la correction, les plus importantes d'abord
# Vocabulaire des erreurs, hérité de la correction du flux historique
# (llm/prompts.build_lang_correction_prompt) : une seule taxonomie dans l'application.
LANG_WRITING_ERROR_TYPES: tuple[str, ...] = (
    "genre", "accord", "conjugaison", "ordre des mots", "préposition", "faux-ami", "orthographe",
    "registre", "vocabulaire",
)

# C6 — acquisition (mot, puis signe d'écriture). Un mot est acquis après N
# reconnaissances (lu au passage 2 sans le toucher, ou bien répondu dans un jeu)
# réparties sur au moins M épisodes distincts.
LANG_ACQUIRED_RECOGNITIONS = 3
LANG_ACQUIRED_MIN_EPISODES = 2
LANG_SCRIPT_ACQUIRED_RECOGNITIONS = 4
LANG_SCRIPT_ACQUIRED_MIN_EPISODES = 2

# C7 — absence (jours depuis le dernier jour d'étude de CETTE langue, 0 dès
# qu'aujourd'hui compte). (borne haute incluse, palier) ; None = au-delà.
# Jusqu'à 3 jours, l'épisode prêt se joue. Au-delà, quel que soit le palier, la
# séance est une relecture imposée sans nouvel épisode, et l'épisode prêt
# attend la séance suivante — jamais jeté ni réécrit. Le palier ajoute : une
# respiration au prochain épisode à écrire dès `reprise`, un contrôle dès
# `reprise_controle`.
LANG_ABSENCE_TIERS: tuple[tuple[int | None, str], ...] = (
    (3, "normal"), (6, "rappel_long"), (20, "reprise"), (None, "reprise_controle"),
)
LANG_DUE_CARDS_CAP = 15                 # cartes dues servies par séance (warm-up du sas compris), les plus anciennes d'abord

# C8 — jour d'étude (décompte par langue, backend seulement, jamais affiché en série).
LANG_STUDY_DAY_CUTOFF_HOUR = 4
LANG_STUDY_DAY_MIN_S = 300

# C9 — pré-génération. L'épisode N+1 part à l'étape LANG_PREGEN_TRIGGER_STEP de
# la séance N, avec les signaux du jour : la lecture est faite, ses taps et ses
# traductions montrées sont connus.
LANG_PREGEN_BUFFER = 1
LANG_PREGEN_TRIGGER_STEP = "lecon"
LANG_GEN_MAX_ATTEMPTS_PER_CALL = 3
# Échecs d'écriture d'un même épisode au-delà desquels l'accueil mentionne les
# limites du modèle local (une ligne statique, aucun appel, rien de bloqué).
LANG_GEN_FAILURES_PRO_HINT = 2
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
# Accroche du sas d'entrée (services/lang_hook.py) : une phrase, refusée au-delà,
# et les répliques du DÉBUT de l'épisode que Clikoda voit traduites — de quoi
# poser la situation sans lui montrer la fin.
LANG_HOOK_MAX_CHARS = 200
LANG_HOOK_OPENING_LINES = 6
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

LANG_WEEKLY_WINDOWS_DAYS = (7, 28)
# Portrait d'une langue lu par le brainstorming (`lang_runs.learner_overview`) :
# dernières séances MESURÉES dont la difficulté (`lang_progress.classify`) est
# résumée, cherchées parmi les N dernières terminées (les relectures, sans
# mesure, s'enchaînent après une absence).
LANG_OVERVIEW_RECENT_RUNS = 5
LANG_OVERVIEW_SCAN_RUNS = 20

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
# « Localiser le fichier » (services/relink) : après une re-liaison, les AUTRES
# documents introuvables rangés sous l'ancien dossier sont cherchés au même
# endroit relatif sous le nouveau. Chaque candidat coûte une lecture complète du
# fichier (empreinte), dans la requête : borné, et un second « Localiser »
# reprend où le premier s'est arrêté.
RELINK_SIBLINGS_MAX = 100

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

DB_SCHEMA_VERSION = 46

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
# Plafond sur une fenêtre GLISSANTE de lecture : au plus ASSISTANT_MAX_INTERVENTIONS
# dans toute période de ASSISTANT_INTERVENTION_WINDOW_S, pauses exclues (comme les
# cooldowns). C'était un plafond par SÉANCE : les six tombaient dans la première
# heure, puis Clikoda se taisait jusqu'à la fin — 2 h 47 sans une question sur
# une séance de 3 h (journal du 2026-10-20).
# None = AUCUN plafond, et c'est le réglage de l'édition locale (retour d'usage du
# 2026-10-21 : même glissant, le plafond faisait taire Clikoda). Les cooldowns,
# le warm-up et l'anti-répétition (page, raison) suffisent à régler la cadence ;
# une intervention n'y coûte qu'un appel au modèle local.
ASSISTANT_MAX_INTERVENTIONS: int | None = None
ASSISTANT_INTERVENTION_WINDOW_S = 3600.0

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
# Crédit d'attention versé au retour d'une pause, au prorata du temps pris sur
# la durée conseillée (PAUSE_DEFAULT_MIN pour une pause que l'élève prend de
# lui-même). Une pause manuelle était neutre ; or le repos rend l'attention quel
# que soit celui qui l'a proposé, et décider de s'arrêter est de l'autorégulation
# (retour d'usage du 2026-10-21 : « je fais des pauses et l'attention reste basse »).
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
ATTENTION_PROGRESS_BONUS = 1.2       # points gagnés par nouvelle page lue (PAGE_READ_MIN_DWELL_S)
ATTENTION_PASSIVE_FLOOR = 15.0       # plancher de la seule dérive passive
# Engagement : ce que l'élève FAIT de sa lecture prouve qu'il y est. Poser une
# question à Clikoda, répondre à la sienne, surligner, annoter ne rapportaient
# rien à l'attention : seule la progression d'une page la créditait, et toute
# réponse rédigée lui COÛTAIT (au-delà de 12 s de réponse, jusqu'à 6 points —
# les dix réponses des séances 59 et 60 ont pris de 58 s à 14 min). Chaque geste
# crédite l'attention, au plus une fois par ATTENTION_ENGAGEMENT_COOLDOWN_S et
# par geste : surligner dix lignes d'affilée ne vaut pas dix fois l'effort.
# Lus uniquement par `services/session.LiveGauges.credit_engagement` ; le
# lecteur envoie `engage` (surligner, annoter), le socket compte le reste.
ATTENTION_ENGAGEMENT_CREDIT: dict[str, float] = {
    "ask": 2.0,        # une question posée à Clikoda
    "answer": 1.5,     # une réponse écrite à la question de Clikoda
    "highlight": 1.0,  # un passage surligné, souligné, barré ou encadré
    "note": 1.5,       # une note, un post-it ou un signet écrits
}
ATTENTION_ENGAGEMENT_COOLDOWN_S = 20.0
# Une séance sans canal temps réel (séance de langue) n'observe l'attention que
# par INTERVALLES — une page tournée, une question répondue. Un intervalle plus
# long que permis ne coûte que sa part inexpliquée (dépassement × part du temps
# sans un geste), au rythme de ATTENTION_DRIFT_PER_MIN, jusqu'au plancher
# ATTENTION_PASSIVE_FLOOR, et jamais plus que ceci par intervalle : une longue
# interruption est UN décrochage, pas une chute libre.
# Lu par metacog.gauges.stall_attention_drop.
ATTENTION_STALL_MAX_DROP = 6.0
ATTENTION_PERSIST_EVERY_S = 60.0     # cadence d'écriture des jauges passives en base
# Une page est LUE quand le temps passé dessus dans la séance (pauses exclues,
# visites cumulées) atteint ce seuil. Avant, « pages lues » était la page la plus
# avancée envoyée par le client, et le bonus de progression comptait toute page
# dominante une fraction de seconde : défiler vingt pages en valait vingt.
# Lu par services/session_memory.pages_read, seul auteur du compte
# (`reading_sessions.pages_read`) et du bonus de progression ci-dessus.
PAGE_READ_MIN_DWELL_S = 5.0
# Une séance ouverte écrit son temps de lecture (`reading_sessions.duration_s`)
# au plus une fois par cet intervalle. Fermer le logiciel sans « Terminer » ne
# laisse rien d'autre : c'est ce temps-là qui date la clôture de la séance au
# démarrage suivant (services/session.close_abandoned_sessions).
SESSION_HEARTBEAT_S = 60.0

# ── Temps restant d'un document (carte « Reprendre ») ────────────────────────
# Le « ≈ N min » de la carte était la médiane des 40 dernières séances, quiz et
# langues compris : 7 min annoncées pour un rythme de lecture de 22, la même
# durée pour un chapitre et pour un manuel. C'est désormais le temps qu'il
# reste au document : ses pages restantes à l'allure MESURÉE de l'élève —
# médiane du temps par page lue (au moins PAGE_READ_MIN_DWELL_S) dans ce
# document, sinon dans les documents de même nature (un fichier de code ne se
# lit pas au rythme d'un PDF), sinon ce défaut, annoncé comme une estimation.
# La médiane relevée sur la base de dev est d'environ 116 s par page lue.
# Lus uniquement par services/reading_pace.py.
READING_ESTIMATE_DEFAULT_PAGE_S = 120.0
READING_ESTIMATE_MIN_PAGES = 5       # échantillons pour se fier à une médiane
READING_ESTIMATE_WINDOW = 200        # échantillons récents gardés (l'allure change)

# ── Recherche dans le document (Ctrl/Cmd+F du lecteur) ───────────────────────
# Insensible aux accents et à la casse, à travers les mots coupés en fin de
# ligne (services/reader_find.py). Une lettre seule trouverait toutes les
# pages : la requête en demande au moins deux, pliées. Au-delà de 200, ce n'est
# plus une recherche mais un collage. Une page surligne au plus 500 occurrences
# (« de » sur une page dense de tableaux en approche) : au-delà, elles restent
# comptées, et la réponse dit que la liste de la page est tronquée.
READER_FIND_MIN_CHARS = 2
READER_FIND_MAX_QUERY_CHARS = 200
READER_FIND_MAX_PAGE_HITS = 500

# ── Prise de notes du lecteur (schéma v45) ───────────────────────────────────
# Vocabulaires FERMÉS, validés par services/annotations.py : une couleur est une
# clé de la palette (chaque clé a son `--note-<clé>` dans theme/tokens.css et son
# nom accessible `annotations.color.<clé>` dans les deux dictionnaires, cf.
# tests/test_annotation_palette_tokens.py), un style l'un des quatre tracés.
ANNOTATION_COLORS = ("yellow", "orange", "red", "pink", "violet", "blue", "cyan", "green", "lime", "gray")
ANNOTATION_STYLES = ("highlight", "underline", "strike", "outline")
# Étiquettes semées pour chaque utilisateur, dans cet ordre : (preset, couleur).
# Leur nom vient de l'i18n (`annotations.preset.<preset>`) tant que l'élève ne
# l'a pas renommée — il suit alors la langue de l'interface.
ANNOTATION_PRESETS = (
    ("important", "yellow"),
    ("definition", "blue"),
    ("example", "green"),
    ("review", "red"),
    ("question", "violet"),
    ("idea", "orange"),
)
# L'ancienne colonne `reader_highlights.color` (v20) : sa correspondance en
# étiquette, pour la migration v45 et pour un client qui l'enverrait encore.
ANNOTATION_LEGACY_COLOR_PRESETS = {"key": "important", "explain": "definition", "reference": "example"}
ANNOTATION_DEFAULT_COLOR = "yellow"
ANNOTATION_MAX_LABELS = 24
ANNOTATION_LABEL_NAME_MAX = 40
ANNOTATION_NOTE_MAX_CHARS = 4000
ANNOTATION_QUOTE_MAX_CHARS = 4000
ANNOTATION_MAX_RECTS = 400

# ── Révision éclair : le RYTHME des cartes du sas d'entrée ──────────────────
# Les cartes du warm-up ne sont pas notées (un clic retourne, un clic avance) :
# ce qui se mesure, c'est le temps passé sur chaque face. Chaque face a des
# temps de référence tirés de son propre texte, et le temps passé est classé :
#   * rushed  : sous le temps de SURVOL -> la face n'a pas été lue, on clique ;
#   * slow    : au-delà de la lecture + une marge (chercher la réponse au recto,
#               la confronter au verso) -> la trace en mémoire est fragile ;
#   * drifted : au-delà de la lecture + WARMUP_DRIFT_S -> l'élève n'est plus là ;
#   * steady  : entre les deux, aucun effet.
# Lues uniquement par services/warmup.py — sauf WARMUP_MAX_CARDS, qui borne
# aussi le tirage des cartes du sas d'une séance de langue (services/lang*.py).
WARMUP_MAX_CARDS = 5
WARMUP_SKIM_MS_PER_WORD = 100        # ≈ 600 mots/min : plus vite, on ne lit pas, on clique
WARMUP_READ_MS_PER_WORD = 250        # ≈ 240 mots/min : lecture attentive
WARMUP_MIN_FACE_MS = 800             # plancher du survol, même pour une réponse d'un mot
WARMUP_RECALL_ALLOWANCE_S = 15.0     # recto : chercher la réponse avant de retourner
WARMUP_CHECK_ALLOWANCE_S = 8.0       # verso : confronter la réponse à la sienne
WARMUP_DRIFT_S = 60.0                # au-delà (lecture comprise), l'attention a décroché
# Effets sur les jauges live, PAR FACE (une carte en a deux). Cliquer sans lire
# coûte attention ET métacognition (on ne se teste pas, on se donne l'illusion
# de savoir) ; la lenteur coûte de la rétention, surtout au verso (on réapprend
# la réponse au lieu de la reconnaître) ; le décrochage ne coûte que l'attention
# — un temps pareil ne dit plus rien de la mémoire.
WARMUP_RUSH_ATTENTION = 1.5
WARMUP_RUSH_META = 1.5
WARMUP_SLOW_FRONT_RETENTION = 1.0
WARMUP_SLOW_BACK_RETENTION = 2.0
WARMUP_DRIFT_ATTENTION = 3.0
# Plafond du coût en attention de toute la révision éclair : cinq cartes cliquées
# sans lire coûtaient 15 points (séance 59), plus qu'un quart d'heure loin de
# l'écran — pour un prélude d'une minute dont les cartes sont parfois déjà sues.
WARMUP_MAX_ATTENTION_COST = 5.0

# ── Poids d'une séance dans le profil long terme, par catégorie ──────────────
# Le profil glisse vers les jauges de chaque séance finalisée d'une part α
# (adaptatif, `metacog.profile.compute_alpha`) × la confiance de la séance (ce
# qu'elle a mesuré). Ce poids s'y multiplie selon la CATÉGORIE de la séance : une
# lecture et une séance de langue font apprendre, un quiz vérifie ce qui a été
# appris — il pèse moins. Valeurs dans [0, 1]. Lu par
# `services/session.nudge_metacog_profile`, l'unique finalisation.
PROFILE_SESSION_KIND_WEIGHT: dict[str, float] = {"reading": 1.0, "lang": 1.0, "quiz": 0.5}

# ── Séances de pratique : le quiz et les langues font bouger les jauges ──────
# Un quiz et une séance de langue mesurent l'apprenant comme une lecture. Leurs
# mesures sont rejouées en fin de séance en une courbe de jauges
# (`practice_session_gauges`), qui fait glisser le profil par le moteur unique
# (`services/session.nudge_metacog_profile`). Lues par `metacog/gauges.py`.
#
# Une réponse jugée par un verdict SEUL — QCM, jeu de langue, auto-évaluation,
# aucun signal du LLM — tire chaque jauge qu'elle vise vers la cible de son
# verdict. Un verdict n'informe que la performance (attention, compréhension,
# rétention) : il ne dit rien de la curiosité, de la créativité ni de la
# métacognition, qui restent alors intactes. Une réponse rédigée corrigée par le
# LLM garde le modèle du lecteur (signaux, `update_gauges_from_evaluation`).
GAUGE_VERDICT_TARGETS: dict[str, float] = {"correct": 100.0, "partial": 60.0, "incorrect": 15.0}
# Part du chemin vers la cible parcourue à chaque verdict : au bout de huit
# réponses, la jauge dit la séance plutôt que son amorce.
GAUGE_VERDICT_WEIGHT = 0.2

# Curiosité : questionner de sa propre initiative en est LE signal, et le prompt
# de réponse exige un signal d'au moins 1,0 — +12,8 points par question posée à
# Clikoda : la jauge atteignait 100 en trois ou quatre questions, à chaque séance
# (retour d'usage du 2026-10-21). La question posée ne pèse plus que cette part
# de son signal, et toute hausse de la curiosité est proportionnelle à ce qui
# reste à gagner, (100 − valeur) / 100 (`metacog.gauges.GaugeState.update`) :
# la dixième question d'une séance en dit moins que la première, et 100 n'est
# plus jamais atteint. Lu par `services/session.LiveGauges.apply_question`.
GAUGE_ASK_CURIOSITY_SCALE = 0.5

# Question réflexive (métacognition, anticipation : `no_wrong_answer` dans
# config/question_types.py) : il n'y a pas de mauvaise réponse, donc pas de
# bonus de verdict. C'est l'analyse du LLM — `metacog_signals.meta_cognition`,
# entre -2 et 2 — qui fait bouger la jauge de métacognition, multipliée par ce
# facteur : de -3 à +3 points par réponse, à la hausse comme à la baisse.
GAUGE_REFLECTION_META_SCALE = 1.5

# Jauge(s) que chaque mesure d'une séance de langue informe — toujours parmi
# les trois critères de performance ci-dessus. Un jeu de lexique travaille la
# mémoire, un jeu sur le dialogue la compréhension, un repérage l'attention.
# Feuilleton : par jeu (services/lang_runs.py) ; flux hérité : par compétence de
# l'exercice (services/lang.py).
LANG_GAME_TARGET_GAUGES: dict[str, tuple[str, ...]] = {
    "qui_a_dit": ("context_comprehension",),
    "completer_replique": ("context_comprehension", "retention"),
    "remettre_en_ordre": ("context_comprehension",),
    "bonne_forme": ("context_comprehension", "retention"),
    "apparier": ("retention",),
    "caractere_sens": ("retention",),
    "caractere_pinyin": ("retention",),
    "ton_du_caractere": ("retention",),
    "lettre_forme": ("retention",),
    "lire_vocalise": ("retention",),
    "trouver_dans_le_texte": ("attention",),
    "retrouver_la_lettre": ("attention",),
}
# Deuxième vague : l'apprenant retraduit une réplique, la confronte à l'original
# puis juge son rappel (« su », « à peu près », « pas su »).
LANG_SECOND_WAVE_TARGET_GAUGES: tuple[str, ...] = ("retention",)
# Expression écrite : le verdict de la correction de Clikoda, s'il est arrivé
# avant la clôture. Les contrôles calculés (longueur, mots employés) ne sont
# ni une mesure ni un score.
LANG_WRITING_TARGET_GAUGES: tuple[str, ...] = ("retention", "context_comprehension")
# Le « compris / à peu près / pas compris » qui ferme un passage de lecture.
LANG_UNDERSTOOD_TARGET_GAUGES: tuple[str, ...] = ("context_comprehension",)
# La dernière question d'une séance (le ressenti de « au revoir ») est une
# question de métacognition : y répondre avant « Terminer », c'est s'observer
# apprendre ; la laisser sans réponse, c'est s'en dispenser. Choix parmi trois,
# elle n'est pas notée par Clikoda : la métacognition de la séance vaut le
# profil ± ce pas, et le profil n'en parcourt que sa part α (adaptative,
# `metacog.profile.compute_alpha`) — un léger mouvement, jamais un saut.
# Une séance quittée avant la question ne déplace rien.
LANG_FEELING_META_STEP = 10.0
LANG_SKILL_TARGET_GAUGES: dict[str, tuple[str, ...]] = {
    "comprehension_orale": ("context_comprehension", "attention"),
    "comprehension_ecrite": ("context_comprehension",),
    "grammaire_contexte": ("context_comprehension",),
    "vocabulaire": ("retention",),
    "revision": ("retention",),
    "ecriture": ("retention",),
    "prononciation": ("attention",),
    "production_orale": ("retention",),
    "production_ecrite": ("retention", "context_comprehension"),
}

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
# Bilan de session : « cours à renforcer » affichés au plus. Ils sont CALCULÉS
# (`services.quiz._courses_to_review`) depuis les questions de lecture manquées,
# jamais proposés par le LLM — le catalogue statique n'a pas de cours à ouvrir.
QUIZ_REVIEW_MAX_COURSES = 3

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
# La matière n'est plus un poids : c'est un palier (services/flashcards.
# session_start_cards) — les cartes de la matière du document d'abord.
FLASHCARD_POOL = 400
FLASHCARD_RECENCY_HALF_LIFE_DAYS = 30.0
FLASHCARD_RECENCY_FLOOR = 0.35
# `last_reviewed` est déjà écrit par l'échauffement lui-même (WarmUp appelle
# /review) : c'est le signal « vue à la session précédente », jusqu'ici ignoré.
FLASHCARD_REVIEW_COOLDOWN_DAYS = 5.0
FLASHCARD_REVIEW_FLOOR = 0.2
# Carte écrite à la main : Clikoda y applique les règles des cartes de langue
# (lemme au recto, sens au verso, prononciation, langue) — services/flashcards.
# Au-delà de ce nombre de caractères sur une face, ce n'est plus un mot ni une
# courte expression (définition, question de cours) : aucun appel.
MANUAL_CARD_LANG_MAX_CHARS = 120

# Brainstorming : plafond d'extraits par type de source (surlignage, flashcard, erreur,
# Q&R, document, mot et épisode du module Langues) et amortissement d'une source
# DÉJÀ CITÉE dans la discussion.
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


# ── Taille des prompts du lecteur : pleine ou compacte ───────────────────────
# Ce qu'un prompt du lecteur embarque (texte de page, réponses de la séance,
# passages trouvés ailleurs…) est dimensionné pour le `num_ctx` que sa tâche
# déclare. Quand le contexte de travail est celui du mode économe
# (`compact_context()` : mode économe, ou palier minuscule), les trois tâches
# qui déclarent plus que lui — la question (6144), l'évaluation (6144) et la
# réponse libre (8192) — reçoivent moins : mesuré le 2026-10-13 avec le
# tokenizer de qwen3 sur leurs cas maximaux, leurs prompts pleins font 5645,
# 4318 et 4967 tokens, avant même les 700 réservés à la sortie. Ollama en
# aurait coupé le début (le rôle, la page) sans un mot. Le banc qui le
# garantit : tests/services/test_reader_prompt_budget.py.
#
# Les valeurs pleines sont celles d'avant, à l'identique : un prompt du modèle
# de référence ne change pas d'un octet.
#
# En contexte compact, les trois blocs dont le contenu est celui du DOCUMENT ou
# de l'étudiant (la page, la réponse évaluée, les passages trouvés ailleurs)
# sont bornés en tokens ESTIMÉS (`*_tokens`, tokenizer du modèle actif) et pas
# seulement en caractères : une page de chinois ou un tableau de chiffres coûte
# un token par caractère, trois fois une page de français. Une borne en
# caractères n'y garantissait rien ; celle-ci tient quel que soit le document.
# La page a une borne PAR TÂCHE : c'est la place que laisse son squelette (~600
# tokens pour la question compacte, ~1 650 pour l'évaluation) une fois les
# autres blocs comptés à leur maximum — calibrée et vérifiée par le banc.
@dataclass(frozen=True)
class PromptLimits:
    page_chars: int        # texte de la page visible (question, évaluation, réponse, reformulation)
    answer_chars: int      # réponse de l'étudiant soumise à l'évaluation
    history: int           # questions-réponses de la séance relayées (question, évaluation)
    exchanges: int         # échanges récents relayés à la réponse libre
    quotes: int            # extraits sélectionnés, et autant de surlignages
    struggles: int         # difficultés passées
    rag_top_k: int         # passages trouvés ailleurs (question ordinaire)
    rag_search_top_k: int  # … quand la recherche s'élargit
    rag_chars: int         # longueur d'un passage
    rag_table_chars: int   # longueur d'une table (coupée entre deux rangées)
    last_turn_chars: int   # une réplique du dernier échange (réponse libre)
    page_tokens: dict[str, int] | None = None  # par tâche ; None : contexte plein
    answer_tokens: int | None = None
    rag_tokens: int | None = None     # pour l'ensemble des passages
    last_turn_tokens: int | None = None  # pour tout le dernier échange


PROMPT_LIMITS_FULL = PromptLimits(
    page_chars=3500, answer_chars=2000, history=5, exchanges=4, quotes=5, struggles=3,
    rag_top_k=ASSISTANT_RAG_TOP_K, rag_search_top_k=ASSISTANT_RAG_SEARCH_TOP_K,
    rag_chars=ASSISTANT_RAG_MAX_CHARS, rag_table_chars=ASSISTANT_RAG_TABLE_CHUNK_CHARS,
    last_turn_chars=600,
)
PROMPT_LIMITS_COMPACT = PromptLimits(
    page_chars=2000, answer_chars=1200, history=2, exchanges=2, quotes=2, struggles=2,
    rag_top_k=2, rag_search_top_k=3, rag_chars=500, rag_table_chars=900, last_turn_chars=400,
    page_tokens={"question": 900, "evaluation": 500, "assistant_answer": 380, "rephrasing": 1100,
                 "curiosity_hook": 800},
    # `last_turn_tokens` : le dernier échange (question de suivi), que le
    # palier minuscule ne reçoit pas (llm/prompts._previous_turn_block). Quand
    # il est dans le prompt, il prend autant sur `rag_tokens` : mesuré le
    # 2026-10-19, Gemma en mode économe garde 42 tokens de marge au pire cas.
    answer_tokens=250, rag_tokens=400, last_turn_tokens=150,
)


def prompt_limits() -> PromptLimits:
    """Les limites du contexte de travail courant (cf. `compact_context`)."""
    return PROMPT_LIMITS_COMPACT if compact_context() else PROMPT_LIMITS_FULL
