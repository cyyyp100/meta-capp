# llm/prompts.py — Prompts JSON pour MetaC-App (bilingue FR/EN)
from __future__ import annotations

import json
import random

import i18n as _i18n
from config.settings import (
    DOCUMENT_DIGEST_PROMPT_CHARS,
    LANGUAGE_SCRIPTS,
    LATIN_SCRIPT,
    SCRIPT_HINTS,
    SCRIPTS,
    TONAL_LANGUAGES,
)


def _t(fr: str, en: str) -> str:
    """Return fr or en string based on current UI language."""
    return en if _i18n.current_lang() == "en" else fr


QUESTION_TYPE_GUIDE: tuple[tuple[str, str, str, str], ...] = (
    (
        "qcm",
        "QCM",
        "vérification rapide de compréhension factuelle",
        "Choisis la bonne proposition parmi 3 ou 4 réponses.",
    ),
    (
        "open",
        "Question ouverte",
        "expression libre, reformulation personnelle",
        "Résume en une phrase l'idée principale du passage.",
    ),
    (
        "comprehension",
        "Question de compréhension textuelle",
        "extraction d'une information explicitement donnée",
        "Quelle définition est donnée pour cette notion ?",
    ),
    (
        "application",
        "Question d'application",
        "mise en pratique sur un calcul, un exemple numérique ou un cas particulier",
        "Applique la relation du passage à ce petit cas.",
    ),
    (
        "curiosity",
        "Question de curiosité / inductive",
        "création d'un déséquilibre cognitif qui pousse à chercher le pourquoi",
        "T'es-tu déjà demandé comment cette idée peut rester vraie dans ce cas ?",
    ),
    (
        "visualization",
        "Exercice de visualisation",
        "vision dans l'espace, schéma mental, représentation d'un mécanisme",
        "Trace mentalement la situation : que vois-tu changer ?",
    ),
    (
        "metacognition",
        "Question métacognitive",
        "prise de conscience du raisonnement utilisé",
        "Comment as-tu trouvé ta réponse ? Qu'as-tu modifié dans ton raisonnement ?",
    ),
    (
        "anticipation",
        "Anticipation / auto-évaluation",
        "surveillance de la compréhension et repérage des difficultés possibles",
        "Qu'est-ce qui pourrait te poser problème ici ?",
    ),
)

QUESTION_TYPE_GUIDE_EN: tuple[tuple[str, str, str, str], ...] = (
    (
        "qcm",
        "MCQ",
        "quick factual comprehension check",
        "Choose the correct answer from 3 or 4 options.",
    ),
    (
        "open",
        "Open question",
        "free expression, personal reformulation",
        "Summarize the main idea of the passage in one sentence.",
    ),
    (
        "comprehension",
        "Reading comprehension",
        "extraction of explicitly stated information",
        "What definition is given for this concept?",
    ),
    (
        "application",
        "Application question",
        "practice on a calculation, numerical example, or specific case",
        "Apply the formula from the passage to this small case.",
    ),
    (
        "curiosity",
        "Curiosity / inductive question",
        "creating cognitive imbalance to push the learner to seek the why",
        "Have you ever wondered how this idea can hold true in this case?",
    ),
    (
        "visualization",
        "Visualization exercise",
        "spatial vision, mental diagram, representation of a mechanism",
        "Mentally trace the situation: what do you see changing?",
    ),
    (
        "metacognition",
        "Metacognitive question",
        "awareness of the reasoning process used",
        "How did you arrive at your answer? What did you adjust in your reasoning?",
    ),
    (
        "anticipation",
        "Anticipation / self-assessment",
        "monitoring comprehension and spotting possible difficulties ahead",
        "What might be challenging for you here?",
    ),
)


def _format_struggles(past_struggles: list[dict] | None) -> str:
    """Liste compacte des difficultés récurrentes (budget contexte serré)."""
    lines: list[str] = []
    for item in (past_struggles or [])[:3]:
        question = " ".join(str((item or {}).get("question") or "").split())[:120]
        if not question:
            continue
        chapter = str((item or {}).get("chapter_title") or "").strip()
        try:
            fails = int((item or {}).get("fail_count") or 0)
        except (TypeError, ValueError):
            fails = 0
        suffix = f" — {chapter}" if chapter else ""
        count = _t(f" ({fails} échecs)", f" ({fails} failures)") if fails else ""
        lines.append(f"- « {question} »{suffix}{count}")
    return "\n".join(lines)


def _format_related_flashcards(cards: list[dict] | None) -> str:
    lines: list[str] = []
    for card in (cards or [])[:3]:
        front = " ".join(str((card or {}).get("front") or "").split())[:100]
        if front:
            lines.append(f"- {front}")
    return "\n".join(lines)


def _format_quote_lines(items: list[str] | None, limit: int = 5) -> str:
    """Liste compacte de citations (extraits sélectionnés / surlignages)."""
    lines: list[str] = []
    for raw in (items or [])[:limit]:
        text = " ".join(str(raw or "").split())[:200]
        if text:
            lines.append(f"- « {text} »")
    return "\n".join(lines)


def _student_context_block(
    selected_snippets: list[str] | None,
    user_highlights: list[str] | None,
) -> str:
    """Bloc optionnel : extraits ajoutés au contexte + passages surlignés.

    Inséré dans les prompts de réponse / question / intervention pour que le LLM
    tienne compte de ce que l'étudiant a explicitement mis en avant.
    """
    parts: list[str] = []
    snippets = _format_quote_lines(selected_snippets)
    if snippets:
        parts.append(_t(
            "Extraits sélectionnés par l'étudiant (à prendre en compte en priorité) :\n" + snippets,
            "Snippets selected by the student (treat as a priority):\n" + snippets,
        ))
    highlights = _format_quote_lines(user_highlights)
    if highlights:
        parts.append(_t(
            "Passages déjà surlignés par l'étudiant (lui tiennent à cœur) :\n" + highlights,
            "Passages already highlighted by the student (matter to them):\n" + highlights,
        ))
    if not parts:
        return ""
    return "\n" + "\n\n".join(parts) + "\n"


def _retrieved_passages_block(passages: list[dict] | None) -> str:
    """Bloc optionnel : passages pertinents trouvés AILLEURS dans le document (RAG).

    Inséré uniquement dans le prompt de réponse à une question. Chaque passage
    indique sa page source pour que le LLM puisse la citer en clair dans sa réponse.
    """
    lines: list[str] = []
    for item in (passages or [])[:3]:
        text = " ".join(str((item or {}).get("text") or "").split())[:400]
        if not text:
            continue
        page = (item or {}).get("page")
        prefix = f"(p.{page}) " if page else ""
        lines.append(f"- {prefix}« {text} »")
    if not lines:
        return ""
    body = "\n".join(lines)
    return "\n" + _t(
        "Passages pertinents trouvés ailleurs dans le document (recherche automatique) :\n" + body,
        "Relevant passages found elsewhere in the document (automatic search):\n" + body,
    ) + "\n"


def build_question_prompt(
    paragraph: str,
    chapter_title: str = "",
    doc_title: str = "",
    metacog_profile: dict | None = None,
    history: list[dict] | None = None,
    session_gauges: dict | None = None,
    recent_question_types: list[str] | None = None,
    preferred_question_type: str | None = None,
    source_block_id: str | None = None,
    has_existing_question: bool = False,
    standalone: bool = False,
    past_struggles: list[dict] | None = None,
    user_highlights: list[str] | None = None,
) -> str:
    history = history or []
    session_gauges = session_gauges or {}
    student_context = _student_context_block(None, user_highlights)
    recent_question_types = _normalize_recent_question_types(
        recent_question_types or _question_types_from_history(history)
    )
    adaptation = _question_adaptation(
        paragraph=paragraph,
        gauges=session_gauges,
        recent_question_types=recent_question_types,
        preferred_question_type=preferred_question_type,
        has_existing_question=has_existing_question,
        standalone=standalone,
    )
    sid = source_block_id or ""

    if history:
        history_instruction = _t(
            "\nQuand c'est pédagogiquement pertinent, fais un lien explicite avec une réponse précédente"
            " de l'étudiant, par exemple : \"Tu avais dit quelques paragraphes plus tôt que...\"."
            " Le lien doit aider l'étudiant à consolider sa compréhension, sans le culpabiliser.",
            "\nWhen pedagogically relevant, make an explicit link to a previous student answer,"
            " for example: \"Earlier you mentioned that...\"."
            " The link should help the student consolidate their understanding, without making them feel guilty.",
        )
    else:
        history_instruction = ""

    struggles = _format_struggles(past_struggles)
    if struggles:
        struggles_block = _t(
            f"- Difficultés passées (questions ratées lors de sessions précédentes) :\n{struggles}\n",
            f"- Past struggles (questions failed in previous sessions):\n{struggles}\n",
        )
        struggles_instruction = _t(
            "\nSi le paragraphe touche à une difficulté passée listée dans le contexte, recible cette notion"
            " avec une question NOUVELLE (autre angle, autre forme) ; ne repose jamais la même question à"
            " l'identique, et ne re-vérifie pas ce que l'étudiant maîtrise déjà.",
            "\nIf the paragraph relates to a past struggle listed in the context, re-target that notion"
            " with a NEW question (different angle, different form); never repeat the same question verbatim,"
            " and do not re-check what the student already masters.",
        )
    else:
        struggles_block = ""
        struggles_instruction = ""

    if standalone:
        question_instruction = _t(
            "Tu reçois une question issue d'une session de lecture, avec sa réponse attendue. "
            "Reformule-la en une question de révision totalement autonome, compréhensible sans "
            "avoir lu le document source. "
            "Remplace impérativement toute formule contextuelle ('selon le passage', "
            "'d'après ce texte', 'dans ce paragraphe', 'le passage', 'd'après le texte') "
            "par le concept ou la donnée précise. "
            "Exemple : 'Selon le passage, qu'est-ce qu'une suite $u$ ?' → "
            "'Donne la définition d'une suite numérique $u_n$.' "
            "Choisis le question_type le plus adapté au contenu (qcm si possible).",
            "You receive a question from a reading session with its expected answer. "
            "Rephrase it as a fully standalone review question, understandable without having read the source document. "
            "You must replace any contextual phrasing ('according to the passage', 'based on this text', "
            "'in this paragraph', 'the passage', 'from the text') with the precise concept or data. "
            "Example: 'According to the passage, what is a sequence $u$?' → "
            "'Give the definition of a numerical sequence $u_n$.' "
            "Choose the most suitable question_type for the content (qcm if possible).",
        )
    elif has_existing_question:
        question_instruction = _t(
            "Le paragraphe contient déjà une ou plusieurs questions. "
            "Demande à l'étudiant d'y répondre directement. "
            "Tu peux ajouter UNE question complémentaire si c'est pédagogiquement pertinent, "
            "mais la question principale doit être celle du texte d'origine. "
            "Choisis question_type selon la forme de la question déjà présente ; "
            "si elle ne correspond à aucun type précis, utilise \"comprehension\".",
            "The paragraph already contains one or more questions. "
            "Ask the student to answer them directly. "
            "You may add ONE supplementary question if pedagogically relevant, "
            "but the main question must be the one from the original text. "
            "Choose question_type based on the form of the existing question; "
            "if it does not match any specific type, use \"comprehension\".",
        )
    else:
        question_instruction = _t(
            "Choisis d'abord UN type pédagogique dans la liste ci-dessous, puis génère UNE question "
            "obligatoire adaptée à ce type. Ne choisis pas toujours \"comprehension\" : varie selon "
            "le paragraphe, le profil et l'effort d'apprentissage le plus utile.",
            "First choose ONE pedagogical type from the list below, then generate ONE required question "
            "adapted to that type. Do not always choose \"comprehension\": vary based on the paragraph, "
            "the profile, and the most useful learning effort.",
        )

    _na = _t("non renseigné", "not specified")
    _types_str = ", ".join(f'"{item[0]}"' for item in QUESTION_TYPE_GUIDE)

    if _i18n.current_lang() == "en":
        _standalone_constraint = (
            "- The question must be understandable without any source document: never write "
            "'according to the passage', 'based on this text', or any contextual reference."
            if standalone else
            "- The question must depend on the provided paragraph, not on external knowledge."
        )
        return f"""You are the adaptive learning companion of MetaC-App.

Context:
- Document: {doc_title or _na}
- Chapter: {chapter_title or _na}
- Metacognitive profile: {_json(metacog_profile or {})}
- Current session gauges: {_json(session_gauges)}
- Recent question types: {_json(recent_question_types)}
- Last 5 session answers: {_json(history)}
{struggles_block}{student_context}
Paragraph to assess:
---
{paragraph[:3500]}
---

Available question types:
{_question_type_guide()}

Type selection rules:
- Select exactly one question_type value from: {_types_str}.
- For a definition or dense fact, prefer "qcm" or "comprehension".
- For a central idea to reformulate, prefer "open".
- For a formula, calculation, example, table, or specific case, prefer "application".
- For a figure, diagram, spatial relation, or process to visualize, prefer "visualization".
- To provoke an intuition or hypothesis from the paragraph, prefer "curiosity".
- To make the student articulate their reasoning strategy, prefer "metacognition".
- To anticipate a difficulty, uncertainty, or risk of error, prefer "anticipation".
- The chosen type must stay faithful to the paragraph: do not require external knowledge to answer.
- For "curiosity", the question may open a lead, but the expected answer must remain grounded in the passage.
- For "metacognition" and "anticipation", expected_answer describes elements expected in a good answer, not a single solution.

Mandatory adaptive rules:
{_adaptive_instruction(adaptation)}

{question_instruction}
Adapt difficulty to the profile without making the question punitive.
{history_instruction}{struggles_instruction}
Respond only in valid JSON, without Markdown, in the exact format:
{{
  "question_type": "qcm" or "open" or "comprehension" or "application" or "curiosity" or "visualization" or "metacognition" or "anticipation",
  "question": "question text",
  "choices": ["A", "B", "C", "D"],
  "expected_answer": "short but precise expected answer",
  "evaluation_criteria": ["validation criterion 1", "validation criterion 2"],
  "session_hint": "",
  "source_block_id": "{sid}",
  "paragraph_mask": {{
    "enabled": false,
    "start_char": 0,
    "end_char": 0,
    "placeholder": "temporarily masked answer"
  }}
}}

Constraints:
- Write every user-facing string in English: question, choices, expected_answer, evaluation_criteria, session_hint, and paragraph_mask.placeholder.
- If question_type is not "qcm", choices must be [].
- If question_type is "qcm", choices contains 3 or 4 plausible options and expected_answer indicates the correct one.
- If a target pedagogical type is indicated in the adaptive rules, use that question_type unless clearly incompatible with the paragraph content.
- If session_hint is set, it must be a short sentence helping the student regulate their session, without replacing the question.
- Always write mathematical expressions between $...$ (inline) or $$...$$ (display) in valid LaTeX.
- In JSON, escape each LaTeX backslash with a double backslash: write "$u_n \\\\sim n$", never "$u_n \\sim n$".
- Never remove the backslash from LaTeX commands: write \\text{{u}}_n, not ext{{u}}_n.
- The source text may contain raw Unicode symbols (≠, →, ∞): treat them as mathematical content.
- If the paragraph contains [Table: ...] or a [Table N×M rows×columns] annotation, ask a question about the data or trends in the table.
- If the paragraph mentions [Figure: ...] or [Figure on this page: ...], use the caption to contextualize your question.
- An image is attached: it is the FULL PDF page the student is reading. The text below is its (imperfect) extraction. Treat the image as the primary source — base your question on what is actually visible on the page (text, formulas, figures, tables) and use the image to resolve any OCR ambiguity in the text.
- paragraph_mask.enabled is true only if masking a short portion of the paragraph genuinely helps the student reason without copying.
- If paragraph_mask.enabled is true, start_char and end_char are exact indices in the provided paragraph.
{_standalone_constraint}"""

    _standalone_constraint_fr = (
        "- La question doit être compréhensible sans aucun document source : n'écris jamais 'selon le passage', "
        "'d'après ce texte' ou toute référence contextuelle."
        if standalone else
        "- La question doit dépendre du paragraphe fourni, pas d'un savoir externe."
    )
    return f"""Tu es le compagnon d'apprentissage adaptatif de MetaC-App.

Contexte :
- Document : {doc_title or _na}
- Chapitre : {chapter_title or _na}
- Profil métacognitif : {_json(metacog_profile or {})}
- Jauges courantes de la session : {_json(session_gauges)}
- Types de questions récents : {_json(recent_question_types)}
- 5 dernières réponses de la session : {_json(history)}
{struggles_block}{student_context}
Paragraphe à vérifier :
---
{paragraph[:3500]}
---

Types de questions disponibles :
{_question_type_guide()}

Règles de choix du type :
- Sélectionne exactement une valeur question_type parmi : {_types_str}.
- Pour une définition ou un fait dense, privilégie "qcm" ou "comprehension".
- Pour une idée centrale à reformuler, privilégie "open".
- Pour une formule, un calcul, un exemple, un tableau ou un cas particulier, privilégie "application".
- Pour une figure, un schéma, une relation spatiale ou un processus à se représenter, privilégie "visualization".
- Pour provoquer une intuition ou une hypothèse à partir du paragraphe, privilégie "curiosity".
- Pour faire expliciter la stratégie de réponse, privilégie "metacognition".
- Pour faire repérer à l'avance une difficulté, une incertitude ou un risque d'erreur, privilégie "anticipation".
- Le type choisi doit rester fidèle au paragraphe : n'exige pas de connaissances externes pour répondre.
- Pour "curiosity", la question peut ouvrir une piste, mais la réponse attendue doit rester ancrée dans le passage.
- Pour "metacognition" et "anticipation", expected_answer décrit les éléments attendus dans une bonne réponse, pas une solution unique.

Règles adaptatives obligatoires :
{_adaptive_instruction(adaptation)}

{question_instruction}
Adapte la difficulté au profil sans rendre la question punitive.
{history_instruction}{struggles_instruction}
Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "question_type": "qcm" ou "open" ou "comprehension" ou "application" ou "curiosity" ou "visualization" ou "metacognition" ou "anticipation",
  "question": "texte de la question",
  "choices": ["A", "B", "C", "D"],
  "expected_answer": "réponse attendue courte mais précise",
  "evaluation_criteria": ["critère de validation 1", "critère de validation 2"],
  "session_hint": "",
  "source_block_id": "{sid}",
  "paragraph_mask": {{
    "enabled": false,
    "start_char": 0,
    "end_char": 0,
    "placeholder": "réponse masquée temporairement"
  }}
}}

Contraintes :
- Écris tous les champs visibles par l'utilisateur en français : question, choices, expected_answer, evaluation_criteria, session_hint et paragraph_mask.placeholder.
- Si question_type ne vaut pas "qcm", choices doit être [].
- Si question_type vaut "qcm", choices contient 3 ou 4 choix plausibles et expected_answer indique le bon choix.
- Si un Type pédagogique cible est indiqué dans les règles adaptatives, utilise ce question_type sauf contradiction manifeste avec le contenu du paragraphe.
- Si session_hint est renseigné, il doit être une phrase courte qui aide l'étudiant à réguler sa session, sans remplacer la question.
- Écris TOUJOURS les expressions mathématiques entre $...$ (inline) ou $$...$$ (display) en LaTeX valide.
- Dans le JSON, échappe chaque backslash LaTeX avec un double backslash : écris "$u_n \\\\sim n$", jamais "$u_n \\sim n$".
- Ne supprime jamais le backslash des commandes LaTeX : écris \\text{{u}}_n, pas ext{{u}}_n.
- Le texte source peut contenir des symboles Unicode bruts (≠, →, ∞) : traite-les comme du contenu mathématique.
- Si le paragraphe contient [Tableau: ...] ou une annotation [Tableau N×M lignes×colonnes], pose une question sur les données ou les tendances du tableau.
- Si le paragraphe mentionne [Figure: ...] ou [Figure sur cette page : ...], utilise la légende pour contextualiser ta question.
- Une image est jointe : c'est la PAGE PDF COMPLÈTE que lit l'étudiant. Le texte ci-dessous en est l'extraction (imparfaite). Considère l'image comme la source primaire — fonde ta question sur ce qui est réellement visible sur la page (texte, formules, figures, tableaux) et sers-toi de l'image pour lever toute ambiguïté OCR du texte.
- paragraph_mask.enabled vaut true seulement si masquer une courte portion du paragraphe aide vraiment l'étudiant à raisonner sans recopier.
- Si paragraph_mask.enabled vaut true, start_char et end_char sont des indices exacts dans le paragraphe fourni.
{_standalone_constraint_fr}"""


