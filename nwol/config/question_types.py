# config/question_types.py — Registre canonique des types de questions.
#
# SOURCE DE VÉRITÉ UNIQUE. La grille était auparavant recopiée à huit endroits
# (guide FR, guide EN, QUESTION_TYPES, alias de parsing, jauges cibles,
# dimensions d'évaluation, énumérations littérales des prompts, liste du prompt
# de réparation) : un oubli ne levait aucune erreur, `parse_question` retombait
# silencieusement sur "qcm"/"open". Tout consommateur lit désormais ce module.
#
# Ajouter un type = ajouter UNE entrée ici (+ son libellé i18n côté frontend,
# vérifié par tests/test_question_types.py).
from __future__ import annotations

from dataclasses import dataclass

# Widgets de réponse côté UI (miroir de frontend/src/features/questions/registry.ts).
WIDGET_CHOICES = "choices"      # boutons de choix (QCM)
WIDGET_TEXT = "text"            # zone de texte libre
WIDGET_ORDERING = "ordering"    # liste à réordonner (drag & drop)


@dataclass(frozen=True)
class QuestionTypeSpec:
    """Tout ce qu'un type de question implique, en un seul endroit.

    `label`/`purpose`/`example`/`prefer_rule` sont des couples (fr, en) : le
    registre est appelé depuis `config/`, il ne peut pas dépendre de `i18n`.
    """

    key: str
    label: tuple[str, str]
    purpose: tuple[str, str]
    example: tuple[str, str]
    prefer_rule: tuple[str, str]
    target_gauges: tuple[str, ...]   # clés de db.metacog.CRITERIA
    # Poids de départ du tirage pondéré. UNIFORME (1.0) pour tous les types :
    # aucun n'est privilégié par principe, seuls le contenu du paragraphe et les
    # jauges de la session font ensuite pencher la balance (llm/prompts.py).
    base_weight: float
    widget: str
    eval_dimension_hint: bool = True  # False -> signal piloté par le verdict
    flashcard_eligible: bool = True
    quiz_eligible: bool = True
    # Réponse assez courte et factuelle pour qu'un QCM soit fabriqué autour d'elle
    # (distracteurs LLM du quiz). Faux pour les productions longues : en faire un
    # QCM trahirait l'intention du type.
    quiz_mcq_convertible: bool = False
    aliases: tuple[str, ...] = ()


