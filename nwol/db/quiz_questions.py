# db/quiz_questions.py — Questions statiques du quizz de niveau + sélection adaptative
from __future__ import annotations

import json
import logging
from db import get_connection

logger = logging.getLogger("DB.quiz")

_GENERIC_QUESTION_FRAGMENTS: tuple[str, ...] = (
    "la relation ou les données du passage",
    "les données du passage à un cas",
    "du passage à un cas simple",
    "appliquerais-tu la relation",
)

# Phrases qui référencent un contexte de lecture absent dans le quiz
_CONTEXT_REF_PHRASES: tuple[str, ...] = (
    "selon le passage",
    "d'après le passage",
    "dans ce passage",
    "dans le passage",
    "selon ce texte",
    "d'après ce texte",
    "d'après le paragraphe",
    "dans ce paragraphe",
    "selon le texte",
)


def _is_unusable_for_quiz(question_text: str, source_context: str | None = None) -> bool:
    t = (question_text or "").lower()
    if any(frag in t for frag in _GENERIC_QUESTION_FRAGMENTS):
        return True
    if not (source_context or "").strip() and any(phrase in t for phrase in _CONTEXT_REF_PHRASES):
        return True
    return False

_STATIC_QUESTIONS: list[dict] = [
    # Sciences
    {
        "question": "Quelle est la formule chimique de l'eau ?",
        "choices": ["H₂O", "CO₂", "NaCl", "O₂"],
        "answer": "H₂O",
        "category": "sciences",
        "difficulty": 1,
    },
    {
        "question": "Quelle est la vitesse de la lumière dans le vide (approximation) ?",
        "choices": ["3×10⁸ m/s", "3×10⁶ m/s", "3×10¹⁰ m/s", "1×10⁸ m/s"],
        "answer": "3×10⁸ m/s",
        "category": "sciences",
        "difficulty": 1,
    },
    {
        "question": "Quel est l'élément chimique de symbole Fe ?",
        "choices": ["Fer", "Fluor", "Francium", "Fermium"],
        "answer": "Fer",
        "category": "sciences",
        "difficulty": 1,
    },
    {
        "question": "Combien de protons contient un atome de carbone ?",
        "choices": ["6", "12", "4", "8"],
        "answer": "6",
        "category": "sciences",
        "difficulty": 2,
    },
    {
        "question": "Quelle force maintient les planètes en orbite autour du Soleil ?",
        "choices": ["La gravitation", "L'électromagnétisme", "La force nucléaire forte", "La pression solaire"],
        "answer": "La gravitation",
        "category": "sciences",
        "difficulty": 1,
    },
    {
        "question": "Quel est l'ADN ? (développer l'acronyme)",
        "choices": ["Acide DésoxyriboNucléique", "Acide DiazoteNucléaire", "Acide DésoxyNitrogenique", "Acide DiNitroAminé"],
        "answer": "Acide DésoxyriboNucléique",
        "category": "sciences",
        "difficulty": 2,
    },
    # Mathématiques
    {
        "question": "Quelle est la valeur de π arrondie à deux décimales ?",
        "choices": ["3,14", "3,12", "3,16", "3,18"],
        "answer": "3,14",
        "category": "mathématiques",
        "difficulty": 1,
    },
    {
        "question": "Quel est le résultat de 2¹⁰ ?",
        "choices": ["1024", "512", "2048", "256"],
        "answer": "1024",
        "category": "mathématiques",
        "difficulty": 2,
    },
    {
        "question": "Si f(x) = x², quelle est la dérivée f'(x) ?",
        "choices": ["2x", "x²", "x/2", "2"],
        "answer": "2x",
        "category": "mathématiques",
        "difficulty": 2,
    },
    {
        "question": "Combien y a-t-il de nombres premiers inférieurs à 10 ?",
        "choices": ["4", "3", "5", "6"],
        "answer": "4",
        "category": "mathématiques",
        "difficulty": 2,
    },
    {
        "question": "Quel est le théorème fondamental du calcul intégral-différentiel ?",
        "choices": ["Théorème de Newton-Leibniz", "Théorème de Pythagore", "Théorème de Bayes", "Théorème de Fermat"],
        "answer": "Théorème de Newton-Leibniz",
        "category": "mathématiques",
        "difficulty": 3,
    },
    # Histoire
    {
        "question": "En quelle année a eu lieu la Révolution française ?",
        "choices": ["1789", "1776", "1804", "1815"],
        "answer": "1789",
        "category": "histoire",
        "difficulty": 1,
    },
    {
        "question": "Qui a découvert l'Amérique en 1492 ?",
        "choices": ["Christophe Colomb", "Vasco de Gama", "Magellan", "Amerigo Vespucci"],
        "answer": "Christophe Colomb",
        "category": "histoire",
        "difficulty": 1,
    },
    {
        "question": "Quelle guerre s'est terminée en 1918 ?",
        "choices": ["Première Guerre mondiale", "Seconde Guerre mondiale", "Guerre de Crimée", "Guerre de Sécession"],
        "answer": "Première Guerre mondiale",
        "category": "histoire",
        "difficulty": 1,
    },
    {
        "question": "Qui était le premier président de la Ve République française ?",
        "choices": ["Charles de Gaulle", "Georges Pompidou", "Valéry Giscard d'Estaing", "François Mitterrand"],
        "answer": "Charles de Gaulle",
        "category": "histoire",
        "difficulty": 2,
    },
    # Géographie
    {
        "question": "Quelle est la capitale de l'Australie ?",
        "choices": ["Canberra", "Sydney", "Melbourne", "Brisbane"],
        "answer": "Canberra",
        "category": "géographie",
        "difficulty": 2,
    },
    {
        "question": "Quel est le plus long fleuve du monde ?",
        "choices": ["Le Nil", "L'Amazone", "Le Yangtsé", "Le Mississippi"],
        "answer": "Le Nil",
        "category": "géographie",
        "difficulty": 2,
    },
    {
        "question": "Sur quel continent se trouve le désert du Sahara ?",
        "choices": ["Afrique", "Asie", "Amérique du Sud", "Australie"],
        "answer": "Afrique",
        "category": "géographie",
        "difficulty": 1,
    },
    # Langue française
    {
        "question": "Quel est l'homonyme du mot « saut » ?",
        "choices": ["seau", "sot", "sceau", "Les trois"],
        "answer": "Les trois",
        "category": "français",
        "difficulty": 2,
    },
    {
        "question": "De quel auteur est l'œuvre « Les Misérables » ?",
        "choices": ["Victor Hugo", "Émile Zola", "Gustave Flaubert", "Alexandre Dumas"],
        "answer": "Victor Hugo",
        "category": "français",
        "difficulty": 1,
    },
    {
        "question": "Quelle figure de style consiste à comparer deux éléments avec « comme » ou « tel » ?",
        "choices": ["La comparaison", "La métaphore", "L'allégorie", "La métonymie"],
        "answer": "La comparaison",
        "category": "français",
        "difficulty": 2,
    },
    # Informatique
    {
        "question": "Que signifie l'acronyme HTTP ?",
        "choices": ["HyperText Transfer Protocol", "High Transfer Text Program", "Hyper Tool Transfer Process", "HyperText Transmission Path"],
        "answer": "HyperText Transfer Protocol",
        "category": "informatique",
        "difficulty": 1,
    },
    {
        "question": "Combien de bits contient un octet ?",
        "choices": ["8", "4", "16", "32"],
        "answer": "8",
        "category": "informatique",
        "difficulty": 1,
    },
    {
        "question": "Quel langage de programmation a été créé par Guido van Rossum ?",
        "choices": ["Python", "Java", "C++", "Ruby"],
        "answer": "Python",
        "category": "informatique",
        "difficulty": 1,
    },
    {
        "question": "Que fait la commande git commit ?",
        "choices": [
            "Enregistre les modifications dans l'historique local",
            "Envoie les modifications sur le serveur distant",
            "Crée une nouvelle branche",
            "Fusionne deux branches",
        ],
        "answer": "Enregistre les modifications dans l'historique local",
        "category": "informatique",
        "difficulty": 2,
    },
]