def _question_type_guide() -> str:
    guide = QUESTION_TYPE_GUIDE_EN if _i18n.current_lang() == "en" else QUESTION_TYPE_GUIDE
    sep = "Example:" if _i18n.current_lang() == "en" else "Exemple :"
    return "\n".join(
        f'- "{key}" — {label} : {purpose}. {sep} {example}'
        for key, label, purpose, example in guide
    )


def _question_adaptation(
    paragraph: str,
    gauges: dict,
    recent_question_types: list[str],
    preferred_question_type: str | None,
    has_existing_question: bool,
    standalone: bool,
) -> dict:
    valid_types = tuple(item[0] for item in QUESTION_TYPE_GUIDE)
    explicit = _normalize_question_type(preferred_question_type, valid_types)
    if explicit:
        return {
            "preferred_type": explicit,
            "strategy": _t("type fourni par le contexte appelant", "type provided by calling context"),
            "attention_break": _gauge(gauges, "attention") < 45.0,
            "simplify": _gauge(gauges, "context_comprehension") < 45.0,
        }

    attention = _gauge(gauges, "attention")
    comprehension = _gauge(gauges, "context_comprehension")
    curiosity = _gauge(gauges, "curiosity")
    meta_cognition = _gauge(gauges, "meta_cognition")

    if has_existing_question and not standalone:
        return {
            "preferred_type": "",
            "strategy": _t(
                "répondre à la question déjà présente dans le paragraphe",
                "answer the question already present in the paragraph",
            ),
            "attention_break": attention < 45.0,
            "simplify": comprehension < 45.0,
        }

    if attention < 45.0:
        weights: dict[str, float] = {
            "qcm": 1.0,
            "open": 1.0,
            "comprehension": 1.0,
            "application": 0.85,
            "curiosity": 0.8,
            "visualization": 0.7,
            "metacognition": 1.8,
            "anticipation": 1.2,
        }
        _apply_recent_penalty(weights, recent_question_types)
        preferred = _weighted_question_type(weights)
        return {
            "preferred_type": preferred,
            "strategy": _t("pause_attention", "attention_break"),
            "attention_break": True,
            "simplify": True,
        }

    weights = {
        "qcm": 1.0,
        "open": 1.0,
        "comprehension": 1.0,
        "application": 0.85,
        "curiosity": 0.8,
        "visualization": 0.7,
        "metacognition": 0.7,
        "anticipation": 0.7,
    }
    lower = (paragraph or "").lower()
    if "$" in paragraph or "\\" in paragraph or any(sign in paragraph for sign in ("=", "≤", "≥", "≈", "≠", "∑", "∫")):
        weights["application"] += 1.8
    if "[tableau" in lower or "|" in paragraph:
        weights["application"] += 1.5
    if "[figure" in lower or "schéma" in lower or "schema" in lower:
        weights["visualization"] += 2.0

    strategy = _t("diversifier les types de questions", "diversify question types")
    if comprehension < 45.0:
        weights["qcm"] += 2.6
        weights["comprehension"] += 2.2
        weights["application"] *= 0.65
        weights["visualization"] *= 0.75
        strategy = _t(
            "simplifier car la compréhension du contexte est basse",
            "simplify because context comprehension is low",
        )
    if curiosity < 45.0:
        weights["curiosity"] += 3.4
        weights["open"] += 0.4
        strategy = _t("relancer curiosité et créativité", "boost curiosity and creativity")
    if meta_cognition < 38.0:
        weights["metacognition"] += 1.2
        weights["anticipation"] += 0.5
        strategy = _t("renforcer la méta-cognition", "strengthen metacognition")

    # cap de fréquence : pénalise fortement la métacognition si posée récemment
    if any(t in ("metacognition", "anticipation") for t in recent_question_types[-2:]):
        weights["metacognition"] *= 0.12
        weights["anticipation"] *= 0.25

    _apply_recent_penalty(weights, recent_question_types)
    preferred = _weighted_question_type(weights)
    return {
        "preferred_type": preferred,
        "strategy": strategy,
        "attention_break": False,
        "simplify": comprehension < 45.0,
    }


def _adaptive_instruction(adaptation: dict) -> str:
    preferred = adaptation.get("preferred_type") or ""
    default_strategy = _t("diversifier les questions", "diversify question types")
    lines = [
        f"- {_t('Stratégie', 'Strategy')} : {adaptation.get('strategy') or default_strategy}.",
    ]
    if preferred:
        lines.append(
            f'- {_t("Type pédagogique cible", "Target pedagogical type")} : "{preferred}".'
        )
    if adaptation.get("attention_break"):
        lines.append(
            _t(
                "- Attention actuelle sous le seuil 45 : renseigne session_hint avec une suggestion "
                "explicite de pause courte avant de continuer, puis pose une question très légère.",
                "- Current attention below threshold 45: set session_hint with an explicit suggestion "
                "for a short break before continuing, then ask a very light question.",
            )
        )
    if adaptation.get("simplify"):
        lines.append(
            _t(
                "- Compréhension du contexte basse : formule une question simple, en une étape, "
                "avec une réponse attendue courte et concrète.",
                "- Context comprehension is low: formulate a simple, single-step question "
                "with a short and concrete expected answer.",
            )
        )
    lines.append(
        _t(
            "- Assure une vraie diversité sur la session : évite de répéter le même question_type "
            "quand le contenu permet un autre type pertinent.",
            "- Ensure genuine diversity across the session: avoid repeating the same question_type "
            "when the content allows another relevant type.",
        )
    )
    return "\n".join(lines)


def _question_types_from_history(history: list[dict]) -> list[str]:
    result: list[str] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        qtype = item.get("question_type")
        if isinstance(qtype, str) and qtype:
            result.append(qtype)
    return result


def _normalize_recent_question_types(values: list[str]) -> list[str]:
    valid = {item[0] for item in QUESTION_TYPE_GUIDE}
    return [value for value in (_normalize_question_type(v, tuple(valid)) for v in values or []) if value]


def _normalize_question_type(value: str | None, valid_types: tuple[str, ...]) -> str:
    if not isinstance(value, str):
        return ""
    token = value.strip().lower().replace("é", "e").replace("è", "e")
    aliases = {
        "visualisation": "visualization",
        "metacognition": "metacognition",
        "meta_cognition": "metacognition",
        "curiosite": "curiosity",
        "question_ouverte": "open",
        "comprehension_textuelle": "comprehension",
    }
    token = aliases.get(token, token)
    return token if token in valid_types else ""


def _apply_recent_penalty(weights: dict[str, float], recent_question_types: list[str]) -> None:
    for index, qtype in enumerate(reversed(recent_question_types[-4:]), start=1):
        if qtype in weights:
            weights[qtype] *= 0.18 if index == 1 else 0.45


def _weighted_question_type(weights: dict[str, float]) -> str:
    items = [(key, max(0.05, float(value))) for key, value in weights.items()]
    total = sum(value for _key, value in items)
    threshold = random.random() * total
    cumulative = 0.0
    for key, weight in items:
        cumulative += weight
        if threshold <= cumulative:
            return key
    return items[-1][0]


def _gauge(gauges: dict, key: str) -> float:
    try:
        return float((gauges or {}).get(key, 50.0))
    except (TypeError, ValueError):
        return 50.0


# Dimension métacognitive principale visée par chaque type de question. Sert à
# guider le LLM (signal plus marqué sur la bonne jauge) ET les jauges côté backend
# (metacog/gauges.QUESTION_TYPE_TARGET_GAUGES, source canonique pour le calcul).
_EVAL_DIMENSION_LABELS = {
    "attention": ("l'attention / la concentration", "attention / focus"),
    "context_comprehension": ("la compréhension du contexte", "context comprehension"),
    "creativity": ("la créativité", "creativity"),
    "retention": ("la rétention / mémorisation", "retention / memory"),
    "curiosity": ("la curiosité", "curiosity"),
    "meta_cognition": ("la métacognition", "metacognition"),
}
_EVAL_TYPE_DIMENSIONS = {
    "qcm": ("retention", "attention"),
    "open": ("context_comprehension", "creativity"),
    "comprehension": ("context_comprehension",),
    "application": ("context_comprehension", "retention"),
    "curiosity": ("curiosity",),
    "visualization": ("creativity", "context_comprehension"),
}


def _eval_dimension_hint(question_type: str) -> tuple[str, str]:
    """Phrase guidant le LLM à marquer le signal sur la dimension du type.

    Vide pour metacognition/anticipation (pilotées par le verdict côté jauges).
    Renvoie (fr, en)."""
    dims = _EVAL_TYPE_DIMENSIONS.get(question_type or "")
    if not dims:
        return "", ""
    fr_labels = " et ".join(_EVAL_DIMENSION_LABELS[d][0] for d in dims)
    en_labels = " and ".join(_EVAL_DIMENSION_LABELS[d][1] for d in dims)
    fr = (
        f"- Cette question est de type \"{question_type}\" : dans metacog_signals, "
        f"marque plus nettement le signal de {fr_labels} (positif si réussi, négatif sinon)."
    )
    en = (
        f"- This question is of type \"{question_type}\": in metacog_signals, "
        f"emphasize the signal for {en_labels} more clearly (positive if successful, negative otherwise)."
    )
    return fr, en