QUESTION_TYPE_SPECS: tuple[QuestionTypeSpec, ...] = (
    QuestionTypeSpec(
        key="qcm",
        label=("QCM", "MCQ"),
        purpose=(
            "vérification rapide de compréhension factuelle",
            "quick factual comprehension check",
        ),
        example=(
            "Choisis la bonne proposition parmi 3 ou 4 réponses.",
            "Choose the correct answer from 3 or 4 options.",
        ),
        prefer_rule=(
            "Pour une définition ou un fait dense, privilégie \"qcm\" ou \"comprehension\".",
            "For a definition or dense fact, prefer \"qcm\" or \"comprehension\".",
        ),
        target_gauges=("retention", "attention"),
        base_weight=1.0,
        widget=WIDGET_CHOICES,
        quiz_mcq_convertible=True,
        aliases=("mcq", "multiple_choice", "qcm_verification_rapide_de_comprehension"),
    ),
    QuestionTypeSpec(
        key="open",
        label=("Question ouverte", "Open question"),
        purpose=(
            "expression libre, reformulation personnelle",
            "free expression, personal reformulation",
        ),
        example=(
            "Résume en une phrase l'idée principale du passage.",
            "Summarize the main idea of the passage in one sentence.",
        ),
        prefer_rule=(
            "Pour une idée centrale à reformuler, privilégie \"open\".",
            "For a central idea to reformulate, prefer \"open\".",
        ),
        target_gauges=("context_comprehension", "creativity"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        # Type par défaut (et repli des questions d'avant la grille typée) : sa
        # réponse est une phrase courte, le quiz sait en faire un QCM.
        quiz_mcq_convertible=True,
        aliases=("question_ouverte", "ouverte", "open_question", "reformulation"),
    ),
    QuestionTypeSpec(
        key="comprehension",
        label=("Question de compréhension textuelle", "Reading comprehension"),
        purpose=(
            "extraction d'une information explicitement donnée",
            "extraction of explicitly stated information",
        ),
        example=(
            "Quelle définition est donnée pour cette notion ?",
            "What definition is given for this concept?",
        ),
        prefer_rule=(
            "Pour retrouver une information explicite du texte, privilégie \"comprehension\".",
            "To retrieve information explicitly stated in the text, prefer \"comprehension\".",
        ),
        target_gauges=("context_comprehension",),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        quiz_mcq_convertible=True,
        aliases=(
            "question_de_comprehension",
            "question_de_comprehension_textuelle",
            "comprehension_textuelle",
            "textual_comprehension",
        ),
    ),
    QuestionTypeSpec(
        key="application",
        label=("Question d'application", "Application question"),
        purpose=(
            "mise en pratique sur un calcul, un exemple numérique ou un cas particulier",
            "practice on a calculation, numerical example, or specific case",
        ),
        example=(
            "Applique la relation du passage à ce petit cas.",
            "Apply the formula from the passage to this small case.",
        ),
        prefer_rule=(
            "Pour une formule, un calcul, un exemple, un tableau ou un cas particulier,"
            " privilégie \"application\".",
            "For a formula, calculation, example, table, or specific case,"
            " prefer \"application\".",
        ),
        target_gauges=("context_comprehension", "retention"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        quiz_mcq_convertible=True,
        aliases=(
            "question_d_application",
            "question_application",
            "application_question",
            "mise_en_pratique",
        ),
    ),
    QuestionTypeSpec(
        key="curiosity",
        label=("Question de curiosité / inductive", "Curiosity / inductive question"),
        purpose=(
            "création d'un déséquilibre cognitif qui pousse à chercher le pourquoi",
            "creating cognitive imbalance to push the learner to seek the why",
        ),
        example=(
            "T'es-tu déjà demandé comment cette idée peut rester vraie dans ce cas ?",
            "Have you ever wondered how this idea can hold true in this case?",
        ),
        prefer_rule=(
            "Pour provoquer une intuition ou une hypothèse à partir du paragraphe,"
            " privilégie \"curiosity\".",
            "To provoke an intuition or hypothesis from the paragraph, prefer \"curiosity\".",
        ),
        target_gauges=("curiosity",),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        aliases=(
            "question_de_curiosite",
            "question_de_curiosite_inductive",
            "curiosite",
            "curiosite_inductive",
            "inductive",
            "question_inductive",
        ),
    ),
    QuestionTypeSpec(
        key="visualization",
        label=("Exercice de visualisation", "Visualization exercise"),
        purpose=(
            "vision dans l'espace, schéma mental, représentation d'un mécanisme",
            "spatial vision, mental diagram, representation of a mechanism",
        ),
        example=(
            "Trace mentalement la situation : que vois-tu changer ?",
            "Mentally trace the situation: what do you see changing?",
        ),
        prefer_rule=(
            "Pour une figure, un schéma, une relation spatiale ou un processus à se représenter,"
            " privilégie \"visualization\".",
            "For a figure, diagram, spatial relation, or process to visualize,"
            " prefer \"visualization\".",
        ),
        target_gauges=("creativity", "context_comprehension"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        aliases=("visualisation", "exercice_de_visualisation", "visualization_exercise"),
    ),
    QuestionTypeSpec(
        key="metacognition",
        label=("Question métacognitive", "Metacognitive question"),
        purpose=(
            "prise de conscience du raisonnement utilisé",
            "awareness of the reasoning process used",
        ),
        example=(
            "Comment as-tu trouvé ta réponse ? Qu'as-tu modifié dans ton raisonnement ?",
            "How did you arrive at your answer? What did you adjust in your reasoning?",
        ),
        prefer_rule=(
            "Pour faire expliciter la stratégie de réponse, privilégie \"metacognition\".",
            "To make the student articulate their reasoning strategy, prefer \"metacognition\".",
        ),
        target_gauges=("meta_cognition",),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        eval_dimension_hint=False,
        flashcard_eligible=False,
        quiz_eligible=False,
        aliases=(
            "meta_cognition",
            "question_metacognitive",
            "metacognitive",
            "metacognitive_question",
        ),
    ),
    QuestionTypeSpec(
        key="anticipation",
        label=("Anticipation / auto-évaluation", "Anticipation / self-assessment"),
        purpose=(
            "surveillance de la compréhension et repérage des difficultés possibles",
            "monitoring comprehension and spotting possible difficulties ahead",
        ),
        example=(
            "Qu'est-ce qui pourrait te poser problème ici ?",
            "What might be challenging for you here?",
        ),
        prefer_rule=(
            "Pour faire repérer à l'avance une difficulté, une incertitude ou un risque d'erreur,"
            " privilégie \"anticipation\".",
            "To anticipate a difficulty, uncertainty, or risk of error, prefer \"anticipation\".",
        ),
        target_gauges=("meta_cognition", "attention"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        eval_dimension_hint=False,
        flashcard_eligible=False,
        quiz_eligible=False,
        aliases=(
            "anticipation_auto_evaluation",
            "auto_evaluation",
            "self_evaluation",
            "question_d_anticipation",
        ),
    ),
    # ── Types ajoutés : rappel, attention, séquence, production contrainte ──
    QuestionTypeSpec(
        key="recall",
        label=("Rappel libre", "Free recall"),
        purpose=(
            "restitution de mémoire, passage masqué dans la page",
            "recall from memory, with the passage hidden in the page",
        ),
        example=(
            "Sans relire le passage masqué, redonne les trois éléments qu'il énonce.",
            "Without rereading the hidden passage, list the three elements it states.",
        ),
        prefer_rule=(
            "Pour faire restituer de mémoire un passage court et dense, privilégie \"recall\""
            " (et renseigne alors paragraph_mask).",
            "To make the student recall a short dense passage from memory, prefer \"recall\""
            " (and then fill in paragraph_mask).",
        ),
        target_gauges=("retention", "attention"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        aliases=("rappel", "rappel_libre", "free_recall", "recall_libre", "restitution"),
    ),
    QuestionTypeSpec(
        key="error_detection",
        label=("Repérage d'erreur", "Error spotting"),
        purpose=(
            "détection et correction d'une affirmation volontairement fausse",
            "detecting and correcting a deliberately wrong statement",
        ),
        example=(
            "Une chose est fausse dans cette reformulation : laquelle, et que faut-il écrire ?",
            "One thing is wrong in this restatement: which one, and what should it say?",
        ),
        prefer_rule=(
            "Pour réveiller l'attention ou vérifier une lecture fine, privilégie"
            " \"error_detection\" : énonce une reformulation contenant UNE erreur subtile"
            " (signe inversé, condition retirée, cause et effet permutés).",
            "To wake up attention or check close reading, prefer \"error_detection\":"
            " state a restatement containing ONE subtle error (inverted sign, dropped"
            " condition, swapped cause and effect).",
        ),
        target_gauges=("attention", "context_comprehension"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        aliases=(
            "detection_d_erreur",
            "reperage_d_erreur",
            "erreur_volontaire",
            "spot_the_error",
            "error_spotting",
        ),
    ),
    QuestionTypeSpec(
        key="ordering",
        label=("Remise en ordre", "Reordering"),
        purpose=(
            "reconstitution de l'ordre d'un processus, d'une démonstration ou d'une chronologie",
            "reconstructing the order of a process, a proof, or a timeline",
        ),
        example=(
            "Remets les étapes de ce mécanisme dans l'ordre du passage.",
            "Put the steps of this mechanism back into the order given by the passage.",
        ),
        prefer_rule=(
            "Pour un enchaînement d'étapes, une chronologie ou une démonstration,"
            " privilégie \"ordering\" et donne dans choices les 3 à 6 étapes DANS L'ORDRE CORRECT"
            " (l'interface les mélangera).",
            "For a sequence of steps, a timeline, or a proof, prefer \"ordering\" and give in"
            " choices the 3 to 6 steps IN THE CORRECT ORDER (the interface will shuffle them).",
        ),
        target_gauges=("retention", "context_comprehension"),
        base_weight=1.0,
        widget=WIDGET_ORDERING,
        aliases=("remise_en_ordre", "ordre", "sequencing", "reordering", "chronologie"),
    ),
    QuestionTypeSpec(
        key="teach_back",
        label=("Explication à un débutant", "Explain it back"),
        purpose=(
            "reformulation sans jargon, comme à quelqu'un qui découvre la notion",
            "jargon-free reformulation, as if to someone discovering the notion",
        ),
        example=(
            "Explique cette notion en deux phrases à quelqu'un qui ne l'a jamais vue,"
            " sans employer le mot « dérivée ».",
            "Explain this notion in two sentences to someone who has never seen it,"
            " without using the word \"derivative\".",
        ),
        prefer_rule=(
            "Pour forcer une compréhension profonde d'une notion technique, privilégie"
            " \"teach_back\" : impose une contrainte explicite (deux phrases, un mot interdit).",
            "To force deep understanding of a technical notion, prefer \"teach_back\":"
            " impose an explicit constraint (two sentences, one banned word).",
        ),
        target_gauges=("context_comprehension", "meta_cognition"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        aliases=("explication", "feynman", "explain_back", "teach_it_back", "vulgarisation"),
    ),
    QuestionTypeSpec(
        key="elaboration_why",
        label=("Pourquoi c'est vrai", "Why is it true"),
        purpose=(
            "justification élaborative : pourquoi cela plutôt que l'inverse",
            "elaborative justification: why this rather than the opposite",
        ),
        example=(
            "Pourquoi cette condition est-elle nécessaire, plutôt que l'inverse ?",
            "Why is this condition necessary, rather than the opposite?",
        ),
        prefer_rule=(
            "Pour faire justifier un fait par le mécanisme qui le rend vrai, privilégie"
            " \"elaboration_why\" : la justification doit être entièrement dans le passage.",
            "To make the student justify a fact by the mechanism that makes it true, prefer"
            " \"elaboration_why\": the justification must be entirely within the passage.",
        ),
        target_gauges=("context_comprehension", "retention"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        aliases=(
            "elaboration",
            "pourquoi",
            "interrogation_elaborative",
            "elaborative_interrogation",
            "why",
        ),
    ),
    QuestionTypeSpec(
        key="connection",
        label=("Mise en lien", "Connection"),
        purpose=(
            "rattachement de la notion à ce qui a déjà été lu ou travaillé",
            "linking the notion to what has already been read or practised",
        ),
        example=(
            "À quoi cette notion se relie-t-elle dans ce que tu as déjà lu ?",
            "What does this notion connect to in what you have already read?",
        ),
        prefer_rule=(
            "Pour rattacher le paragraphe à une réponse antérieure, une difficulté passée ou"
            " un passage retrouvé ailleurs dans le document, privilégie \"connection\".",
            "To connect the paragraph to a previous answer, a past struggle, or a passage found"
            " elsewhere in the document, prefer \"connection\".",
        ),
        target_gauges=("retention", "meta_cognition"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        quiz_eligible=False,
        aliases=("mise_en_lien", "lien", "transfert", "linking", "connexion"),
    ),
    QuestionTypeSpec(
        key="counterexample",
        label=("Limites et contre-exemple", "Limits and counterexample"),
        purpose=(
            "repérage des conditions de validité et du cas qui casse l'énoncé",
            "spotting validity conditions and the case that breaks the statement",
        ),
        example=(
            "Cette affirmation reste-t-elle vraie si on retire cette hypothèse ?"
            " Donne un contre-exemple.",
            "Does this statement still hold if we drop this hypothesis? Give a counterexample.",
        ),
        prefer_rule=(
            "Pour faire délimiter le domaine de validité d'un énoncé, privilégie"
            " \"counterexample\" : la condition à retirer doit figurer dans le passage.",
            "To make the student delimit a statement's validity range, prefer"
            " \"counterexample\": the condition to drop must appear in the passage.",
        ),
        target_gauges=("creativity", "context_comprehension"),
        base_weight=1.0,
        widget=WIDGET_TEXT,
        aliases=("contre_exemple", "contre_exemples", "limites", "counter_example"),
    ),
    QuestionTypeSpec(
        key="estimation",
        label=("Ordre de grandeur", "Order of magnitude"),
        purpose=(
            "intuition chiffrée avant le calcul exact",
            "numerical intuition before the exact calculation",
        ),
        example=(
            "Avant de calculer : le résultat sera-t-il plutôt de l'ordre de $10^3$ ou de $10^6$ ?",
            "Before computing: will the result be closer to $10^3$ or to $10^6$?",
        ),
        prefer_rule=(
            "Pour faire estimer avant de calculer, privilégie \"estimation\" ; tu peux proposer"
            " 3 ou 4 ordres de grandeur dans choices, ou laisser la réponse libre.",
            "To make the student estimate before computing, prefer \"estimation\"; you may offer"
            " 3 or 4 orders of magnitude in choices, or leave the answer free.",
        ),
        target_gauges=("curiosity", "context_comprehension"),
        base_weight=1.0,
        widget=WIDGET_CHOICES,
        quiz_mcq_convertible=True,
        aliases=("ordre_de_grandeur", "estimate", "order_of_magnitude", "approximation"),
    ),
)

KEYS: tuple[str, ...] = tuple(spec.key for spec in QUESTION_TYPE_SPECS)

_BY_KEY: dict[str, QuestionTypeSpec] = {spec.key: spec for spec in QUESTION_TYPE_SPECS}

# Types dont le `choices` du LLM est signifiant. Partout ailleurs il est vidé :
# gemma4 en émet spontanément même pour une question ouverte.
_CHOICE_BOUNDS: dict[str, tuple[int, int]] = {
    "qcm": (3, 4),
    "ordering": (3, 6),
    "estimation": (3, 4),
}


def _index(lang: str) -> int:
    return 1 if lang == "en" else 0


def spec(key: str) -> QuestionTypeSpec | None:
    return _BY_KEY.get(key)


def guide_rows(lang: str) -> tuple[tuple[str, str, str, str], ...]:
    """Lignes (clé, libellé, but, exemple) du guide injecté dans le prompt."""
    i = _index(lang)
    return tuple(
        (s.key, s.label[i], s.purpose[i], s.example[i]) for s in QUESTION_TYPE_SPECS
    )


def prefer_rules(lang: str) -> tuple[str, ...]:
    i = _index(lang)
    return tuple(s.prefer_rule[i] for s in QUESTION_TYPE_SPECS)


def json_enum(lang: str) -> str:
    """`"qcm" ou "open" ou …` — valeur autorisée du champ question_type."""
    joiner = " or " if lang == "en" else " ou "
    return joiner.join(f'"{key}"' for key in KEYS)


def keys_line() -> str:
    """`qcm, open, …` — liste compacte pour les consignes de format."""
    return ", ".join(KEYS)


def base_weights() -> dict[str, float]:
    return {s.key: s.base_weight for s in QUESTION_TYPE_SPECS}


def target_gauges_map() -> dict[str, tuple[str, ...]]:
    return {s.key: s.target_gauges for s in QUESTION_TYPE_SPECS}


def eval_dimensions_map() -> dict[str, tuple[str, ...]]:
    """Dimensions à marquer dans metacog_signals, hors types pilotés par le verdict."""
    return {
        s.key: s.target_gauges for s in QUESTION_TYPE_SPECS if s.eval_dimension_hint
    }


def alias_map() -> dict[str, str]:
    return {alias: s.key for s in QUESTION_TYPE_SPECS for alias in s.aliases}


def widget(key: str) -> str:
    found = _BY_KEY.get(key)
    return found.widget if found else WIDGET_TEXT


def allows_choices(key: str) -> bool:
    return key in _CHOICE_BOUNDS


def choice_bounds(key: str) -> tuple[int, int]:
    """(min, max) de `choices` pour un type qui en accepte. (0, 0) sinon."""
    return _CHOICE_BOUNDS.get(key, (0, 0))


def requires_choices(key: str) -> bool:
    """`ordering` sans items n'est pas rejouable : la question est alors rejetée."""
    return key == "ordering"


def flashcard_eligible(key: str) -> bool:
    found = _BY_KEY.get(key)
    return found.flashcard_eligible if found else True


def quiz_excluded_keys() -> tuple[str, ...]:
    """Types réflexifs contextuels : sans objet hors de la lecture en cours."""
    return tuple(s.key for s in QUESTION_TYPE_SPECS if not s.quiz_eligible)


def quiz_mcq_convertible(key: str) -> bool:
    found = _BY_KEY.get(key)
    # Type inconnu (question d'avant l'ajout du champ) : on garde l'ancien
    # comportement, la question part au générateur de distracteurs.
    return found.quiz_mcq_convertible if found else True