def seed_static_questions() -> None:
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) FROM quiz_static_questions").fetchone()
    if row[0] > 0:
        return
    with conn:
        for q in _STATIC_QUESTIONS:
            conn.execute(
                """INSERT INTO quiz_static_questions (question, choices_json, answer, category, difficulty)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    q["question"],
                    json.dumps(q.get("choices"), ensure_ascii=False) if q.get("choices") else None,
                    q["answer"],
                    q.get("category", "culture"),
                    q.get("difficulty", 2),
                ),
            )
    logger.info("Questions statiques seedées (%d questions)", len(_STATIC_QUESTIONS))


def get_quiz_questions(user_id: int = 1, n: int = 10, subject: str | None = None) -> list[dict]:
    """Retourne n questions pour le quizz : d'abord les questions de lecture (non-correct),
    complétées par des questions statiques si nécessaire.
    Si subject est fourni, filtre uniquement les questions de cette matière."""
    conn = get_connection()
    results: list[dict] = []

    # 1. Questions issues des lectures où l'utilisateur a eu des difficultés
    if subject:
        rows = conn.execute(
            """
            SELECT DISTINCT q.id, q.question, q.choices_json, q.answer, q.question_type,
                   q.source_context, q.scope_label, q.page_start, q.page_end,
                   COALESCE(d.filename, '') AS document_title,
                   COALESCE(d.subject, '') AS subject,
                   COALESCE(c.title, '') AS chapter_title
            FROM questions q
            LEFT JOIN documents d ON d.id = q.document_id
            LEFT JOIN chapters c ON c.id = q.chapter_id
            JOIN answers a ON a.question_id = q.id AND a.user_id = ?
            WHERE a.verdict IN ('incorrect', 'partial')
              AND LOWER(COALESCE(d.subject, '')) = LOWER(?)
            ORDER BY a.answered_at DESC
            LIMIT ?
            """,
            (user_id, subject, n),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT DISTINCT q.id, q.question, q.choices_json, q.answer, q.question_type,
                   q.source_context, q.scope_label, q.page_start, q.page_end,
                   COALESCE(d.filename, '') AS document_title,
                   COALESCE(d.subject, '') AS subject,
                   COALESCE(c.title, '') AS chapter_title
            FROM questions q
            LEFT JOIN documents d ON d.id = q.document_id
            LEFT JOIN chapters c ON c.id = q.chapter_id
            JOIN answers a ON a.question_id = q.id AND a.user_id = ?
            WHERE a.verdict IN ('incorrect', 'partial')
            ORDER BY a.answered_at DESC
            LIMIT ?
            """,
            (user_id, n),
        ).fetchall()

    seen_ids: set[int] = set()
    for row in rows:
        (
            qid, question, choices_json, answer, qtype, source_context,
            scope_label, page_start, page_end, document_title, row_subject,
            chapter_title,
        ) = row
        if qid in seen_ids:
            continue
        seen_ids.add(qid)
        if _is_unusable_for_quiz(question, source_context):
            continue
        choices = None
        if choices_json:
            try:
                choices = json.loads(choices_json)
            except Exception:
                choices = None
        course_context = _course_context_text(
            document_title=document_title,
            chapter_title=chapter_title,
            scope_label=scope_label,
            page_start=page_start,
            page_end=page_end,
            source_context=source_context,
        )
        results.append({
            "id": qid,
            "question": question,
            "choices": choices,
            "answer": answer,
            "question_type": qtype,
            "category": row_subject or "culture",
            "document": document_title or None,
            "chapter_title": chapter_title or None,
            "source_context": source_context or "",
            "course_context": course_context,
            "source": "reading",
        })

    # 2. Compléter avec des questions statiques
    if len(results) < n:
        needed = n - len(results)
        if subject:
            static_rows = conn.execute(
                """SELECT id, question, choices_json, answer, category
                   FROM quiz_static_questions
                   WHERE LOWER(category) = LOWER(?)
                   ORDER BY RANDOM()
                   LIMIT ?""",
                (subject, needed),
            ).fetchall()
        else:
            static_rows = conn.execute(
                """SELECT id, question, choices_json, answer, category
                   FROM quiz_static_questions
                   ORDER BY RANDOM()
                   LIMIT ?""",
                (needed,),
            ).fetchall()
        for row in static_rows:
            qid, question, choices_json, answer, category = row
            choices = None
            if choices_json:
                try:
                    choices = json.loads(choices_json)
                except Exception:
                    choices = None
            results.append({
                "id": qid,
                "question": question,
                "choices": choices,
                "answer": answer,
                "category": category or "culture",
                "source": "static",
            })

    results = [
        q for q in results
        if not _is_unusable_for_quiz(q.get("question", ""), q.get("source_context"))
    ]
    return results[:n]