def build_evaluation_prompt(
    question: dict,
    user_answer: str,
    paragraph: str,
    metacog_profile: dict | None = None,
    history: list[dict] | None = None,
    past_struggles: list[dict] | None = None,
) -> str:
    history = history or []
    if history:
        history_instruction = _t(
            "\nSi une réponse antérieure aide à expliquer le verdict ou le feedback, référence-la explicitement"
            " avec tact (\"Tu avais déjà repéré...\", \"Tu avais affirmé plus tôt...\") et montre le lien logique.",
            "\nIf a previous answer helps explain the verdict or feedback, reference it explicitly"
            " and tactfully (\"You had already noticed...\", \"You mentioned earlier...\") and show the logical link.",
        )
    else:
        history_instruction = ""

    struggles = _format_struggles(past_struggles)
    if struggles:
        struggles_block = _t(
            f"Difficultés passées de l'étudiant (sessions précédentes) :\n{struggles}\n",
            f"Student's past struggles (previous sessions):\n{struggles}\n",
        )
        history_instruction += _t(
            "\nSi l'erreur actuelle rejoint une difficulté passée listée, mentionne-le avec tact dans feedback"
            " (\"Comme la dernière fois sur...\") et propose un angle nouveau pour la dépasser.",
            "\nIf the current mistake matches a listed past struggle, tactfully mention it in feedback"
            " (\"Like last time on...\") and suggest a new angle to overcome it.",
        )
    else:
        struggles_block = ""

    question_type = (question or {}).get("question_type", "")
    _dim_hint_fr, _dim_hint_en = _eval_dimension_hint(question_type)
    if question_type in ("metacognition", "anticipation"):
        _flashcard_constraint = _t(
            "- flashcard DOIT être null : les questions de type métacognitif et d'anticipation "
            "ne génèrent jamais de flashcard.",
            "- flashcard MUST be null: metacognitive and anticipation question types never generate a flashcard.",
        )
        _flashcard_example = "null"
    else:
        _flashcard_constraint = _t(
            "- flashcard : fournis TOUJOURS une flashcard. "
            "front doit être une question autonome, compréhensible sans avoir lu le document : "
            "si la question fait référence au passage ('selon le passage', 'd'après ce texte'…), "
            "remplace cette référence par le concept ou la donnée précise tirée du paragraphe — "
            "intègre le contexte dans la logique même de la question, pas en préambule. "
            "Exemple : 'Selon le passage, qu\\'est-ce qu\\'une suite ?' → 'Donne la définition d\\'une suite numérique $u_n$.' "
            "back doit être la réponse attendue concise, fidèle à expected_answer.",
            "- flashcard: ALWAYS provide a flashcard. "
            "front must be a standalone question, understandable without having read the document: "
            "if the question references the passage ('according to the passage', 'based on this text'…), "
            "replace that reference with the precise concept or data from the paragraph — "
            "embed the context into the logic of the question itself, not as a preamble. "
            "Example: 'According to the passage, what is a sequence?' → 'Give the definition of a numerical sequence $u_n$.' "
            "back must be the concise expected answer, faithful to expected_answer.",
        )
        _flashcard_example = (
            '{"front": "standalone reformulated question", "back": "concise answer",'
            ' "tags": ["tag1", "tag2"], "difficulty": 2}'
        )

    if _i18n.current_lang() == "en":
        return f"""You are evaluating a student's answer in MetaC-App.

Metacognitive profile: {_json(metacog_profile or {})}
Recent session history: {_json(history)}
{struggles_block}
Source paragraph:
---
{paragraph[:3500]}
---

Question:
{_json(question)}

Student's answer:
---
{user_answer[:2000]}
---

Evaluate strictly against the paragraph and the expected answer.
{history_instruction}
Respond only in valid JSON, without Markdown. Keep the output concise:
{{
  "verdict": "partial",
  "feedback": "brief and useful feedback",
  "completion": "element to add if partial, otherwise empty string",
  "hint": "hint if incorrect, otherwise empty string",
  "metacog_signals": {{
    "context_comprehension": 0.0,
    "creativity": 0.0,
    "attention": 0.0,
    "retention": 0.0,
    "curiosity": 1.0,
    "meta_cognition": 0.0
  }},
  "curiosity_signals": {{
    "asked_follow_up_question": false,
    "asked_for_clarification": false,
    "asked_for_example": false,
    "explored_beyond_required_answer": false
  }},
  "creativity_signals": {{
    "goes_beyond_prompt": false,
    "makes_connections": false,
    "uses_analogy": false,
    "personal_reformulation": false,
    "original_hypothesis": false,
    "depth_of_reflection": 0.0
  }},
  "answer_to_user_question": null,
  "flashcard": {_flashcard_example},
  "highlights": [{{"quote": "EXACT quote copied from the source paragraph (8 to 25 words)", "purpose": "key"}}]
}}

Constraints:
- Metacognitive signals are between -2.0 and 2.0.
- highlights: 0 to 3 quotes copied WORD FOR WORD from the source paragraph (never rephrased), pointing at the passages that justify the verdict or correct the mistake. purpose is "key" (key passage), "explain" (passage your feedback explains) or "reference" (supporting passage). Use an empty list if nothing relevant.
- verdict must be exactly "correct", "partial", or "incorrect".
- meta_cognition stays at 0.0 here: it will only be evaluated in the end-of-session debrief.
- verdict is "correct" if the expected idea is present, even if the student adds a personal reflection, a caveat, or a question that does not contradict the paragraph.
- verdict is "partial" only if the main idea is present but too imprecise or incomplete.
- verdict is "incorrect" only if the main idea is absent, contradicted, or off-topic.
- hint must only be set if verdict is "incorrect". Otherwise hint must be an empty string.
- completion must only be set if verdict is "partial". Otherwise completion must be an empty string.
- If verdict is "correct", feedback must be a short, specific sentence validating what the student understood — cite a precise element from their answer or the paragraph. Never write simply "Correct" or "Good answer": always add a nuance, a link, or a useful pedagogical remark.
- If the student's answer contains a follow-up question, a clarification request, an example request, or a request for deeper understanding, increase the curiosity signal and set curiosity_signals.
- Do not answer this question in answer_to_user_question during evaluation: set answer_to_user_question to null. The follow-up question will be handled by the dedicated "Ask a question about this paragraph" field.
- If the answer goes beyond the minimum expected, makes connections, reformulates in their own words, proposes an analogy or a hypothesis, increase the creativity signal and set creativity_signals.
- An image is attached: it is the full PDF page being read (the text is its extraction). Use it to confirm notation and stay faithful to what is actually on the page.
{_dim_hint_en}
{_flashcard_constraint}
- Do not give the complete solution directly if verdict is incorrect."""

    return f"""Tu évalues une réponse d'étudiant dans MetaC-App.

Profil métacognitif : {_json(metacog_profile or {})}
Historique récent de la session : {_json(history)}
{struggles_block}
Paragraphe source :
---
{paragraph[:3500]}
---

Question :
{_json(question)}

Réponse de l'étudiant :
---
{user_answer[:2000]}
---

Évalue strictement par rapport au paragraphe et à la réponse attendue.
{history_instruction}
Réponds uniquement en JSON valide, sans Markdown. Garde la sortie courte :
{{
  "verdict": "partial",
  "feedback": "retour bref et utile",
  "completion": "élément à ajouter si partial, sinon chaîne vide",
  "hint": "indice si incorrect, sinon chaîne vide",
  "metacog_signals": {{
    "context_comprehension": 0.0,
    "creativity": 0.0,
    "attention": 0.0,
    "retention": 0.0,
    "curiosity": 1.0,
    "meta_cognition": 0.0
  }},
  "curiosity_signals": {{
    "asked_follow_up_question": false,
    "asked_for_clarification": false,
    "asked_for_example": false,
    "explored_beyond_required_answer": false
  }},
  "creativity_signals": {{
    "goes_beyond_prompt": false,
    "makes_connections": false,
    "uses_analogy": false,
    "personal_reformulation": false,
    "original_hypothesis": false,
    "depth_of_reflection": 0.0
  }},
  "answer_to_user_question": null,
  "flashcard": {_flashcard_example},
  "highlights": [{{"quote": "citation EXACTE copiée du paragraphe source (8 à 25 mots)", "purpose": "key"}}]
}}

Contraintes :
- Les signaux métacognitifs sont entre -2.0 et 2.0.
- highlights : 0 à 3 citations copiées MOT POUR MOT du paragraphe source (jamais reformulées), désignant les passages qui justifient le verdict ou corrigent l'erreur. purpose vaut "key" (passage clé), "explain" (passage que ton feedback explique) ou "reference" (passage cité en appui). Liste vide si rien de pertinent.
- verdict doit être exactement "correct", "partial" ou "incorrect".
- meta_cognition reste à 0.0 ici : elle sera évaluée uniquement dans le sas de fin de session.
- verdict vaut "correct" si l'idée attendue est présente, même si l'étudiant ajoute une réflexion personnelle, une réserve ou une question qui ne contredit pas le paragraphe.
- verdict vaut "partial" seulement si l'idée principale est présente mais trop imprécise ou incomplète.
- verdict vaut "incorrect" seulement si l'idée principale est absente, contredite ou hors sujet.
- hint doit être renseigné uniquement si verdict vaut "incorrect". Sinon hint doit être une chaîne vide.
- completion doit être renseigné uniquement si verdict vaut "partial". Sinon completion doit être une chaîne vide.
- Si verdict vaut "correct", feedback doit être une phrase courte et spécifique qui valide ce que l'étudiant a bien saisi — cite un élément précis de sa réponse ou du paragraphe. Ne jamais écrire simplement "Correct" ou "Bonne réponse" : ajoute toujours une nuance, un lien ou une remarque pédagogique utile.
- Si la réponse de l'étudiant contient une question de suivi, une demande de clarification, d'exemple ou d'approfondissement, augmente le signal curiosity et renseigne curiosity_signals.
- Ne réponds pas à cette question dans answer_to_user_question pendant l'évaluation : mets answer_to_user_question à null. La question de suivi sera traitée par le champ dédié "Poser une question sur ce paragraphe".
- Si la réponse dépasse le minimum attendu, fait des liens, reformule avec ses mots, propose une analogie ou une hypothèse, augmente le signal creativity et renseigne creativity_signals.
- Une image est jointe : c'est la page PDF complète lue (le texte en est l'extraction). Utilise-la pour confirmer les notations et rester fidèle à ce qui figure réellement sur la page.
{_dim_hint_fr}
{_flashcard_constraint}
- Ne donne pas directement la solution complète si verdict vaut incorrect."""


def build_follow_up_prompt(
    paragraph: str,
    user_question: str,
    metacog_profile: dict | None = None,
) -> str:
    if _i18n.current_lang() == "en":
        return f"""You are the adaptive learning companion of MetaC-App.

The student has asked a follow-up question about a paragraph they just read.

Metacognitive profile: {_json(metacog_profile or {})}

Source paragraph:
---
{paragraph[:3500]}
---

Student's question:
---
{user_question[:500]}
---

Respond in valid JSON, without Markdown:
{{
  "answer": "clear and pedagogical answer: first what the paragraph says, then a general explanation if useful",
  "metacog_signals": {{
    "context_comprehension": 0.0,
    "creativity": 0.0,
    "attention": 0.0,
    "retention": 0.0,
    "curiosity": 0.0,
    "meta_cognition": 0.0
  }},
  "curiosity_signals": {{
    "asked_follow_up_question": true,
    "asked_for_clarification": false,
    "asked_for_example": false,
    "explored_beyond_required_answer": false
  }},
  "highlights": [{{"quote": "EXACT quote copied from the paragraph (8 to 25 words)", "purpose": "explain"}}]
}}

Constraints:
- curiosity must be at least 1.0 because the student is asking a follow-up question.
- highlights: 0 to 3 quotes copied WORD FOR WORD from the source paragraph (never rephrased), pointing at the passages your answer relies on. purpose is "key", "explain" or "reference". Use an empty list if nothing relevant.
- Always answer the student's question when a useful answer is possible.
- If the paragraph does not provide enough information, supplement with your general knowledge.
- Structure your answer in two parts: (1) what the paragraph says on the subject, (2) what your general knowledge adds — even if the paragraph already addresses the question.
- The general knowledge supplement is MANDATORY whenever the student's question goes beyond the strict definition in the paragraph (examples, special cases, properties, counterexamples, applications…). Introduce it with "More generally, ..." or "In mathematics / in physics / in computer science, ...".
- Do not invent precise facts about the document if the paragraph does not provide them; distinguish the local source from the external explanation.
- Do not simply write "unable to answer": if the paragraph does not answer, use your knowledge to explain the concept.
- meta_cognition stays at 0.0."""

    return f"""Tu es le compagnon d'apprentissage adaptatif de MetaC-App.

L'étudiant a posé une question de suivi sur un paragraphe qu'il vient de lire.

Profil métacognitif : {_json(metacog_profile or {})}

Paragraphe source :
---
{paragraph[:3500]}
---

Question de l'étudiant :
---
{user_question[:500]}
---

Réponds en JSON valide, sans Markdown :
{{
  "answer": "réponse claire et pédagogique : d'abord ce que dit le paragraphe, puis une explication générale si utile",
  "metacog_signals": {{
    "context_comprehension": 0.0,
    "creativity": 0.0,
    "attention": 0.0,
    "retention": 0.0,
    "curiosity": 0.0,
    "meta_cognition": 0.0
  }},
  "curiosity_signals": {{
    "asked_follow_up_question": true,
    "asked_for_clarification": false,
    "asked_for_example": false,
    "explored_beyond_required_answer": false
  }},
  "highlights": [{{"quote": "citation EXACTE copiée du paragraphe (8 à 25 mots)", "purpose": "explain"}}]
}}

Contraintes :
- curiosity doit être au moins 1.0 car l'étudiant pose une question de suivi.
- highlights : 0 à 3 citations copiées MOT POUR MOT du paragraphe source (jamais reformulées), désignant les passages sur lesquels ta réponse s'appuie. purpose vaut "key", "explain" ou "reference". Liste vide si rien de pertinent.
- Réponds toujours à la question de l'étudiant quand une réponse utile est possible.
- Si le paragraphe ne donne pas assez d'éléments, complète avec tes connaissances générales.
- Structure ta réponse en deux temps : (1) ce que le paragraphe dit sur le sujet, (2) ce que tes connaissances générales apportent en complément — même si le paragraphe aborde déjà la question.
- Le complément de connaissances générales est OBLIGATOIRE dès que la question de l'étudiant dépasse la définition stricte du paragraphe (exemples, cas particuliers, propriétés, contre-exemples, applications…). Introduis-le avec "Plus généralement, ..." ou "En mathématiques / en physique / en informatique, ...".
- N'invente pas de fait précis sur le document si le paragraphe ne le donne pas ; distingue la source locale et l'explication externe.
- N'écris pas simplement "impossible de répondre" : si le paragraphe ne répond pas, utilise tes connaissances pour expliquer le concept.
- meta_cognition reste à 0.0."""


def build_rephrasing_prompt(paragraph: str, attempt_count: int) -> str:
    if _i18n.current_lang() == "en":
        return f"""You are rephrasing a course paragraph to unblock a student.

Number of consecutive incorrect attempts: {attempt_count}

Original paragraph:
---
{paragraph[:3500]}
---

Respond only in valid JSON, without Markdown, in the exact format:
{{
  "rephrasing_angle": "chosen angle",
  "rephrased_paragraph": "clear, faithful, and more accessible reformulation",
  "note": "brief sentence on what to look at differently",
  "highlights": [{{"quote": "EXACT quote copied from the original paragraph (8 to 25 words)", "purpose": "explain"}}]
}}

Constraints:
- highlights: 0 to 3 quotes copied WORD FOR WORD from the original paragraph (never rephrased), pointing at the passages your reformulation clarifies. Use an empty list if nothing relevant.
- Do not simplify to the point of changing the content.
- Keep important formulas and notation.
- An image is attached: it is the full PDF page being read (the text is its extraction): use it to preserve notation that OCR may have degraded."""

    return f"""Tu reformules un paragraphe de cours pour débloquer un étudiant.

Nombre de tentatives incorrectes consécutives : {attempt_count}

Paragraphe original :
---
{paragraph[:3500]}
---

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "rephrasing_angle": "angle choisi",
  "rephrased_paragraph": "reformulation claire, fidèle et plus accessible",
  "note": "phrase brève sur ce qu'il faut regarder autrement",
  "highlights": [{{"quote": "citation EXACTE copiée du paragraphe original (8 à 25 mots)", "purpose": "explain"}}]
}}

Contraintes :
- highlights : 0 à 3 citations copiées MOT POUR MOT du paragraphe original (jamais reformulées), désignant les passages que ta reformulation éclaire. Liste vide si rien de pertinent.
- Ne simplifie pas au point de changer le contenu.
- Garde les formules et notations importantes.
- Une image est jointe : c'est la page PDF complète lue (le texte en est l'extraction) : utilise-la pour préserver les notations que l'OCR aurait pu dégrader."""


def build_flashcard_prompt(front: str, back: str, paragraph: str = "") -> str:
    """Transforme un échange (question utilisateur + réponse de l'assistant) en
    flashcard de révision AUTONOME : le recto doit être compréhensible sans avoir
    lu le document (jamais « reformule ce paragraphe » ou « selon ce texte »)."""
    context_block_fr = f"\nParagraphe de référence :\n---\n{paragraph[:2000]}\n---\n" if paragraph else ""
    context_block_en = f"\nReference paragraph:\n---\n{paragraph[:2000]}\n---\n" if paragraph else ""

    if _i18n.current_lang() == "en":
        return f"""You turn a reading exchange into a STANDALONE review flashcard for MetaC-App.
{context_block_en}
Student's note / question (raw front):
---
{(front or "")[:600]}
---

Assistant's answer (raw back):
---
{(back or "")[:1200]}
---

Respond only in valid JSON, without Markdown:
{{
  "front": "standalone question understandable without the document",
  "back": "concise, self-contained answer",
  "tags": ["tag1", "tag2"],
  "difficulty": 2
}}

Constraints:
- front MUST be a standalone question: never "rephrase this paragraph", "summarize the text", "according to the passage". If the raw front references the document, replace that reference with the precise concept or data it concerns.
- back must be the concise answer to front, faithful to the assistant's answer; embed any needed context so the card stands on its own.
- If the exchange cannot become a meaningful self-contained card (purely conversational, no transferable knowledge), still produce the most useful factual card you can from the concept discussed.
- difficulty is 1, 2 or 3. Keep mathematical notation in valid LaTeX between $...$."""

    return f"""Tu transformes un échange de lecture en flashcard de révision AUTONOME pour MetaC-App.
{context_block_fr}
Note / question de l'étudiant (recto brut) :
---
{(front or "")[:600]}
---

Réponse de l'assistant (verso brut) :
---
{(back or "")[:1200]}
---

Réponds uniquement en JSON valide, sans Markdown :
{{
  "front": "question autonome compréhensible sans le document",
  "back": "réponse concise et autoportante",
  "tags": ["tag1", "tag2"],
  "difficulty": 2
}}

Contraintes :
- front DOIT être une question autonome : jamais « reformule ce paragraphe », « résume le texte », « selon le passage ». Si le recto brut fait référence au document, remplace cette référence par le concept ou la donnée précise concernée.
- back doit être la réponse concise à front, fidèle à la réponse de l'assistant ; intègre le contexte nécessaire pour que la carte se suffise à elle-même.
- Si l'échange ne peut pas devenir une carte autoportante pertinente (purement conversationnel, sans savoir transférable), produis quand même la carte factuelle la plus utile à partir du concept abordé.
- difficulty vaut 1, 2 ou 3. Garde les notations mathématiques en LaTeX valide entre $...$."""


def build_session_summary_prompt(
    session_data: dict,
    metacog_profile: dict | None = None,
    session_gauges: dict | None = None,
) -> str:
    profile = metacog_profile or {}
    gauges = session_gauges or {}

    is_en = _i18n.current_lang() == "en"

    gauge_labels = {
        "attention": _t("Attention", "Attention"),
        "context_comprehension": _t("Compréhension", "Comprehension"),
        "creativity": _t("Créativité", "Creativity"),
        "retention": _t("Rétention", "Retention"),
        "curiosity": _t("Curiosité", "Curiosity"),
        "meta_cognition": _t("Métacognition", "Metacognition"),
    }
    gauge_lines = []
    for key, label in gauge_labels.items():
        session_val = gauges.get(key)
        profile_val = profile.get(key)
        if session_val is not None and profile_val is not None:
            diff = float(session_val) - float(profile_val)
            if is_en:
                trend = (
                    f"+{diff:.1f} (exceeded)" if diff >= 8
                    else (f"{diff:.1f} (below baseline)" if diff <= -8 else f"{diff:+.1f} (stable)")
                )
            else:
                trend = (
                    f"+{diff:.1f} (surpassé)" if diff >= 8
                    else (f"{diff:.1f} (en retrait)" if diff <= -8 else f"{diff:+.1f} (stable)")
                )
            gauge_lines.append(
                f"  {label}: session={float(session_val):.1f} | "
                f"{_t('profil', 'profile')}={float(profile_val):.1f} | "
                f"{_t('écart', 'delta')}={trend}"
            )
        elif session_val is not None:
            gauge_lines.append(f"  {label}: session={float(session_val):.1f}")
    gauge_comparison = "\n".join(gauge_lines) if gauge_lines else f"  ({_t('non disponibles', 'not available')})"

    stats_only = {k: v for k, v in session_data.items() if k not in ("profile", "gauges", "session_score")}

    if is_en:
        return f"""You are producing the end-of-session debrief for MetaC-App.

Session statistics:
{_json(stats_only)}

Session gauges vs reference profile comparison (scale 0–100):
{gauge_comparison}

Reference metacognitive profile (historical averages):
{_json(profile)}

Respond only in valid JSON, without Markdown, in the exact format:
{{
  "session_summary": {{
    "duration_s": 0,
    "paragraphs_read": 0,
    "flashcards_created": 0,
    "rephrasings_count": 0,
    "success_rate": 0.0,
    "qualitative_summary": "...",
    "metacognitive_questions": [
      "question 1",
      "question 2",
      "question 3"
    ]
  }}
}}

Constraints:
- success_rate is between 0.0 and 1.0.
- qualitative_summary: 2 to 3 sentences in English. Mention at least one positive point, one area for improvement, and one concrete suggestion. If a gauge exceeds its profile by ≥8 pts, explicitly note this (e.g., "your attention was noticeably above your usual level"). If a gauge is below by ≥8 pts, note that too. Be precise and personalized.
- Provide exactly 3 short, clear, and distinct metacognitive questions, adapted to the session data and gauges."""

    return f"""Tu produis le sas de sortie d'une session MetaC-App.

Statistiques de session :
{_json(stats_only)}

Comparaison jauges session vs profil de référence (échelle 0–100) :
{gauge_comparison}

Profil métacognitif de référence (moyennes historiques) :
{_json(profile)}

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "session_summary": {{
    "duration_s": 0,
    "paragraphs_read": 0,
    "flashcards_created": 0,
    "rephrasings_count": 0,
    "success_rate": 0.0,
    "qualitative_summary": "...",
    "metacognitive_questions": [
      "question 1",
      "question 2",
      "question 3"
    ]
  }}
}}

Contraintes :
- success_rate est entre 0.0 et 1.0.
- qualitative_summary : 2 à 3 phrases en français. Mentionne au moins un point positif, un point d'amélioration, et une suggestion concrète. Si une jauge dépasse de ≥8 pts son profil, signale explicitement ce surpassement (ex : "ton attention était nettement au-dessus de ton niveau habituel"). Si une jauge est en retrait de ≥8 pts, signale-le aussi. Sois précis et personnalisé.
- Fournis exactement 3 questions métacognitives courtes, claires et différentes, adaptées aux données et aux jauges de la session."""


def build_meta_cognition_questions_prompt(
    session_summary: dict | None = None,
    recent_user_answers: list[dict] | list[str] | None = None,
    previous_end_questions: list[str] | None = None,
    user_profile: dict | None = None,
) -> str:
    if _i18n.current_lang() == "en":
        return f"""You are generating metacognitive questions for the end of a learning session.

Session summary:
{_json(session_summary or {})}

Recent user answers:
{_json(recent_user_answers or [])}

Questions already asked recently:
{_json(previous_end_questions or [])}

User profile:
{_json(user_profile or {})}

Respond only in valid JSON, without Markdown, in the exact format:
{{
  "questions": ["question 1", "question 2", "question 3"]
}}

Constraints:
- You must produce exactly 3 questions.
- They must help the user reflect on their comprehension, blocks, strategies, and self-assessment.
- The questions must be short, clear, context-adapted, and different from each other.
- Avoid repeating questions that have already been asked if possible.
- Do not ask any question outside the metacognition framework."""

    return f"""Tu génères des questions de méta-cognition pour la fin d'une session d'apprentissage.

Résumé de session :
{_json(session_summary or {})}

Réponses récentes de l'utilisateur :
{_json(recent_user_answers or [])}

Questions déjà posées récemment :
{_json(previous_end_questions or [])}

Profil utilisateur :
{_json(user_profile or {})}

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "questions": ["question 1", "question 2", "question 3"]
}}

Contraintes :
- Tu dois produire exactement 3 questions.
- Elles doivent aider l'utilisateur à réfléchir à sa compréhension, ses blocages, ses stratégies et son auto-évaluation.
- Les questions doivent être courtes, claires, adaptées au contexte et différentes entre elles.
- Évite de reprendre exactement les questions déjà posées si possible.
- Ne pose aucune question hors du cadre de la méta-cognition."""


def build_meta_cognition_analysis_prompt(
    questions: list[str],
    answers: list[str],
    session_context: dict | None = None,
    user_profile: dict | None = None,
) -> str:
    if _i18n.current_lang() == "en":
        return f"""You are analyzing a user's answers to metacognitive questions.

Questions:
{_json(questions)}

User's answers:
{_json(answers)}

Session context:
{_json(session_context or {})}

User profile:
{_json(user_profile or {})}

Evaluate whether the user accurately identifies their difficulties, strategies, comprehension level, and feelings.
Increase the score if the answers are concrete, honest, reflective, and useful.
Decrease the score if the answers are vague, absent, superficial, or off-topic.

Respond only in valid JSON, without Markdown, in the exact format:
{{
  "score_delta": 0.0,
  "score": 50.0,
  "reasoning": "brief reasoning",
  "detected_signals": {{
    "awareness_of_difficulties": 0.0,
    "strategy_identification": 0.0,
    "self_evaluation": 0.0,
    "specificity": 0.0,
    "honesty_or_depth": 0.0
  }}
}}

Constraints:
- score_delta is generally between -12 and +12.
- score and all signals are bounded between 0.0 and 100.0 for score, 0.0 and 1.0 for signals.
- Return a negative score_delta if the answers are absent or too vague."""

    return f"""Tu analyses les réponses de l'utilisateur à des questions de méta-cognition.

Questions :
{_json(questions)}

Réponses de l'utilisateur :
{_json(answers)}

Contexte de session :
{_json(session_context or {})}

Profil utilisateur :
{_json(user_profile or {})}

Évalue si l'utilisateur identifie ses difficultés, ses stratégies, son niveau de compréhension et son ressenti avec précision.
Augmente le score si les réponses sont concrètes, honnêtes, réflexives et utiles.
Diminue le score si les réponses sont vagues, absentes, superficielles ou hors sujet.

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "score_delta": 0.0,
  "score": 50.0,
  "reasoning": "raisonnement bref",
  "detected_signals": {{
    "awareness_of_difficulties": 0.0,
    "strategy_identification": 0.0,
    "self_evaluation": 0.0,
    "specificity": 0.0,
    "honesty_or_depth": 0.0
  }}
}}

Contraintes :
- score_delta est généralement entre -12 et +12.
- score et tous les signaux sont bornés entre 0.0 et 100.0 pour score, 0.0 et 1.0 pour les signaux.
- Retourne score_delta négatif si les réponses sont absentes ou trop vagues."""


def build_profile_analysis_prompt(
    profile: dict | None = None,
    session_metrics: dict | None = None,
    session_gauges: dict | None = None,
    reflections: list[dict] | None = None,
    previous_analysis: str = "",
) -> str:
    """Analyse générale (évolutive) de l'apprenant, affichée sur la page profil.

    Synthétise le profil métacognitif long terme, la session qui vient de s'achever
    (métriques + jauges) et les réponses de réflexion, en tenant compte de l'analyse
    précédente pour faire évoluer le portrait plutôt que repartir de zéro."""
    if _i18n.current_lang() == "en":
        return f"""You are the metacognitive coach of MetaC-App, keeping an evolving portrait of the learner.

Long-term metacognitive profile (0–100 per criterion):
{_json(profile or {})}

Session that just ended (statistics):
{_json(session_metrics or {})}

Session gauges (0–100):
{_json(session_gauges or {})}

Learner's reflection answers:
{_json(reflections or [])}

Previous general analysis (may be empty):
{previous_analysis or "(none)"}

Update the GENERAL analysis of the learner: evolve the previous portrait with what this
session and these reflections reveal — do not restart from scratch.

Respond only in valid JSON, without Markdown, in the exact format:
{{"analysis": "..."}}

Constraints:
- analysis: 3 to 5 sentences in English, addressed to the learner ("you").
- Cover strengths, recurring difficulties, and trends across criteria; give one concrete suggestion.
- Be factual and personalized; never invent data absent from the inputs."""

    return f"""Tu es le coach métacognitif de MetaC-App ; tu tiens un portrait évolutif de l'apprenant.

Profil métacognitif long terme (0–100 par critère) :
{_json(profile or {})}

Session qui vient de s'achever (statistiques) :
{_json(session_metrics or {})}

Jauges de la session (0–100) :
{_json(session_gauges or {})}

Réponses de réflexion de l'apprenant :
{_json(reflections or [])}

Analyse générale précédente (peut être vide) :
{previous_analysis or "(aucune)"}

Mets à jour l'analyse GÉNÉRALE de l'apprenant : fais évoluer le portrait précédent avec ce
que cette session et ces réflexions révèlent — ne repars pas de zéro.

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{"analysis": "..."}}

Contraintes :
- analysis : 3 à 5 phrases en français, adressées à l'apprenant (« tu »).
- Couvre les forces, les difficultés récurrentes et les tendances par critère ; donne une suggestion concrète.
- Reste factuel et personnalisé ; n'invente jamais de données absentes des entrées."""


def build_flashcard_tags_prompt(
    front: str,
    back: str,
    session_context: dict | None = None,
    existing_sections: list[str] | None = None,
    existing_tags: list[str] | None = None,
) -> str:
    if _i18n.current_lang() == "en":
        return f"""You are generating tags to classify a flashcard.

Front:
---
{(front or "")[:1200]}
---

Back:
---
{(back or "")[:1200]}
---

Available context:
{_json(session_context or {})}

Existing sections:
{_json(existing_sections or [])}

Existing tags:
{_json(existing_tags or [])}

Respond only in valid JSON, without Markdown, in the exact format:
{{
  "tags": ["tag 1", "tag 2"]
}}

Constraints:
- Generate between 2 and 6 short, relevant, duplicate-free tags in English.
- Normalize tags in lowercase.
- Avoid vague tags like "course", "important", or "misc".
- Reuse existing tags or sections when they match the content.
- Do not invent unnecessary categories if an existing tag fits."""

    return f"""Tu génères des tags pour classer une flashcard.

Recto :
---
{(front or "")[:1200]}
---

Verso :
---
{(back or "")[:1200]}
---

Contexte disponible :
{_json(session_context or {})}

Sections existantes :
{_json(existing_sections or [])}

Tags existants :
{_json(existing_tags or [])}

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "tags": ["tag 1", "tag 2"]
}}

Contraintes :
- Génère entre 2 et 6 tags courts, pertinents, sans doublons, en français.
- Normalise les tags en minuscules.
- Évite les tags vagues comme "cours", "important" ou "divers".
- Réutilise les tags ou sections existants lorsqu'ils correspondent au contenu.
- N'invente pas de catégories inutiles si un tag existant convient."""


def build_chapter_summary_prompt(
    chapter_title: str,
    paragraphs_summary: list[dict] | list[str],
    metacog_profile: dict | None = None,
) -> str:
    _na = _t("non renseigné", "not specified")

    if _i18n.current_lang() == "en":
        return f"""You are producing an end-of-chapter summary for MetaC-App.

Chapter: {chapter_title or _na}
Current metacognitive profile (use only to adapt the pedagogical level, never as chapter content):
{_json(metacog_profile or {})}

Elements read in the chapter:
{_json(paragraphs_summary)}

Respond only in valid JSON, without Markdown, in the exact format:
{{
  "chapter_summary": {{
    "title": "chapter title",
    "overview": "short summary in English",
    "recap_qa": [
      {{
        "question": "recap question 1",
        "answer": "concise answer"
      }},
      {{
        "question": "recap question 2",
        "answer": "concise answer"
      }},
      {{
        "question": "recap question 3",
        "answer": "concise answer"
      }}
    ]
  }}
}}

Constraints:
- Give exactly 3 recap Q&As.
- Stay faithful to the elements read in the chapter.
- Never turn the metacognitive profile into course content.
- Formulate answers to help the student verify their understanding."""

    return f"""Tu produis une synthèse de fin de chapitre pour MetaC-App.

Chapitre : {chapter_title or _na}
Profil métacognitif courant (à utiliser seulement pour adapter le niveau pédagogique, jamais comme contenu du chapitre) :
{_json(metacog_profile or {})}

Éléments lus dans le chapitre :
{_json(paragraphs_summary)}

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "chapter_summary": {{
    "title": "titre du chapitre",
    "overview": "synthèse courte en français",
    "recap_qa": [
      {{
        "question": "question récapitulative 1",
        "answer": "réponse concise"
      }},
      {{
        "question": "question récapitulative 2",
        "answer": "réponse concise"
      }},
      {{
        "question": "question récapitulative 3",
        "answer": "réponse concise"
      }}
    ]
  }}
}}

Contraintes :
- Donne exactement 3 Q&R récapitulatives.
- Reste fidèle aux éléments lus dans le chapitre.
- Ne transforme jamais le profil métacognitif en sujet de cours.
- Formule les réponses pour aider l'étudiant à vérifier sa compréhension."""


def build_curiosity_hook_prompt(
    doc_title: str,
    chapter_title: str,
    subchapter_title: str,
    chapter_excerpt: str,
    profile: dict | None = None,
) -> str:
    _na = _t("non renseigné", "not specified")
    no_excerpt = not (chapter_excerpt or "").strip()

    if _i18n.current_lang() == "en":
        excerpt_section = (
            "No excerpt available: base yourself only on the document and chapter title."
            if no_excerpt
            else chapter_excerpt[:2500]
        )
        return f"""You are generating an opening hook for a reader about to read a chapter.

Context:
- Document: {doc_title or _na}
- Chapter: {chapter_title or _na}
- Sub-chapter: {subchapter_title or _na}
- Metacognitive profile: {_json(profile or {})}

Chapter excerpt:
---
{excerpt_section}
---

Write a single opening hook sentence in English, calm and concrete, that makes the reader want to enter this chapter.
The sentence must speak about the document content, not about the reading tool.
Respond only in valid JSON, without Markdown, in the exact format:
{{
  "curiosity_hook": "opening hook sentence",
  "tone": "calm | intriguing | concrete | playful",
  "link_with_chapter": "explicit link with the chapter",
  "estimated_accessibility": 0.0
}}

Constraints:
- curiosity_hook is a single short sentence.
- tone is exactly "calm", "intriguing", "concrete", or "playful".
- estimated_accessibility is between 0.0 and 1.0.
- Never mention the name of the application or the tool."""

    excerpt_section = (
        "Aucun extrait disponible : base-toi uniquement sur le titre du document et du chapitre."
        if no_excerpt
        else chapter_excerpt[:2500]
    )
    return f"""Tu génères une phrase d'accroche pour un lecteur qui s'apprête à lire un chapitre.

Contexte :
- Document : {doc_title or _na}
- Chapitre : {chapter_title or _na}
- Sous-chapitre : {subchapter_title or _na}
- Profil métacognitif : {_json(profile or {})}

Extrait du chapitre :
---
{excerpt_section}
---

Écris une seule phrase d'accroche en français, calme et concrète, qui donne envie d'entrer dans ce chapitre.
La phrase doit parler du contenu du document, pas de l'outil de lecture.
Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "curiosity_hook": "phrase d'accroche",
  "tone": "calm | intriguing | concrete | playful",
  "link_with_chapter": "lien explicite avec le chapitre",
  "estimated_accessibility": 0.0
}}

Contraintes :
- curiosity_hook tient en une phrase courte.
- tone vaut exactement "calm", "intriguing", "concrete" ou "playful".
- estimated_accessibility est entre 0.0 et 1.0.
- Ne mentionne jamais le nom de l'application ou de l'outil."""


def build_latex_paragraph_render_prompt(paragraph_text: str) -> str:
    return f"""Tu es un expert en mise en forme de contenu mathématique extrait de PDFs.

Le texte ci-dessous provient d'un OCR sur un document scientifique. Il peut contenir :
- des formules LaTeX mal extraites (symboles collés, délimiteurs manquants, commandes tronquées)
- du texte prosodique mêlé aux formules
- des artefacts d'extraction

Texte brut extrait :
---
{paragraph_text[:2800]}
---

Ta tâche : produire une version propre et fidèle de ce paragraphe, lisible par un étudiant.

Règles :
- Préserve le sens exact : ne simplifie, ne résume, n'ajoute rien.
- Encadre chaque expression mathématique inline avec $...$ et chaque formule display avec $$...$$.
- N'écris jamais de commande LaTeX brute hors de ces délimiteurs : pas de \\theta, \\cdot, _, ^ ou accolades mathématiques dans le texte courant.
- Préserve les indices, exposants, lettres grecques et noms de variables : ne transforme pas $D_{{meta}}$ en Dmeta, ni $\\hat{{z}}_{{i,j}}$ en z i,j.
- Utilise du LaTeX valide à l'intérieur des délimiteurs.
- Double les backslashes dans le JSON : \\\\frac, \\\\sum, \\\\alpha, etc.
- Le texte non-mathématique reste en français simple, sans Markdown.
- Si une image est jointe, utilise-la pour corriger les notations ambiguës.

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "rendered": "texte nettoyé avec $formules$ correctement délimitées"
}}"""