def _course_context_text(
    document_title: str | None,
    chapter_title: str | None,
    scope_label: str | None,
    page_start,
    page_end,
    source_context: str | None,
) -> str:
    parts: list[str] = []
    if document_title:
        parts.append(f"Cours : {document_title}")
    if chapter_title:
        parts.append(f"Chapitre : {chapter_title}")
    elif scope_label:
        parts.append(f"Section : {scope_label}")
    page_label = _page_label(page_start, page_end)
    if page_label:
        parts.append(page_label)
    if source_context:
        parts.append(f"Extrait : {' '.join(str(source_context).split())[:900]}")
    return "\n".join(parts)


def _page_label(page_start, page_end) -> str:
    try:
        start = int(page_start)
    except (TypeError, ValueError):
        return ""
    try:
        end = int(page_end)
    except (TypeError, ValueError):
        end = start
    if end and end != start:
        return f"Pages : {start}-{end}"
    return f"Page : {start}"


def get_quiz_base_questions(
    user_id: int = 1, n: int = 10, subject: str | None = None
) -> list[dict]:
    """Questions de lecture (``scope_type='page'``) pour une session de quiz QCM.

    Contrairement à :func:`get_quiz_questions`, on prend **toutes** les questions
    de compréhension générées pendant les lectures (pas seulement celles ratées) et
    **sans** complément de questions statiques : le nombre de QCM suit le stock réel
    par thème (borné par ``n``). On priorise les questions déjà ratées puis les plus
    récentes. ``document_id`` est exposé pour permettre le deep-link vers le reader.
    """
    conn = get_connection()
    params: list = [user_id]
    where_subject = ""
    if subject:
        where_subject = "AND LOWER(COALESCE(d.subject, '')) = LOWER(?)"
        params.append(subject)
    params.append(n)
    rows = conn.execute(
        f"""
        SELECT q.id, q.question, q.choices_json, q.answer, q.question_type,
               q.source_context, q.scope_label, q.page_start, q.page_end,
               q.document_id,
               COALESCE(d.filename, '') AS document_title,
               COALESCE(d.subject, '')  AS subject,
               COALESCE(c.title, '')    AS chapter_title,
               MAX(CASE WHEN a.verdict IN ('incorrect', 'partial') THEN 1 ELSE 0 END) AS failed
        FROM questions q
        LEFT JOIN documents d ON d.id = q.document_id
        LEFT JOIN chapters c ON c.id = q.chapter_id
        LEFT JOIN answers a ON a.question_id = q.id AND a.user_id = ?
        WHERE q.scope_type = 'page'
          AND TRIM(COALESCE(q.question, '')) <> ''
          {where_subject}
        GROUP BY q.id
        ORDER BY failed DESC, q.created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        (
            qid, question, choices_json, answer, qtype, source_context,
            scope_label, page_start, page_end, document_id, document_title,
            row_subject, chapter_title, _failed,
        ) = row
        if _is_unusable_for_quiz(question, source_context):
            continue
        choices = None
        if choices_json:
            try:
                choices = json.loads(choices_json)
            except Exception:
                choices = None
        course_context = _course_context_text(
            document_title=document_title,
            chapter_title=chapter_title,
            scope_label=scope_label,
            page_start=page_start,
            page_end=page_end,
            source_context=source_context,
        )
        results.append({
            "id": qid,
            "question": question,
            "choices": choices,
            "answer": answer or "",
            "question_type": qtype,
            "category": row_subject or "culture",
            "document": document_title or None,
            "document_id": document_id,
            "chapter_title": chapter_title or None,
            "source_context": source_context or "",
            "course_context": course_context,
            "source": "reading",
        })
    return results


def get_quiz_subjects(user_id: int = 1) -> list[dict]:
    """Matières ayant des questions de lecture exploitables pour le quiz.

    Renvoie ``[{"subject": str, "count": int}]`` trié par effectif décroissant,
    pour ne proposer dans le sélecteur que des thèmes réellement disponibles.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT LOWER(COALESCE(d.subject, '')) AS subject,
               q.question, q.source_context
        FROM questions q
        LEFT JOIN documents d ON d.id = q.document_id
        WHERE q.scope_type = 'page'
          AND TRIM(COALESCE(q.question, '')) <> ''
          AND TRIM(COALESCE(d.subject, '')) <> ''
        """,
    ).fetchall()
    counts: dict[str, int] = {}
    for subject, question, source_context in rows:
        if _is_unusable_for_quiz(question, source_context):
            continue
        counts[subject] = counts.get(subject, 0) + 1
    return [
        {"subject": subject, "count": count}
        for subject, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