def build_latex_contextual_chunk_render_prompt(
    target_text: str,
    previous_context: str = "",
    next_context: str = "",
) -> str:
    context = _format_chunk_context(previous_context, next_context)
    return f"""Tu es un expert en mise en forme de contenu mathématique extrait de PDFs.

Le texte cible ci-dessous est un fragment d'une section plus longue. Un contexte voisin peut être fourni uniquement pour comprendre les notations.
{context}

Texte cible à corriger :
---
{target_text[:2200]}
---

Ta tâche : produire une version propre et fidèle du texte cible uniquement.

Règles :
- Ne réécris pas le contexte voisin dans la réponse.
- Préserve le sens exact : ne simplifie, ne résume, n'ajoute rien.
- Encadre chaque expression mathématique inline avec $...$ et chaque formule display avec $$...$$.
- N'écris jamais de commande LaTeX brute hors de ces délimiteurs.
- Préserve les indices, exposants, lettres grecques et noms de variables.
- Utilise du LaTeX valide à l'intérieur des délimiteurs.
- Double les backslashes dans le JSON : \\\\frac, \\\\sum, \\\\alpha, etc.
- Si une image est jointe, utilise-la pour corriger les notations ambiguës.

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "rendered": "texte cible nettoyé avec $formules$ correctement délimitées"
}}"""


def build_latex_paragraph_render_text_prompt(paragraph_text: str) -> str:
    return f"""Tu es un expert en mise en forme de contenu mathématique extrait de PDFs.

Le texte ci-dessous provient d'un OCR sur un document scientifique. Il peut contenir :
- des formules LaTeX mal extraites (symboles collés, délimiteurs manquants, commandes tronquées)
- du texte prosodique mêlé aux formules
- des artefacts d'extraction

Texte brut extrait :
---
{paragraph_text[:2800]}
---

Ta tâche : produire une version propre et fidèle de ce paragraphe, lisible par un étudiant.

Règles :
- Préserve le sens exact : ne simplifie, ne résume, n'ajoute rien.
- Encadre chaque expression mathématique inline avec $...$ et chaque formule display avec $$...$$.
- N'écris jamais de commande LaTeX brute hors de ces délimiteurs : pas de \\theta, \\cdot, _, ^ ou accolades mathématiques dans le texte courant.
- Préserve les indices, exposants, lettres grecques et noms de variables : ne transforme pas $D_{{meta}}$ en Dmeta, ni $\\hat{{z}}_{{i,j}}$ en z i,j.
- Utilise du LaTeX valide à l'intérieur des délimiteurs.
- Le texte non-mathématique reste en français simple, sans Markdown.
- Si une image est jointe, utilise-la pour corriger les notations ambiguës.

Réponds uniquement avec le paragraphe corrigé en texte brut.
N'utilise pas JSON, pas Markdown, pas bloc de code, pas commentaire avant ou après."""


def _format_chunk_context(previous_context: str, next_context: str) -> str:
    parts: list[str] = []
    if previous_context.strip():
        parts.append(f"Contexte précédent, à ne pas réécrire :\n---\n{previous_context[-700:]}\n---")
    if next_context.strip():
        parts.append(f"Contexte suivant, à ne pas réécrire :\n---\n{next_context[:500]}\n---")
    if not parts:
        return ""
    return "\n" + "\n\n".join(parts)


# Liste canonique des matières attribuables à un document (miroir de
# db.subjects.SUBJECT_LABELS et llm.schema_json._KNOWN_SUBJECTS).
SUBJECT_KEYS = (
    "mathématiques, physique, chimie, biologie, sciences, informatique, "
    "technologie, histoire, géographie, français, philosophie, littérature, "
    "langues, économie, sciences-sociales, droit, gestion, psychologie, "
    "sociologie, arts, musique, médecine, sport, religion, culture"
)


def build_document_digest_prompt(doc_title: str, excerpt: str) -> str:
    """Fiche d'un document à l'import : matière + résumé + mots-clés en un appel.

    Le résumé est du texte VISIBLE par l'utilisateur : contrairement à l'ancienne
    détection de matière (une simple clé), ce prompt doit suivre la langue de
    l'interface.
    """
    subjects = SUBJECT_KEYS
    safe_excerpt = (excerpt or "").strip()[:DOCUMENT_DIGEST_PROMPT_CHARS]
    if _i18n.current_lang() == "en":
        return f"""You are indexing a study document for a personal library.

Document title: {doc_title or "unknown"}

Beginning of the document:
---
{safe_excerpt or "Not available."}
---

Produce a card that lets someone find this document again without remembering
its filename.

Respond only in valid JSON, without Markdown, without any comment, in exactly
this format:
{{"subject": "<subject>", "summary": "<one sentence>", "keywords": ["<keyword>", "<keyword>"]}}

Constraints:
- "subject" MUST be exactly one of: {subjects}
  Pick the most SPECIFIC one. If unsure, pick "culture".
- "summary": ONE sentence of 12 to 30 words, 200 characters maximum, saying what
  the document CONTAINS (topic and scope). Plain descriptive English.
  Start directly with the subject matter, like this example:
  "Photosynthesis in green plants, from the light phase to the Calvin cycle."
  Do not judge; do not invent.
- "keywords": 3 to 6 topics or notions actually covered, lowercase, 1 to 3 words
  each, no duplicates. Banned vague words: "course", "chapter", "introduction",
  "document", "notes".
- Nothing outside the JSON."""

    return f"""Tu indexes un document d'étude pour une bibliothèque personnelle.

Titre du document : {doc_title or "inconnu"}

Début du document :
---
{safe_excerpt or "Non disponible."}
---

Produis une fiche qui permette de RETROUVER ce document sans se souvenir de son
nom de fichier.

Réponds uniquement en JSON valide, sans Markdown, sans commentaire, exactement
dans ce format :
{{"subject": "<matière>", "summary": "<une phrase>", "keywords": ["<mot-clé>", "<mot-clé>"]}}

Contraintes :
- "subject" DOIT être exactement l'une de : {subjects}
  Choisis la plus SPÉCIFIQUE (par ex. "physique" plutôt que "sciences").
  Si tu hésites, choisis "culture".
- "summary" : UNE phrase de 12 à 30 mots, 200 caractères maximum, qui dit ce que
  le document CONTIENT (sujet et portée). Français simple et descriptif.
  Commence directement par le sujet traité, comme dans cet exemple :
  « La photosynthèse chez les plantes vertes, de la phase claire au cycle de Calvin. »
  Ne juge pas ; n'invente rien.
- "keywords" : 3 à 6 thèmes ou notions réellement traités, en minuscules, 1 à 3
  mots chacun, sans doublon. Mots vagues interdits : « cours », « chapitre »,
  « introduction », « document », « notes ».
- Ne mets rien en dehors du JSON."""


def build_quiz_session_analysis_prompt(
    answers_history: list[dict],
    subject_profiles: list[dict] | None = None,
) -> str:
    if _i18n.current_lang() == "en":
        return f"""You are the adaptive learning companion of MetaC-App.
The student has just completed a quiz session.

Answer history (each entry contains: question, user_answer, verdict, score [0.0=incorrect, 0.5=partial, 1.0=correct], category, source, document, chapter_title):
{_json(answers_history)}

Current mastery levels by subject:
{_json(subject_profiles or [])}

Analyze the performance, identify gaps, and recommend specific courses to review.
To recommend a course: use each answer's score to group questions by document/chapter (fields document and chapter_title). Prioritize recommending courses (document + chapter) where the average score is lowest.

Respond only in valid JSON, without Markdown, in the exact format:
{{
  "analysis": "supportive pedagogical summary in 2-3 sentences, factual and direct",
  "weak_subjects": ["subject 1", "subject 2"],
  "courses_to_review": [
    {{
      "title": "title of the course or chapter to review (= document if available, otherwise subject)",
      "subject": "subject key, one of: {SUBJECT_KEYS}",
      "reason": "short pedagogical reason based on scores (one sentence)",
      "document": "value of the document field if source=reading, otherwise empty string",
      "chapter_title": "value of the chapter_title field if source=reading, otherwise empty string"
    }}
  ]
}}

Constraints:
- courses_to_review contains between 0 and 3 elements, sorted by ascending average score (lowest first).
- If all answers have score=1.0, courses_to_review must be [].
- Each reason cites the score or number of errors found for this course/chapter.
- Stay factual: base yourself only on the provided history.
- If source=reading and document is not null, use that document as title and set document and chapter_title.
- If source=static, leave document and chapter_title as empty strings."""

    return f"""Tu es le compagnon d'apprentissage adaptatif de MetaC-App.
L'étudiant vient de terminer une session de quiz.

Historique des réponses (chaque entrée contient : question, user_answer, verdict, score [0.0=incorrect, 0.5=partiel, 1.0=correct], category, source, document, chapter_title) :
{_json(answers_history)}

Niveaux de maîtrise actuels par matière :
{_json(subject_profiles or [])}

Analyse les performances, identifie les lacunes et recommande des cours spécifiques à réviser.
Pour recommander un cours : utilise le score de chaque réponse pour regrouper les questions par document/chapitre (champs document et chapter_title). Recommande en priorité les cours (document + chapitre) où le score moyen est le plus faible.

Réponds uniquement en JSON valide, sans Markdown, au format exact :
{{
  "analysis": "synthèse pédagogique bienveillante en 2-3 phrases, factuelle et directe",
  "weak_subjects": ["sujet 1", "sujet 2"],
  "courses_to_review": [
    {{
      "title": "titre du cours ou chapitre à réviser (= document si disponible, sinon matière)",
      "subject": "clé de matière, l'une de : {SUBJECT_KEYS}",
      "reason": "raison courte et pédagogique basée sur les scores (une phrase)",
      "document": "valeur du champ document si source=reading, sinon chaîne vide",
      "chapter_title": "valeur du champ chapter_title si source=reading, sinon chaîne vide"
    }}
  ]
}}

Contraintes :
- courses_to_review contient entre 0 et 3 éléments, triés par score moyen croissant (le plus faible en premier).
- Si toutes les réponses ont score=1.0, courses_to_review doit être [].
- Chaque reason cite le score ou le nombre d'erreurs constatés pour ce cours/chapitre.
- Reste factuel : base-toi uniquement sur l'historique fourni.
- Si source=reading et document non null, utilise ce document comme title et renseigne document et chapter_title.
- Si source=static, laisse document et chapter_title comme chaînes vides."""


def build_quiz_distractors_prompt(items: list[dict]) -> str:
    """Génère, en un seul appel, 3 distracteurs par question pour des QCM.

    ``items`` : liste de ``{"id", "question", "answer", "context"}``. Si ``answer``
    est vide (question de lecture ouverte sans réponse stockée), le LLM déduit
    d'abord la bonne réponse concise depuis ``context``, puis crée les distracteurs.
    """
    if _i18n.current_lang() == "en":
        return f"""You build multiple-choice quiz questions for a learning app.
For EACH question below, you must produce the correct answer and exactly 3
plausible but INCORRECT alternatives (distractors).

Questions (each: id, question, answer [may be empty], context):
{_json(items)}

Rules:
- If "answer" is provided, keep it as the correct answer (you may shorten it to a
  concise option). If "answer" is empty, determine the correct concise answer from
  "context".
- Each "answer" and each distractor must be a SHORT option (a few words / one short
  sentence), suitable for a multiple-choice button.
- The 3 distractors must be clearly wrong but credible: same topic, same kind/format
  as the answer, no obviously absurd options, all different from the answer and from
  each other.
- Stay grounded in the question and its context; do not invent unrelated facts.
- Format EVERY mathematical expression as inline LaTeX delimited by $...$ — both in
  the "answer" and in the distractors. Examples: $\\beta$, $y^T(I - X\\beta)y$,
  $\\lVert y - X\\beta \\rVert^2$, $\\frac{{1}}{{n}}\\sum x_i$. Leave plain (non-math)
  text without delimiters.

Respond ONLY with valid JSON, no Markdown, in the exact format:
{{
  "items": [
    {{"id": 1, "answer": "the correct concise answer", "distractors": ["wrong 1", "wrong 2", "wrong 3"]}}
  ]
}}
Return one entry per question, keeping the same "id". Nothing outside the JSON."""

    return f"""Tu construis des questions à choix multiples (QCM) pour une app d'apprentissage.
Pour CHAQUE question ci-dessous, tu dois produire la bonne réponse et exactement 3
alternatives plausibles mais FAUSSES (distracteurs).

Questions (chacune : id, question, answer [peut être vide], context) :
{_json(items)}

Règles :
- Si "answer" est fourni, garde-le comme bonne réponse (tu peux le raccourcir en une
  option concise). Si "answer" est vide, détermine la bonne réponse concise à partir
  de "context".
- Chaque "answer" et chaque distracteur doit être une option COURTE (quelques mots /
  une phrase courte), adaptée à un bouton de QCM.
- Les 3 distracteurs doivent être clairement faux mais crédibles : même thème, même
  nature/format que la réponse, aucune option absurde, tous différents de la réponse
  et entre eux.
- Reste ancré dans la question et son contexte ; n'invente pas de faits hors-sujet.
- Formate TOUTE expression mathématique en LaTeX inline délimité par $...$ — aussi bien
  dans "answer" que dans les distracteurs. Exemples : $\\beta$, $y^T(I - X\\beta)y$,
  $\\lVert y - X\\beta \\rVert^2$, $\\frac{{1}}{{n}}\\sum x_i$. Laisse le texte non
  mathématique sans délimiteurs.

Réponds UNIQUEMENT en JSON valide, sans Markdown, au format exact :
{{
  "items": [
    {{"id": 1, "answer": "la bonne réponse concise", "distractors": ["faux 1", "faux 2", "faux 3"]}}
  ]
}}
Renvoie une entrée par question en conservant le même "id". Rien en dehors du JSON."""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


# ── Module langue ─────────────────────────────────────────────────────────────

def build_lang_curriculum_prompt(language: str) -> str:
    return f"""Tu es un expert en didactique des langues étrangères appliquant la méthode Assimil.

Génère un programme de 100 leçons progressives pour apprendre le {language} depuis le niveau A0.
Leçons 1-49 : phase passive (absorption naturelle, dialogues simples).
Leçons 50-100 : phase active (production, retour sur les leçons 1-49 enrichi).

Réponds UNIQUEMENT en JSON valide, sans markdown, sans commentaires :
{{
  "lessons": [
    {{
      "lesson_n": 1,
      "theme": "thème de la leçon",
      "grammar_point": "point grammatical principal",
      "vocabulary": ["mot1", "mot2", "mot3"],
      "level": "A1",
      "reuses": []
    }}
  ]
}}

Contraintes strictes :
- Exactement 100 entrées dans "lessons", lesson_n de 1 à 100.
- vocabulary contient entre 5 et 10 mots-clés par leçon.
- reuses est une liste de numéros de leçons précédentes réutilisées (vide pour les 5 premières leçons).
- level suit le CECR : A1 (leçons 1-20), A2 (21-50), B1 (51-80), B2 (81-100).
- Les thèmes progressent de façon réaliste : salutations → famille → travail → société → débat."""


def build_lang_curiosity_prompt(
    language: str, lesson_n: int, theme: str, grammar_point: str
) -> str:
    return f"""Tu génères une phrase d'accroche pour un apprenant qui s'apprête à commencer \
la leçon {lesson_n} de {language}.

Thème de la leçon : {theme}
Point grammatical : {grammar_point or "non spécifié"}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "curiosity_hook": "une seule phrase courte et motivante en français",
  "cultural_note": "anecdote culturelle factuelle courte sur la langue ou le thème",
  "tone": "calm"
}}

Contraintes :
- curiosity_hook : une seule phrase max 120 caractères, parle du contenu culturel ou linguistique.
- cultural_note : anecdote factuelle max 200 caractères.
- tone vaut exactement "calm", "intriguing", "concrete" ou "playful"."""


def build_lang_lesson_prompt(
    language: str, lesson_n: int, curriculum_row: dict
) -> str:
    vocab_list = ", ".join(curriculum_row.get("vocabulary", []))
    return f"""Tu es un auteur de méthode Assimil.
Génère le contenu complet de la leçon {lesson_n} pour apprendre le {language}.

Thème : {curriculum_row.get("theme", "")}
Point grammatical : {curriculum_row.get("grammar_point", "")}
Vocabulaire cible : {vocab_list}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "dialogue": [
    {{
      "speaker": "A",
      "target": "phrase en {language}",
      "phonetic": "transcription phonétique si utile, sinon chaîne vide",
      "translation": "traduction en français"
    }}
  ],
  "notes": {{
    "grammar": "explication courte du point grammatical (max 300 caractères)",
    "pronunciation": "conseil de prononciation clé (max 200 caractères)",
    "cultural": "note culturelle brève (max 200 caractères)"
  }},
  "vocabulary": [
    {{
      "word": "mot en {language}",
      "translation": "traduction en français",
      "example": "exemple d'utilisation"
    }}
  ]
}}

Contraintes :
- dialogue : entre 6 et 12 échanges alternant locuteurs A et B.
- vocabulary : exactement les mots de la liste cible, ni plus ni moins.
- Toutes les valeurs "translation" sont en français.
- Pour les leçons 1-20 (débutant A1), les phrases cibles sont très courtes (3-6 mots)."""


def build_lang_exercises_prompt(
    language: str,
    lesson_n: int,
    dialogue: list[dict],
    vocabulary: list[dict],
) -> str:
    dialogue_text = "\n".join(
        f"{line['speaker']}: {line['target']} / {line['translation']}"
        for line in dialogue[:8]
    )
    vocab_text = ", ".join(
        f"{v['word']} ({v['translation']})" for v in vocabulary[:8]
    )
    return f"""Tu crées des exercices de compréhension pour la leçon {lesson_n} de {language}.

Dialogue :
{dialogue_text}

Vocabulaire : {vocab_text}

Génère exactement 3 QCM en JSON valide, sans markdown :
{{
  "exercises": [
    {{
      "type": "qcm",
      "question": "question en français sur le dialogue",
      "choices": ["A: réponse A", "B: réponse B", "C: réponse C"],
      "correct": "A",
      "explanation": "explication courte"
    }}
  ]
}}

Contraintes :
- Exactement 3 exercices.
- Les questions portent sur le sens du dialogue ou le vocabulaire.
- Les mauvaises réponses sont plausibles mais clairement incorrectes.
- correct vaut exactement "A", "B" ou "C"."""


def build_lang_correction_prompt(
    language: str, target_phrase: str, user_attempt: str
) -> str:
    return f"""Tu corriges la production en {language} d'un apprenant.

Phrase attendue : {target_phrase}
Tentative de l'apprenant : {user_attempt}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "verdict": "correct",
  "corrections": [
    {{"original": "mot erroné", "corrected": "mot correct", "error_type": "accord", "reason": "explication courte"}}
  ],
  "feedback": "encouragement court et constructif",
  "score": 0.8
}}

Contraintes :
- verdict vaut "correct", "partial" ou "incorrect".
- corrections est vide si verdict vaut "correct".
- score est entre 0.0 et 1.0.
- Pointer UNE seule erreur prioritaire si plusieurs.
- "error_type" NOMME le type de faute parmi : "genre", "accord", "conjugaison", \
"ordre des mots", "préposition", "faux-ami", "orthographe", "registre", "vocabulaire". \
"reason" reste une phrase max, sans jargon grammatical lourd."""


def build_lang_revision_quiz_prompt(
    language: str, errors: list[dict], due_cards: list[dict] | None = None
) -> str:
    """Quiz de révision à DEUX sources : erreurs passées + cartes SR dues.

    Pont SR → séance (2e vague Assimil) : on revoit l'ancien au moment où il
    commence à s'effacer, pas seulement après une faute. Les cartes dues viennent
    du SR global filtré par langue ; on garde leur `target_word` pour que le
    bouclage d'échéance retrouve la carte à la correction.
    """
    error_list = "\n".join(
        f"- {e['word']} (type: {e.get('error_type', 'vocabulaire')}, contexte: {e.get('context', '')})"
        for e in (errors or [])[:10]
    ) or "(aucune)"
    due_list = "\n".join(
        f"- {c.get('back', '')} = {c.get('front', '')}" for c in (due_cards or [])[:10]
    ) or "(aucune)"
    return f"""Tu génères un quiz de révision ciblé pour un apprenant de {language}.{_lang_script_hint(language)}

Construis le quiz à partir de DEUX sources, mélangées :
1. ERREURS PASSÉES (priorité haute) :
{error_list}
2. VOCABULAIRE À RAFRAÎCHIR (cartes dues, format « cible = français ») :
{due_list}

Génère 5 exercices en JSON valide, sans markdown :
{{
  "exercises": [
    {{
      "type": "translation",
      "prompt_fr": "phrase en français à traduire",
      "expected": "traduction correcte en {language}",
      "target_word": "mot ciblé par l'exercice (le mot cible exact si issu d'une carte)",
      "hint": "indice optionnel, peut être vide"
    }}
  ]
}}

Règles : pour le vocabulaire à rafraîchir, varie la forme de rappel (parfois FR→cible, \
parfois cible→FR via "hint", parfois en phrase à trou). Jamais deux fois le même mot. \
"target_word" reprend EXACTEMENT le mot cible de la carte quand l'exercice en vient."""


# ── Séquenceur adaptatif : sélecteur + générateurs de contenu par type ────────
#
# 1 prompt étroit par type de session (décision validée : prompts dédiés, sans
# branchement conditionnel — plus fiable sur un petit modèle). Chaque générateur
# produit la forme JSON de son render_kind ; le sélecteur ne fait qu'un choix.

def _lang_script_hint(language: str) -> str:
    """Consigne de script (vide pour le latin). Force le bon alphabet + translittération."""
    script = LANGUAGE_SCRIPTS.get((language or "").lower(), LATIN_SCRIPT)
    return SCRIPT_HINTS.get(script, "")


def _lang_tonal_hint(language: str) -> str:
    """Consigne « langue tonale » (vide sinon). Le ton, porté par le script (hanzi/thaï)
    ou par la langue (vietnamien), est phonémique : il doit toujours être noté."""
    lang = (language or "").lower()
    script = LANGUAGE_SCRIPTS.get(lang, LATIN_SCRIPT)
    tonal = bool(SCRIPTS.get(script, {}).get("tonal")) or lang in TONAL_LANGUAGES
    if not tonal:
        return ""
    return (
        " La langue cible est TONALE : le ton change le sens du mot. Indique TOUJOURS le ton "
        "dans la translittération (diacritiques, ex. mā má mǎ mà), jamais en chiffre ; ne "
        "l'omets jamais. Quand l'exercice s'y prête, oppose des mots ne différant QUE par le ton."
    )


def _lang_difficulty_hint(profile: dict) -> str:
    """Indice de difficulté continu (1-10) calculé en amont, à appliquer au contenu.

    Même gabarit pour tous les types : la densité progresse séance par séance, pas
    le nombre d'éléments inconnus d'un coup.
    """
    d = (profile or {}).get("difficulty_target")
    if not d:
        return ""
    return (
        f" Niveau de difficulté visé : {d}/10. Traduis-le concrètement : 1-3 = phrases "
        "courtes (5-8 mots), vocabulaire très fréquent, structures simples ; 4-6 = phrases "
        "moyennes (8-14 mots), 1-2 mots nouveaux, subordonnées simples ; 7-10 = phrases "
        "longues, vocabulaire moins fréquent, structures complexes (subordonnées multiples, "
        "nuances temporelles/modales). N'introduis JAMAIS plus de 2-3 éléments réellement "
        "nouveaux par exercice, même à 10 : c'est la densité qui progresse, pas le nombre "
        "d'inconnues d'un coup."
    )


def _lang_theme_hint(profile: dict) -> str:
    """Cohérence narrative d'une séance : thème central + contexte déjà exposé."""
    theme = (profile or {}).get("lesson_theme")
    context = (profile or {}).get("lesson_context")
    parts = []
    if theme:
        parts.append(f" Reste STRICTEMENT dans le thème de la séance : « {theme} ».")
    if context:
        parts.append(f" Prolonge ce qui a déjà été vu dans la séance (réutilise ce vocabulaire) : {context}.")
    return "".join(parts)


def _lang_level_hint(profile: dict) -> str:
    phase = (profile or {}).get("phase", "passive")
    language = (profile or {}).get("language", "")
    script = _lang_script_hint(language)
    tonal = _lang_tonal_hint(language)
    level = "Niveau A1 débutant : phrases très courtes (3-7 mots), vocabulaire de base."
    if phase == "active":
        level = "Niveau A2-B1 : l'apprenant produit, varie légèrement les structures."
    elif phase == "writing":
        level = "Phase d'intégration de l'écriture : reste sur des mots/signes très simples."
    cefr = (profile or {}).get("level")
    if cefr:
        level += f" (niveau visé : {cefr})"
    return level + script + tonal + _lang_difficulty_hint(profile) + _lang_theme_hint(profile)


def _lang_weak_points_line(weak_points: list[dict] | None) -> str:
    words = [w.get("word", "") for w in (weak_points or []) if w.get("word")]
    return ", ".join(words[:5]) if words else "aucun pour l'instant"


# Profondeur multi-étapes (Axe 3) : une question d'inférence ancre mieux qu'un
# repérage littéral. On la demande dans le même appel (coût nul) et on la marque
# pour que l'interface la distingue.
_INFERENCE_HINT = (
    " Parmi les questions, marque-en EXACTEMENT UNE avec \"depth\": \"inference\" : "
    "elle doit demander de DÉDUIRE une information non dite explicitement (raisonnement "
    "sur le texte), pas un simple repérage littéral. Les autres restent du repérage."
)


def build_lang_session_select_prompt(state: dict, available: list[dict]) -> str:
    codes = [t["code"] for t in available]
    catalogue = "\n".join(
        f"- {t['code']} ({t.get('skill', '')}) : {t.get('description', '')}" for t in available
    )
    weak = [w.get("word", "") for w in (state.get("weak_points") or []) if w.get("word")]
    return f"""Tu es le séquenceur pédagogique d'une méthode de langue adaptative (type Assimil).
Réponds UNIQUEMENT en JSON, rien d'autre. Ne génère AUCUN contenu pédagogique : tu choisis \
seulement le TYPE de la prochaine session.

État de l'apprenant :
- Session n°{state.get('session_n')}, phase {state.get('phase')}
- Dernier type joué : {state.get('last_session_type')}
- Répartition des compétences (7 dernières sessions) : {state.get('skill_distribution_7')}
- Points faibles actifs : {weak or "aucun"}

Types disponibles :
{catalogue}

Choisis exactement UN code parmi : {codes}
Règles :
- Ne reprends jamais le dernier type joué si une alternative existe.
- Favorise les compétences les moins travaillées récemment.
- S'il existe des points faibles, privilégie un type qui les fait retravailler.

Réponds : {{"chosen_type": "<un code de la liste>", "reason": "<courte justification>"}}"""


def build_lang_dialogue_ecoute_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu es auteur d'une méthode {language} type Assimil. Génère un court dialogue \
d'ÉCOUTE (compréhension orale) à révéler progressivement. {_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "theme": "thème courant et concret",
  "dialogue": [{{"speaker": "A", "target": "phrase en {language}", "phonetic": "transcription phonétique (obligatoire)", "translation": "traduction française"}}],
  "notes": {{"grammar": "max 200 car.", "pronunciation": "conseil d'écoute clé, max 200 car.", "cultural": "max 150 car."}},
  "vocabulary": [{{"word": "mot en {language}", "translation": "français", "example": "exemple court"}}]
}}

Contraintes : 4 à 8 répliques alternant A/B ; "phonetic" jamais vide ; 3 à 6 mots de vocabulaire."""


def build_lang_dialogue_lecture_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu es auteur d'une méthode {language} type Assimil. Génère un court dialogue de \
LECTURE (compréhension écrite) avec traduction et notes. {_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "theme": "thème courant et concret",
  "dialogue": [{{"speaker": "A", "target": "phrase en {language}", "phonetic": "", "translation": "traduction française"}}],
  "notes": {{"grammar": "explication du point clé, max 250 car.", "pronunciation": "max 150 car.", "cultural": "max 150 car."}},
  "vocabulary": [{{"word": "mot en {language}", "translation": "français", "example": "exemple court"}}]
}}

Contraintes : 5 à 9 répliques alternant A/B ; toutes les "translation" en français ; 4 à 6 mots de vocabulaire."""


def build_lang_vocabulaire_contextuel_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu enseignes le vocabulaire {language} EN CONTEXTE (jamais de liste sèche). \
{_lang_level_hint(profile)} Points faibles à réactiver si possible : {_lang_weak_points_line(weak_points)}.

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "items": [{{"word": "mot en {language}", "translation": "français", "example_target": "phrase exemple en {language}", "example_translation": "traduction de l'exemple"}}],
  "questions": [{{"question": "question de compréhension en français", "choices": ["A: ...", "B: ...", "C: ..."], "correct": "A", "explanation": "courte", "depth": "literal"}}]
}}
{_INFERENCE_HINT}
Contraintes : 6 à 8 items ; chaque "example_target" contient le mot ; exactement 2 questions."""


def build_lang_culture_courte_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu écris un court texte CULTUREL et factuel sur un pays où l'on parle {language}, \
adapté à un apprenant. {_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "title": "titre court",
  "text_target": "texte de 3 à 5 phrases en {language}",
  "text_translation": "traduction française intégrale",
  "glossary": [{{"word": "mot utile en {language}", "translation": "français"}}],
  "questions": [{{"question": "question de compréhension en français", "choices": ["A: ...", "B: ...", "C: ..."], "correct": "A", "explanation": "courte", "depth": "literal"}}]
}}
{_INFERENCE_HINT}
Contraintes : 3 à 5 phrases ; 4 à 6 entrées de glossaire ; exactement 2 questions."""


def build_lang_phonetique_ciblee_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu es phonéticien pour le {language}. Choisis UN son difficile pour un \
francophone et construis un exercice de CONSCIENCE PHONÉTIQUE (vérifiable, sans audio). \
{_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "focus_sound": "le son ciblé (ex. une lettre/groupe et sa valeur)",
  "explanation": "comment le produire, en français, max 250 car.",
  "minimal_pairs": [{{"a": "mot en {language}", "b": "mot proche en {language}", "note": "ce qui change"}}],
  "drills": [
    {{"kind": "read", "target": "phrase d'entraînement en {language}", "phonetic": "transcription", "tone": "ton si langue tonale, sinon vide", "translation": "français"}},
    {{"kind": "stress", "word": "mot en {language}", "syllables": ["syl", "la", "bes"], "stressed_index": 1, "translation": "français"}},
    {{"kind": "spell_to_sound", "written": "graphie en {language}", "options": ["transcription correcte", "leurre 1", "leurre 2"], "answer": 0, "translation": "français"}}
  ]
}}

Contraintes : 3 à 5 paires minimales ; 3 à 5 drills mêlant les 3 "kind" (read/stress/spell_to_sound). \
Pour "stress", "stressed_index" pointe la syllabe accentuée (0 = la 1re). Pour "spell_to_sound", \
"answer" est l'index (0-based) de la BONNE transcription dans "options" (3 options, 1 seule correcte)."""


def build_lang_histoire_courte_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu écris un MINI-RÉCIT simple et progressif en {language} (compréhension écrite \
narrative). {_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "title": "titre du récit",
  "text_target": "récit de 4 à 6 phrases en {language}",
  "text_translation": "traduction française intégrale",
  "glossary": [{{"word": "mot utile en {language}", "translation": "français"}}],
  "questions": [{{"question": "question de compréhension en français", "choices": ["A: ...", "B: ...", "C: ..."], "correct": "A", "explanation": "courte", "depth": "literal"}}]
}}
{_INFERENCE_HINT}
Contraintes : 4 à 6 phrases qui s'enchaînent ; 4 à 6 entrées de glossaire ; exactement 2 questions."""


def _lang_production_two_step_json(language: str) -> str:
    """Gabarit JSON commun de la production en 2 paliers (guidé → libre).

    L'échafaudage `guided` (à trous/amorces) précède la production réelle `free` :
    le mouvement Assimil de ne jamais lâcher l'apprenant en production totale sans
    rampe d'accès. Un seul appel de génération produit les deux paliers.
    """
    return f"""{{
  "instructions": "consigne globale en français",
  "guided": {{
    "prompt": "amorce à compléter en {language} (texte avec ___ ou début de phrase)",
    "expected": "la complétion attendue en {language}",
    "hint": "indice court, peut être vide"
  }},
  "free": {{
    "prompt": "consigne de production libre en français (l'apprenant formule à sa façon)",
    "reference": "UNE formulation possible en {language} (pas la seule)",
    "hint": "indice court, peut être vide"
  }}
}}"""


def build_lang_rappel_production_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu animes un exercice de RAPPEL + PRODUCTION en {language}, en DEUX paliers : \
d'abord guidé (échafaudage), puis libre (production réelle). {_lang_level_hint(profile)} \
Réactive si possible : {_lang_weak_points_line(weak_points)}.

Réponds UNIQUEMENT en JSON valide, sans markdown :
{_lang_production_two_step_json(language)}

Contraintes : le palier "guided" amorce/complète, le palier "free" demande une production \
personnelle sur le MÊME point. "reference" est une bonne réponse parmi d'autres."""


def build_lang_traduction_inverse_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu génères un exercice de TRADUCTION INVERSE (français -> {language}, production \
écrite). {_lang_level_hint(profile)} Cible si possible : {_lang_weak_points_line(weak_points)}.

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "items": [{{"prompt_fr": "phrase en français à traduire", "expected": "traduction correcte en {language}", "hint": "indice optionnel, peut être vide"}}]
}}

Contraintes : 5 phrases ; difficulté progressive ; "expected" toujours en {language}."""


def build_lang_dictee_courte_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu prépares une courte DICTÉE en {language} : l'apprenant écrira ce qu'il entend, \
segment par segment. {_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "segments": [{{"target": "segment à dicter en {language}", "phonetic": "transcription phonétique", "translation": "traduction française"}}]
}}

Contraintes : 3 à 5 segments courts ; "phonetic" jamais vide."""


def build_lang_reformulation_libre_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu animes un exercice de REFORMULATION en {language} (production ouverte), en DEUX \
paliers : d'abord guidé (amorce à compléter), puis libre (l'apprenant reformule à sa façon). \
{_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{_lang_production_two_step_json(language)}

Contraintes : "guided" donne une amorce à compléter ; "free" demande une reformulation \
personnelle de la même idée. "reference" est une formulation correcte parmi d'autres."""


def build_lang_mini_dialogue_simule_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu crées un DIALOGUE SIMULÉ (jeu de rôle) en {language} : l'apprenant complète la \
réplique manquante. {_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "instructions": "le rôle de l'apprenant, en français",
  "tasks": [{{"prompt": "réplique attendue de l'apprenant, décrite en français", "context": "réplique précédente en {language} (+ traduction)", "reference": "réplique modèle en {language}", "hint": "indice optionnel"}}]
}}

Contraintes : 3 à 4 répliques à produire ; "context" donne la réplique précédente en {language}."""


def build_lang_correction_guidee_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu construis un exercice de CORRECTION GUIDÉE en {language} (grammaire en contexte) : \
des phrases contenant une erreur typique à repérer et corriger. {_lang_level_hint(profile)} \
Erreurs à viser si possible : {_lang_weak_points_line(weak_points)}.

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "instructions": "consigne globale en français",
  "tasks": [{{"prompt": "phrase en {language} contenant UNE erreur", "context": "peut être vide", "reference": "la phrase corrigée en {language}", "hint": "nature de l'erreur, en français"}}]
}}

Contraintes : 4 à 5 phrases ; une seule erreur par phrase ; "reference" est la version correcte."""


# ── Phase « écriture » : intégration du système d'écriture (scripts non-latins) ──

def build_lang_ecriture_decouverte_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu es auteur d'une méthode {language} type Assimil, partie INTÉGRATION DE L'ÉCRITURE. \
Présente un PETIT lot de lettres/signes du système d'écriture du {language}, leur son et des \
mots-exemples très simples. {_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "intro": "présentation en français du lot de signes, max 250 car.",
  "signs": [{{"sign": "le signe dans le système d'écriture cible", "name": "nom de la lettre", "sound": "le son (ex. /b/)", "translit": "translittération latine", "tone": "ton si langue tonale, sinon vide", "example_word": "mot-exemple dans le système cible", "example_translit": "translittération du mot", "example_translation": "traduction française"}}],
  "reading": [{{"target": "mot court dans le système cible", "translit": "translittération", "translation": "français"}}],
  "drill": [{{"question": "question de reconnaissance en français", "choices": ["A: ...", "B: ...", "C: ..."], "correct": "A", "explanation": "courte"}}]
}}

Contraintes : 4 à 6 signes ; 3 à 5 mots de lecture ; exactement 2 questions de drill."""


def build_lang_ecriture_lecture_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu es auteur d'une méthode {language} type Assimil, partie INTÉGRATION DE L'ÉCRITURE. \
Construis un exercice de LECTURE des signes : reconnaître et translittérer des mots déjà introduits. \
{_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "intro": "consigne de lecture en français, max 200 car.",
  "signs": [{{"sign": "signe à reconnaître", "name": "nom", "sound": "le son", "translit": "translittération", "tone": "ton si langue tonale, sinon vide", "example_word": "", "example_translit": "", "example_translation": ""}}],
  "reading": [{{"target": "mot dans le système cible", "translit": "translittération", "translation": "français"}}],
  "drill": [{{"question": "question de lecture en français", "choices": ["A: ...", "B: ...", "C: ..."], "correct": "A", "explanation": "courte"}}]
}}

Contraintes : 3 à 5 signes rappelés ; 4 à 6 mots de lecture ; exactement 2 questions."""


def build_lang_ecriture_dictee_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu prépares une DICTÉE DE SIGNES en {language} (intégration de l'écriture) : \
l'apprenant écrit dans le système cible ce qu'il entend, segment par segment. {_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "segments": [{{"target": "mot/segment dans le système d'écriture cible", "phonetic": "translittération phonétique", "translation": "traduction française"}}]
}}

Contraintes : 3 à 5 segments très courts ; "phonetic" (translittération) jamais vide."""


def build_lang_lesson_plan_prompt(state: dict, level: str, language: str, phase: str) -> str:
    weak = [w.get("word", "") for w in (state.get("weak_points") or []) if w.get("word")]
    phase_hint = {
        "writing": "intégration de l'écriture (lettres, lecture des signes)",
        "passive": "assimilation passive (compréhension, vocabulaire en contexte)",
        "active": "production active (traduction, expression, correction)",
    }.get(phase, "assimilation passive")
    # Fil rouge entre séances (Axe 4) : un thème qui prolonge le précédent et un
    # personnage récurrent ancrent affectivement → mémoire renforcée. Coût nul.
    previous_theme = (state or {}).get("previous_theme")
    character = (state or {}).get("character")
    continuity = ""
    if previous_theme:
        continuity += (
            f" Thème de la séance précédente : « {previous_theme} ». Propose un thème qui le "
            "PROLONGE ou le complète logiquement (même univers ou situation qui évolue), SANS le répéter."
        )
    if character:
        continuity += (
            f" Personnage récurrent de l'apprenant : « {character} ». Tu peux l'évoquer dans "
            "l'intro pour donner un fil narratif d'une séance à l'autre."
        )
    return f"""Tu es le concepteur d'une SÉANCE de méthode {language} type Assimil. \
Tu choisis seulement un THÈME concret et fédérateur pour une séance de 10 exercices qui s'enchaînent. \
Phase actuelle : {phase_hint}. Niveau : {level}. Séance n°{state.get('session_n')}. \
Points faibles à réactiver si pertinent : {weak or "aucun"}.{continuity}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{"theme": "<thème concret de la vie courante, 2-5 mots>", "intro": "<une phrase de cadrage en français>"}}"""


def build_lang_placement_prompt(language: str, script: str) -> str:
    script_line = ""
    if script and script != LATIN_SCRIPT:
        meta = SCRIPTS.get(script, {})
        rom = meta.get("romanization")
        rom_part = f", avec translittération ({rom})" if rom else ""
        script_line = (
            f" Le {language} s'écrit dans un système d'écriture non latin ({script}, "
            f"{meta.get('kind', '')}){rom_part}. Inclus 2 items « lecture du système d'écriture » "
            "(reconnaître un mot écrit dans le script cible) marqués \"skill\": \"ecriture\"."
        )
        if meta.get("tonal"):
            script_line += (
                " La langue est TONALE : un des items d'écriture doit porter sur le ton "
                "(distinguer des mots ne différant que par le ton)."
            )
        if meta.get("continuous"):
            script_line += (
                " Le système est logographique (caractères en nombre ouvert) : les items "
                "d'écriture évaluent la reconnaissance de caractères COURANTS, pas un alphabet fini."
            )
    return f"""Tu conçois un TEST DE NIVEAU pour situer un apprenant de {language} sur l'échelle CEFR \
(A1 à C1).{script_line} Génère 12 à 15 items de difficulté CROISSANTE, mêlant compréhension (QCM) et \
1 à 2 items de production (traduction courte FR -> {language}).

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "items": [
    {{"id": 1, "level": "A1", "skill": "comprehension", "format": "qcm", "question": "...", "choices": ["A: ...", "B: ...", "C: ..."], "correct": "A"}},
    {{"id": 16, "level": "B1", "skill": "production", "format": "translation", "question": "phrase française à traduire", "expected": "traduction en {language}"}}
  ]
}}

Contraintes : 12 à 15 items ; "level" parmi A1,A2,B1,B2,C1 ; difficulté croissante ; format "qcm" ou "translation"."""


def build_lang_placement_eval_prompt(language: str, summary: str) -> str:
    return f"""Tu es examinateur CEFR pour le {language}. À partir des résultats d'un test de niveau, \
estime le niveau CEFR d'entrée de l'apprenant.

Résultats (item: niveau visé -> correct ou non) :
{summary}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{"cefr": "<A1|A2|B1|B2|C1>", "can_read_script": <true|false>, "comment": "<une phrase en français>"}}

"can_read_script" : true seulement si les items de lecture du système d'écriture (skill ecriture) sont réussis."""


# ── Types interactifs (correction côté client) : cloze / ordering / matching / transform ──
#
# La solution est connue à la génération → notation instantanée, robustesse
# hors-ligne. La consigne JSON est STRICTE car le parseur rejette les items dont la
# solution est incohérente (un exercice mal corrigé est pire que pas d'exercice).

def build_lang_completion_choix_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu construis un exercice de COMPLÉTION À TROUS avec banque de mots en {language}. \
{_lang_level_hint(profile)} Réactive si possible : {_lang_weak_points_line(weak_points)}.

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "mode": "bank",
  "instructions": "consigne courte en français",
  "sentences": [
    {{"text": "phrase en {language} avec un ou deux trous notés ___", "blanks": ["mot1", "mot2"], "options": ["mot1", "mot2", "leurre1", "leurre2"], "translation": "traduction française"}}
  ]
}}

Contraintes STRICTES : 3 à 5 phrases ; chaque ___ correspond à un mot de "blanks" dans l'ORDRE ; \
autant de ___ que d'entrées dans "blanks" ; "options" contient TOUS les "blanks" PLUS 2-3 distracteurs \
plausibles ; tous les mots de "blanks" figurent dans "options"."""


def build_lang_cloze_libre_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu construis un exercice de COMPLÉTION À TROUS à saisie libre en {language} (sans banque). \
{_lang_level_hint(profile)} Cible si possible : {_lang_weak_points_line(weak_points)}.

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "mode": "free",
  "instructions": "consigne courte en français",
  "sentences": [
    {{"text": "phrase en {language} avec un trou noté ___", "blanks": ["mot attendu"], "translation": "traduction française"}}
  ]
}}

Contraintes STRICTES : 3 à 5 phrases ; UN seul ___ par phrase ; "blanks" contient exactement le mot \
attendu ; pas de champ "options" (saisie libre)."""


def build_lang_remise_en_ordre_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu construis un exercice de REMISE EN ORDRE de mots en {language}. \
{_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "task": "consigne courte en français",
  "items": [
    {{"tokens": ["mots", "dans", "le", "désordre"], "solution": ["les", "mots", "dans", "le", "bon", "ordre"], "translation": "traduction française"}}
  ]
}}

Contraintes STRICTES : 3 à 5 items ; "solution" est la phrase correcte en {language} ; "tokens" contient \
EXACTEMENT les mêmes éléments que "solution" mais mélangés (même multiset, juste l'ordre change) ; \
4 à 8 tokens par item."""


def build_lang_construction_phrase_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu construis un exercice de CONSTRUCTION DE PHRASE à partir de fragments en {language} \
(l'apprenant assemble les fragments dans le bon ordre). {_lang_level_hint(profile)}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "task": "consigne courte en français (ex. « Construis la phrase qui traduit … »)",
  "items": [
    {{"tokens": ["fragments", "mélangés"], "solution": ["fragments", "dans", "l'ordre"], "translation": "ce que la phrase doit dire, en français"}}
  ]
}}

Contraintes STRICTES : 3 à 5 items ; "solution" est la phrase correcte en {language} ; "tokens" contient \
EXACTEMENT les mêmes éléments que "solution" mais mélangés ; 4 à 8 tokens par item."""


def build_lang_appariement_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu construis un exercice d'APPARIEMENT (relier chaque mot {language} à sa traduction). \
{_lang_level_hint(profile)} Réactive si possible : {_lang_weak_points_line(weak_points)}.

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "task": "consigne courte en français",
  "pairs": [
    {{"left": "mot ou expression en {language}", "right": "sa traduction française"}}
  ]
}}

Contraintes STRICTES : 4 à 6 paires ; "left" en {language}, "right" en français ; chaque "right" \
correspond à UN SEUL "left" (pas de doublon ambigu)."""


def build_lang_transformation_prompt(language: str, profile: dict, weak_points=None) -> str:
    return f"""Tu construis un exercice de TRANSFORMATION GUIDÉE en {language} (conjugaison, nombre, \
genre, forme affirmative/négative…). {_lang_level_hint(profile)} \
Cible si possible : {_lang_weak_points_line(weak_points)}.

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "task": "consigne globale de transformation en français (ex. « Mets au passé »)",
  "items": [
    {{"source": "phrase de départ en {language}", "expected": "phrase transformée attendue en {language}", "focus": "ce qui change (court)", "hint": "indice court, peut être vide"}}
  ]
}}

Contraintes STRICTES : 4 à 6 items ; "expected" est l'unique transformation correcte de "source" \
selon la consigne ; "source" et "expected" en {language}."""


# code de type -> builder de prompt de contenu (revision_adaptative est traité à
# part : il réutilise le quiz de révision alimenté par les erreurs passées).
LANG_SESSION_PROMPT_BUILDERS: dict = {
    "dialogue_ecoute": build_lang_dialogue_ecoute_prompt,
    "dialogue_lecture": build_lang_dialogue_lecture_prompt,
    "vocabulaire_contextuel": build_lang_vocabulaire_contextuel_prompt,
    "culture_courte": build_lang_culture_courte_prompt,
    "phonetique_ciblee": build_lang_phonetique_ciblee_prompt,
    "histoire_courte": build_lang_histoire_courte_prompt,
    "rappel_production": build_lang_rappel_production_prompt,
    "traduction_inverse": build_lang_traduction_inverse_prompt,
    "dictee_courte": build_lang_dictee_courte_prompt,
    "reformulation_libre": build_lang_reformulation_libre_prompt,
    "mini_dialogue_simule": build_lang_mini_dialogue_simule_prompt,
    "correction_guidee": build_lang_correction_guidee_prompt,
    "ecriture_decouverte": build_lang_ecriture_decouverte_prompt,
    "ecriture_lecture": build_lang_ecriture_lecture_prompt,
    "ecriture_dictee": build_lang_ecriture_dictee_prompt,
    # Types interactifs (correction côté client).
    "completion_choix": build_lang_completion_choix_prompt,
    "cloze_libre": build_lang_cloze_libre_prompt,
    "remise_en_ordre": build_lang_remise_en_ordre_prompt,
    "construction_phrase": build_lang_construction_phrase_prompt,
    "appariement": build_lang_appariement_prompt,
    "transformation": build_lang_transformation_prompt,
}


# ──────────────────────────────────────────────────────────────────────────────
# Assistant bulle (lecteur scroll libre)
# ──────────────────────────────────────────────────────────────────────────────

def build_assistant_answer_prompt(
    page_text: str,
    user_question: str,
    doc_title: str = "",
    chapter_title: str = "",
    page_number: int | None = None,
    metacog_profile: dict | None = None,
    session_gauges: dict | None = None,
    recent_exchanges: list[dict] | None = None,
    related_flashcards: list[dict] | None = None,
    selected_snippets: list[str] | None = None,
    user_highlights: list[str] | None = None,
    retrieved_passages: list[dict] | None = None,
) -> str:
    """Réponse de l'assistant à une question libre posée pendant la lecture.

    Le contexte est un PageContextSnapshot : la page visible au moment exact
    où l'utilisateur a validé sa question. Les marqueurs de section
    (« Paragraphe source », « Question de l'étudiant ») sont volontairement
    identiques au prompt follow_up pour partager le repli local.

    `retrieved_passages` (RAG) apporte des extraits venant d'AILLEURS dans le
    document ; ils enrichissent la réponse mais ne servent jamais de source aux
    `highlights`, qui restent copiés de la seule page visible.
    """
    student_context = _student_context_block(selected_snippets, user_highlights)
    retrieved_context = _retrieved_passages_block(retrieved_passages)
    exchanges_lines = []
    for item in (recent_exchanges or [])[-4:]:
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if question:
            exchanges_lines.append(f"- Q: {question[:160]}")
        if answer:
            exchanges_lines.append(f"  R: {answer[:200]}")
    exchanges = "\n".join(exchanges_lines) if exchanges_lines else _t("(aucun)", "(none)")
    flashcards = _format_related_flashcards(related_flashcards) or _t("(aucune)", "(none)")
    page_label = f"{page_number}" if page_number else "?"

    if _i18n.current_lang() == "en":
        return f"""You are Gemma, the reading assistant bubble of MetaC-App. The student reads a PDF freely and just asked you a question by clicking on your bubble.

Document: {doc_title or "?"} — chapter: {chapter_title or "?"} — visible page: {page_label}
Metacognitive profile: {_json(metacog_profile or {})}
Session gauges (0-100): {_json(session_gauges or {})}
Recent exchanges with the assistant:
{exchanges}
Existing student flashcards related to this document (fronts):
{flashcards}
{student_context}{retrieved_context}
Paragraphe source (text of the page visible when the student pressed Send):
---
{(page_text or "")[:3500]}
---

Question de l'étudiant:
---
{(user_question or "")[:500]}
---

If an image is attached, it is the rendered PDF page itself: trust it for notations, figures and layout.

Respond in valid JSON, without Markdown:
{{
  "answer": "clear, pedagogical answer grounded in the visible page, then a general supplement if useful",
  "metacog_signals": {{
    "context_comprehension": 0.0,
    "creativity": 0.0,
    "attention": 0.0,
    "retention": 0.0,
    "curiosity": 0.0,
    "meta_cognition": 0.0
  }},
  "curiosity_signals": {{
    "asked_follow_up_question": true,
    "asked_for_clarification": false,
    "asked_for_example": false,
    "explored_beyond_required_answer": false
  }},
  "highlights": [{{"quote": "EXACT quote copied from the visible page (8 to 25 words)", "purpose": "explain"}}]
}}

Constraints:
- curiosity must be at least 1.0: the student is asking on their own initiative.
- highlights: 0 to 3 quotes copied WORD FOR WORD from the visible page text (never rephrased), pointing at the passages your answer relies on — they will be highlighted on the page for the student. purpose is "key", "explain" or "reference". Use an empty list if nothing relevant.
- The "relevant passages found elsewhere" come from OTHER pages of the document: use them to enrich your answer and cite their page in prose (e.g. "see p.12"), but NEVER copy them into highlights — every highlight quote must come from the visible page text only.
- Answer first from the visible page, then add general knowledge introduced by "More generally, ..." when the question goes beyond the page.
- Never invent facts about the document that the page does not show.
- If one of the listed flashcards already covers the question, naturally point it out ("You already have a flashcard on this") and connect your answer to it.
- Keep the answer compact (4-8 sentences): it is displayed in a small floating panel.
- meta_cognition stays at 0.0."""

    return f"""Tu es Gemma, la bulle assistante de lecture de MetaC-App. L'étudiant lit un PDF librement et vient de te poser une question en cliquant sur ta bulle.

Document : {doc_title or "?"} — chapitre : {chapter_title or "?"} — page visible : {page_label}
Profil métacognitif : {_json(metacog_profile or {})}
Jauges de session (0-100) : {_json(session_gauges or {})}
Échanges récents avec l'assistant :
{exchanges}
Flashcards existantes de l'étudiant liées à ce document (rectos) :
{flashcards}
{student_context}{retrieved_context}
Paragraphe source (texte de la page visible au moment où l'étudiant a envoyé sa question) :
---
{(page_text or "")[:3500]}
---

Question de l'étudiant :
---
{(user_question or "")[:500]}
---

Si une image est jointe, c'est la page PDF rendue elle-même : fie-toi à elle pour les notations, figures et mises en page.

Réponds en JSON valide, sans Markdown :
{{
  "answer": "réponse claire et pédagogique ancrée dans la page visible, puis un complément général si utile",
  "metacog_signals": {{
    "context_comprehension": 0.0,
    "creativity": 0.0,
    "attention": 0.0,
    "retention": 0.0,
    "curiosity": 0.0,
    "meta_cognition": 0.0
  }},
  "curiosity_signals": {{
    "asked_follow_up_question": true,
    "asked_for_clarification": false,
    "asked_for_example": false,
    "explored_beyond_required_answer": false
  }},
  "highlights": [{{"quote": "citation EXACTE copiée de la page visible (8 à 25 mots)", "purpose": "explain"}}]
}}

Contraintes :
- curiosity doit être au moins 1.0 : l'étudiant questionne de sa propre initiative.
- highlights : 0 à 3 citations copiées MOT POUR MOT du texte de la page visible (jamais reformulées), désignant les passages sur lesquels ta réponse s'appuie — ils seront surlignés sur la page pour l'étudiant. purpose vaut "key", "explain" ou "reference". Liste vide si rien de pertinent.
- Les « passages pertinents trouvés ailleurs » viennent d'AUTRES pages du document : sers-t'en pour enrichir ta réponse et cite leur page en clair (ex. « voir p.12 »), mais ne les recopie JAMAIS dans highlights — toute citation surlignée doit provenir uniquement du texte de la page visible.
- Réponds d'abord depuis la page visible, puis ajoute un complément de connaissances générales introduit par "Plus généralement, ..." dès que la question dépasse la page.
- N'invente jamais de fait sur le document que la page ne montre pas.
- Si une des flashcards listées couvre déjà la question, signale-le naturellement ("Tu as déjà une flashcard sur ce point") et relie ta réponse à elle.
- Réponse compacte (4 à 8 phrases) : elle s'affiche dans un petit panneau flottant.
- meta_cognition reste à 0.0."""


def build_intervention_prompt(context: dict) -> str:
    """Décision structurée d'intervention autonome de l'assistant."""
    trigger_labels_fr = {
        "long_dwell": "l'étudiant reste longtemps sur la même page",
        "page_revisits": "l'étudiant revient plusieurs fois sur cette page",
        "low_attention": "la jauge d'attention de l'étudiant est basse",
        "hard_page": "la page contient beaucoup de mathématiques ou de figures",
        "repeated_questions": "l'étudiant a posé plusieurs questions sur cette page",
        "flashcard_due": "une flashcard de l'étudiant est arrivée à échéance de révision",
    }
    trigger_labels_en = {
        "long_dwell": "the student has stayed a long time on the same page",
        "page_revisits": "the student keeps coming back to this page",
        "low_attention": "the student's attention gauge is low",
        "hard_page": "the page is heavy on math or figures",
        "repeated_questions": "the student asked several questions on this page",
        "flashcard_due": "one of the student's flashcards is due for review",
    }
    trigger = str(context.get("trigger") or "long_dwell")
    page = context.get("page", "?")
    mode = str(context.get("mode") or "normal")
    due_front = " ".join(str(context.get("due_flashcard_front") or "").split())[:120]
    due_line_fr = f'\nFlashcard due : « {due_front} »' if due_front else ""
    due_line_en = f'\nDue flashcard: "{due_front}"' if due_front else ""
    hl_quotes = _format_quote_lines(context.get("user_highlights"), limit=3)
    hl_line_fr = f"\nPassages surlignés par l'étudiant :\n{hl_quotes}" if hl_quotes else ""
    hl_line_en = f"\nPassages highlighted by the student:\n{hl_quotes}" if hl_quotes else ""

    if _i18n.current_lang() == "en":
        reason = trigger_labels_en.get(trigger, trigger)
        return f"""You are Gemma, the discreet reading assistant of MetaC-App. The application has ALREADY detected a pedagogical signal worth a brief nudge, so you are going to step in now — gently and warmly. Your job here is to FORMULATE that intervention, not to second-guess whether one is warranted.

Observed signal: {reason} (page {page}).{due_line_en}{hl_line_en}
Time on page: {context.get("dwell_s", "?")} s — visits: {context.get("visits", "?")} — questions asked on this page: {context.get("user_questions_on_page", 0)}.
Session gauges (0-100): {_json(context.get("gauges") or {})}
Assistant mode: {mode} ("coach" = warmer and more talkative, "normal" = sober and to the point).

Text of the page:
---
{str(context.get("page_text") or "")[:2500]}
---

Respond in valid JSON, without Markdown:
{{
  "should_intervene": true,
  "kind": "ask_question",
  "message": "one short, warm, non-intrusive sentence addressed to the student",
  "question": "ONE short pedagogical question checking the key idea of this page",
  "highlights": [{{"quote": "EXACT quote copied from the page (8 to 25 words)", "purpose": "key"}}]
}}

Constraints:
- kind must be one of: "offer_help", "ask_question", "suggest_pause", "rephrase_offer", "review_flashcard".
- Prefer "ask_question" when you can ask a good question about this page (then fill "question"); otherwise "offer_help"/"rephrase_offer" and leave "question" empty.
- "review_flashcard" only if the observed signal is a due flashcard: briefly offer to review it (mention its topic in message), without interrupting a difficult passage.
- highlights: 0 to 2 quotes copied WORD FOR WORD from the page text (never rephrased), pointing at the passage your intervention is about — it will be highlighted on the page. Empty list if not applicable.
- "suggest_pause" only if the attention gauge is clearly low.
- "rephrase_offer" if the page looks dense or mathematical: offer to rephrase it.
- Keep should_intervene true by default (a signal was already detected). Set it to false ONLY if the page is so trivial that intervening would clearly disturb more than it helps.
- message: maximum 2 sentences, no emoji spam, never guilt-tripping."""

    reason = trigger_labels_fr.get(trigger, trigger)
    return f"""Tu es Gemma, l'assistante de lecture discrète de MetaC-App. L'application a DÉJÀ détecté un signal pédagogique qui mérite un petit coup de pouce, donc tu vas intervenir maintenant — brièvement et chaleureusement. Ton rôle ici est de FORMULER cette intervention, pas de redécider s'il faut intervenir.

Signal observé : {reason} (page {page}).{due_line_fr}{hl_line_fr}
Temps sur la page : {context.get("dwell_s", "?")} s — visites : {context.get("visits", "?")} — questions posées sur cette page : {context.get("user_questions_on_page", 0)}.
Jauges de session (0-100) : {_json(context.get("gauges") or {})}
Mode de l'assistant : {mode} ("coach" = plus chaleureux et bavard, "normal" = sobre et direct).

Texte de la page :
---
{str(context.get("page_text") or "")[:2500]}
---

Réponds en JSON valide, sans Markdown :
{{
  "should_intervene": true,
  "kind": "ask_question",
  "message": "une phrase courte, chaleureuse et non intrusive adressée à l'étudiant",
  "question": "UNE question pédagogique courte vérifiant l'idée clé de cette page",
  "highlights": [{{"quote": "citation EXACTE copiée de la page (8 à 25 mots)", "purpose": "key"}}]
}}

Contraintes :
- kind doit valoir : "offer_help", "ask_question", "suggest_pause", "rephrase_offer" ou "review_flashcard".
- Privilégie "ask_question" quand tu peux poser une bonne question sur cette page (remplis alors "question") ; sinon "offer_help"/"rephrase_offer" et laisse "question" vide.
- "review_flashcard" uniquement si le signal observé est une flashcard due : propose brièvement de la réviser (mentionne son sujet dans message), sans interrompre un passage difficile.
- highlights : 0 à 2 citations copiées MOT POUR MOT du texte de la page (jamais reformulées), désignant le passage concerné par ton intervention — il sera surligné sur la page. Liste vide si non pertinent.
- "suggest_pause" seulement si la jauge d'attention est nettement basse.
- "rephrase_offer" si la page semble dense ou mathématique : propose de la reformuler.
- Garde should_intervene à true par défaut (un signal a déjà été détecté). Ne le mets à false QUE si la page est triviale au point qu'intervenir dérangerait clairement plus que ça n'aiderait.
- message : 2 phrases maximum, pas de déluge d'emojis, jamais culpabilisant."""


# ── Brainstorming — chat libre + RAG sur la base de l'utilisateur ──────────────

def _brainstorm_history_block(history: list[dict] | None, max_turns: int = 8) -> str:
    lines: list[str] = []
    for item in (history or [])[-max_turns:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        who = _t("Utilisateur", "User") if role == "user" else "Gemma"
        lines.append(f"{who} : {content[:600]}")
    return "\n".join(lines) if lines else _t("(début de la discussion)", "(start of discussion)")


def _brainstorm_sources_block(sources: list[dict] | None) -> str:
    if not sources:
        return _t("(aucun résultat dans la base)", "(no results in the database)")
    label = {
        "highlight": _t("Surlignage", "Highlight"),
        "qa": _t("Échange passé", "Past exchange"),
        "flashcard": "Flashcard",
        "document": "Document",
    }
    lines: list[str] = []
    for i, s in enumerate(sources, 1):
        kind = label.get(s.get("source_type"), s.get("source_type") or "?")
        title = s.get("doc_title")
        page = s.get("page")
        loc = ""
        if title:
            loc = f" — {title}"
            if page:
                loc += _t(f", p.{page}", f", p.{page}")
        snippet = str(s.get("snippet") or "").strip()
        lines.append(f"[{i}] {kind}{loc} : « {snippet} »")
    return "\n".join(lines)


def build_brainstorm_search_decide_prompt(history: list[dict] | None, user_message: str) -> str:
    """Décision JSON courte : faut-il fouiller la base de l'utilisateur, et avec quels mots-clés."""
    hist = _brainstorm_history_block(history, max_turns=4)
    return f"""{_t("Tu prépares la réponse d'un assistant de brainstorming qui a accès à la base personnelle de l'utilisateur (PDFs lus, passages surlignés, flashcards, anciennes questions/réponses).", "You are preparing a brainstorming assistant's reply; it has access to the user's personal database (PDFs read, highlighted passages, flashcards, past questions/answers).")}
{_t("Décide s'il serait utile de chercher dans cette base AVANT de répondre au dernier message.", "Decide whether searching that database BEFORE answering the last message would help.")}

{_t("Contexte récent", "Recent context")} :
{hist}

{_t("Dernier message de l'utilisateur", "User's last message")} :
{(user_message or "")[:600]}

{_t("Réponds UNIQUEMENT en JSON, sans markdown", "Respond ONLY in JSON, no markdown")} :
{{"search": true, "queries": ["{_t("mots-clés ciblés", "targeted keywords")}", "..."]}}

{_t("Règles", "Rules")} :
- search=true {_t("seulement si le sujet peut faire écho à ce que l'utilisateur a déjà lu/noté", "only if the topic may echo something the user has already read/noted")}.
- {_t("1 à 3 requêtes courtes (mots-clés), pas de phrases. Si search=false, queries=[].", "1 to 3 short keyword queries, not sentences. If search=false, queries=[].")}"""


def build_brainstorm_answer_prompt(
    summary: str,
    history: list[dict] | None,
    user_message: str,
    sources: list[dict] | None,
) -> str:
    """Réponse conversationnelle (texte libre) : mémoire de la discussion + sources DB citées."""
    summary_block = (summary or "").strip() or _t("(aucun, discussion récente)", "(none, recent discussion)")
    hist = _brainstorm_history_block(history)
    src = _brainstorm_sources_block(sources)
    return f"""{_t("Tu es Gemma, partenaire de brainstorming de l'utilisateur dans MetaC-App. Tu discutes librement, comme un assistant conversationnel, mais tu as un atout : l'accès à la base personnelle de l'utilisateur.", "You are Gemma, the user's brainstorming partner in MetaC-App. You chat freely, like a conversational assistant, but with an edge: access to the user's personal database.")}

{_t("Mémoire de la discussion (résumé des échanges précédents)", "Discussion memory (summary of earlier exchanges)")} :
{summary_block}

{_t("Messages récents", "Recent messages")} :
{hist}

{_t("Extraits trouvés dans la base de l'utilisateur (PDFs, surlignages, flashcards, anciennes Q&R)", "Excerpts found in the user's database (PDFs, highlights, flashcards, past Q&A)")} :
{src}

{_t("Nouveau message de l'utilisateur", "User's new message")} :
---
{(user_message or "")[:1500]}
---

{_t("Réponds en texte clair (markdown léger autorisé), en français, comme dans une conversation.", "Reply in clear text (light markdown allowed), conversationally.")}
{_t("Consignes", "Guidelines")} :
- {_t("Quand un extrait ci-dessus est pertinent, mentionne-le NATURELLEMENT : « on en a déjà croisé l'idée dans <document> » ou « tu avais surligné ce passage : … ». Ne cite JAMAIS un extrait absent de la liste.", "When an excerpt above is relevant, mention it NATURALLY: 'we already touched on this in <document>' or 'you highlighted this passage: …'. NEVER cite an excerpt that is not in the list.")}
- {_t("Si la base n'apporte rien, réponds normalement avec tes connaissances, sans le signaler.", "If the database adds nothing, just answer normally from your knowledge, without pointing it out.")}
- {_t("Sois un vrai partenaire de réflexion : propose des angles, des questions, des pistes, pas seulement un résumé.", "Be a real thinking partner: offer angles, questions, leads — not just a summary.")}
- {_t("Reste concis et vivant ; structure si utile, mais évite les pavés.", "Stay concise and lively; structure when useful, but avoid walls of text.")}"""


def build_brainstorm_summary_prompt(previous_summary: str, new_messages: list[dict] | None) -> str:
    """Met à jour le résumé glissant d'une discussion (mémoire longue compactée)."""
    prev = (previous_summary or "").strip() or _t("(aucun)", "(none)")
    lines: list[str] = []
    for item in (new_messages or []):
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        who = _t("Utilisateur", "User") if role == "user" else "Gemma"
        lines.append(f"{who} : {content[:600]}")
    block = "\n".join(lines) if lines else _t("(aucun nouveau message)", "(no new messages)")
    return f"""{_t("Tu maintiens la mémoire d'une discussion de brainstorming. Mets à jour le résumé en intégrant les nouveaux messages.", "You maintain the memory of a brainstorming discussion. Update the summary by integrating the new messages.")}

{_t("Résumé actuel", "Current summary")} :
{prev}

{_t("Nouveaux messages", "New messages")} :
{block}

{_t("Produis un résumé MIS À JOUR, en texte simple (pas de markdown, pas de JSON), 4 à 8 phrases.", "Produce an UPDATED summary, plain text (no markdown, no JSON), 4 to 8 sentences.")}
{_t("Garde les idées clés, décisions, pistes ouvertes et le fil du raisonnement. Pas de méta-commentaire, juste le résumé.", "Keep the key ideas, decisions, open leads and the thread of reasoning. No meta-commentary, just the summary.")}"""
