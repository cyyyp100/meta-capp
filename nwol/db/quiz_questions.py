# db/quiz_questions.py — Questions statiques du quizz de niveau + sélection adaptative
from __future__ import annotations

import json
import logging

from config import question_types
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
    # ── Géographie : capitales (les pièges classiques, pas les évidences) ──
    {
        "question": "Quelle est la capitale du Canada ?",
        "choices": ["Ottawa", "Toronto", "Montréal", "Vancouver"],
        "answer": "Ottawa",
        "category": "géographie",
        "difficulty": 2,
    },
    {
        "question": "Quelle est la capitale du Brésil ?",
        "choices": ["Brasília", "Rio de Janeiro", "São Paulo", "Salvador"],
        "answer": "Brasília",
        "category": "géographie",
        "difficulty": 2,
    },
    {
        "question": "Quelle est la capitale de la Turquie ?",
        "choices": ["Ankara", "Istanbul", "Izmir", "Bursa"],
        "answer": "Ankara",
        "category": "géographie",
        "difficulty": 2,
    },
    {
        "question": "Quelle est la capitale de la Suisse ?",
        "choices": ["Berne", "Zurich", "Genève", "Bâle"],
        "answer": "Berne",
        "category": "géographie",
        "difficulty": 2,
    },
    {
        "question": "Quelle est la capitale du Maroc ?",
        "choices": ["Rabat", "Casablanca", "Marrakech", "Fès"],
        "answer": "Rabat",
        "category": "géographie",
        "difficulty": 2,
    },
    {
        "question": "Quelle est la capitale du Kazakhstan ?",
        "choices": ["Astana", "Almaty", "Bichkek", "Tachkent"],
        "answer": "Astana",
        "category": "géographie",
        "difficulty": 3,
    },
    {
        "question": "Quelle est la capitale de la Nouvelle-Zélande ?",
        "choices": ["Wellington", "Auckland", "Christchurch", "Dunedin"],
        "answer": "Wellington",
        "category": "géographie",
        "difficulty": 2,
    },
    {
        "question": "Quelle est la capitale du Nigéria ?",
        "choices": ["Abuja", "Lagos", "Kano", "Ibadan"],
        "answer": "Abuja",
        "category": "géographie",
        "difficulty": 3,
    },
    {
        "question": "Quelle est la capitale de l'Inde ?",
        "choices": ["New Delhi", "Bombay", "Calcutta", "Bangalore"],
        "answer": "New Delhi",
        "category": "géographie",
        "difficulty": 1,
    },
    {
        "question": "Quelle ville est le siège du gouvernement d'Afrique du Sud ?",
        "choices": ["Pretoria", "Le Cap", "Johannesburg", "Durban"],
        "answer": "Pretoria",
        "category": "géographie",
        "difficulty": 3,
    },
    # ── Histoire : dix dates repères ──────────────────────────────────────
    {
        "question": "En quelle année le mur de Berlin est-il tombé ?",
        "choices": ["1989", "1985", "1991", "1987"],
        "answer": "1989",
        "category": "histoire",
        "difficulty": 1,
    },
    {
        "question": "En quelle année a eu lieu le débarquement de Normandie ?",
        "choices": ["1944", "1942", "1943", "1945"],
        "answer": "1944",
        "category": "histoire",
        "difficulty": 1,
    },
    {
        "question": "En quelle année le traité de Versailles a-t-il été signé ?",
        "choices": ["1919", "1918", "1920", "1921"],
        "answer": "1919",
        "category": "histoire",
        "difficulty": 2,
    },
    {
        "question": "En quelle année les États-Unis ont-ils déclaré leur indépendance ?",
        "choices": ["1776", "1783", "1789", "1765"],
        "answer": "1776",
        "category": "histoire",
        "difficulty": 2,
    },
    {
        "question": "En quelle année Charlemagne a-t-il été couronné empereur ?",
        "choices": ["800", "768", "843", "987"],
        "answer": "800",
        "category": "histoire",
        "difficulty": 3,
    },
    {
        "question": "Vers quelle année Gutenberg a-t-il mis au point l'imprimerie à caractères mobiles ?",
        "choices": ["1450", "1350", "1550", "1650"],
        "answer": "1450",
        "category": "histoire",
        "difficulty": 3,
    },
    {
        "question": "En quelle année Constantinople est-elle tombée aux mains des Ottomans ?",
        "choices": ["1453", "1204", "1492", "1517"],
        "answer": "1453",
        "category": "histoire",
        "difficulty": 3,
    },
    {
        "question": "En quelle année l'Homme a-t-il marché sur la Lune pour la première fois ?",
        "choices": ["1969", "1961", "1965", "1972"],
        "answer": "1969",
        "category": "histoire",
        "difficulty": 1,
    },
    {
        "question": "En quelle année la Seconde Guerre mondiale s'est-elle terminée en Europe ?",
        "choices": ["1945", "1943", "1944", "1946"],
        "answer": "1945",
        "category": "histoire",
        "difficulty": 1,
    },
    {
        "question": "En quelle année a eu lieu la bataille de Hastings ?",
        "choices": ["1066", "987", "1099", "1215"],
        "answer": "1066",
        "category": "histoire",
        "difficulty": 3,
    },
    # ── Langues : vocabulaire anglais (dont quelques faux amis) ───────────
    {
        "question": "Que signifie le mot anglais « to achieve » ?",
        "choices": ["Accomplir", "Échouer", "Hériter", "Éviter"],
        "answer": "Accomplir",
        "category": "langues",
        "difficulty": 1,
    },
    {
        "question": "Que signifie le mot anglais « to borrow » ?",
        "choices": ["Emprunter", "Prêter", "Acheter", "Rendre"],
        "answer": "Emprunter",
        "category": "langues",
        "difficulty": 2,
    },
    {
        "question": "Que signifie le mot anglais « to gather » ?",
        "choices": ["Rassembler", "Disperser", "Oublier", "Réparer"],
        "answer": "Rassembler",
        "category": "langues",
        "difficulty": 2,
    },
    {
        "question": "Que signifie l'adjectif anglais « harmful » ?",
        "choices": ["Nuisible", "Utile", "Inoffensif", "Agréable"],
        "answer": "Nuisible",
        "category": "langues",
        "difficulty": 2,
    },
    {
        "question": "Que signifie l'adverbe anglais « actually » ?",
        "choices": ["En réalité", "Actuellement", "Activement", "Éventuellement"],
        "answer": "En réalité",
        "category": "langues",
        "difficulty": 2,
    },
    {
        "question": "Que signifie l'adverbe anglais « eventually » ?",
        "choices": ["Finalement", "Éventuellement", "Rarement", "Immédiatement"],
        "answer": "Finalement",
        "category": "langues",
        "difficulty": 3,
    },
    {
        "question": "Que signifie le verbe anglais « to attend » ?",
        "choices": ["Assister à", "Attendre", "Prétendre", "Tenter"],
        "answer": "Assister à",
        "category": "langues",
        "difficulty": 2,
    },
    {
        "question": "Que signifie le mot anglais « a library » ?",
        "choices": ["Une bibliothèque", "Une librairie", "Un magasin", "Un laboratoire"],
        "answer": "Une bibliothèque",
        "category": "langues",
        "difficulty": 1,
    },
    {
        "question": "Que signifie le mot anglais « weather » ?",
        "choices": ["Le temps qu'il fait", "Le temps qui passe", "Une tempête", "Un rassemblement"],
        "answer": "Le temps qu'il fait",
        "category": "langues",
        "difficulty": 1,
    },
    {
        "question": "Que signifie le verbe anglais « to spend » ?",
        "choices": ["Dépenser (ou passer du temps)", "Économiser", "Suspendre", "Envoyer"],
        "answer": "Dépenser (ou passer du temps)",
        "category": "langues",
        "difficulty": 2,
    },
]


# Les deux réservoirs de questions (`questions` de lecture et
# `quiz_static_questions`) numérotent chacun depuis 1. Une session de quiz qui
# mélange les deux se retrouvait donc avec deux questions de même id : clé React
# dupliquée côté UI, et distracteurs LLM attribués à la mauvaise question.
# L'offset rend l'id unique dans une session mixte.
STATIC_ID_OFFSET = 1_000_000


def seed_static_questions() -> None:
    """Insère les questions statiques manquantes (idempotent, énoncé par énoncé).

    On ne teste PAS « la table est-elle vide ? » : une base déjà installée n'aurait
    alors jamais reçu les questions ajoutées au catalogue après son installation.
    L'énoncé est la clé naturelle de ce catalogue figé.
    """
    conn = get_connection()
    known = {row[0] for row in conn.execute("SELECT question FROM quiz_static_questions")}
    missing = [q for q in _STATIC_QUESTIONS if q["question"] not in known]
    if not missing:
        return
    with conn:
        for q in missing:
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
    logger.info("Questions statiques seedées (%d ajoutées)", len(missing))


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


def _course_search_text(
    document_title: str | None,
    subject: str | None,
    chapter_title: str | None,
    scope_label: str | None,
    auto_summary: str | None,
    keywords_json: str | None,
) -> str:
    """Identité du COURS dont la question est issue, pour la recherche par sujet.

    Chercher « thermodynamique » ne peut pas dépendre du fait que le mot figure
    dans l'énoncé : ce qui situe une question, c'est le cours où elle a été posée.
    On remonte donc la fiche du document (nom de fichier, matière détectée,
    chapitre, mots-clés et résumé LLM) — les mêmes champs que la recherche de
    bibliothèque. Champ interne : `build_quiz` ne le renvoie pas au client.
    """
    keywords: list[str] = []
    if keywords_json:
        try:
            loaded = json.loads(keywords_json)
        except Exception:
            loaded = None
        if isinstance(loaded, list):
            keywords = [str(k) for k in loaded]
    parts = [
        document_title or "",
        subject or "",
        chapter_title or "",
        scope_label or "",
        " ".join(keywords),
        auto_summary or "",
    ]
    return " ".join(part for part in parts if part)


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
    # Types réflexifs (« comment as-tu trouvé ta réponse ? ») : filtrés en SQL et
    # non après coup, sinon ils consommeraient la limite `n` pour rien.
    excluded = question_types.quiz_excluded_keys()
    where_type = ""
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        where_type = f"AND COALESCE(q.question_type, '') NOT IN ({placeholders})"
        params.extend(excluded)
    params.append(n)
    rows = conn.execute(
        f"""
        SELECT q.id, q.question, q.choices_json, q.answer, q.question_type,
               q.source_context, q.scope_label, q.page_start, q.page_end,
               q.document_id,
               COALESCE(d.filename, '')     AS document_title,
               COALESCE(d.subject, '')      AS subject,
               COALESCE(d.auto_summary, '') AS doc_summary,
               COALESCE(d.keywords, '')     AS doc_keywords,
               COALESCE(c.title, '')        AS chapter_title,
               MAX(CASE WHEN a.verdict IN ('incorrect', 'partial') THEN 1 ELSE 0 END) AS failed
        FROM questions q
        LEFT JOIN documents d ON d.id = q.document_id
        LEFT JOIN chapters c ON c.id = q.chapter_id
        LEFT JOIN answers a ON a.question_id = q.id AND a.user_id = ?
        WHERE q.scope_type = 'page'
          AND TRIM(COALESCE(q.question, '')) <> ''
          {where_subject}
          {where_type}
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
            row_subject, doc_summary, doc_keywords, chapter_title, _failed,
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
            "course_search": _course_search_text(
                document_title, row_subject, chapter_title, scope_label,
                doc_summary, doc_keywords,
            ),
            "source": "reading",
        })
    return results


def get_static_quiz_questions(n: int = 10, subject: str | None = None) -> list[dict]:
    """Questions du catalogue statique, au format d'une question de session de quiz.

    Complément — et non remplacement — des questions de lecture : une base neuve,
    ou un thème dont aucun document n'a encore été lu, doit quand même pouvoir
    lancer un quiz. Tirage aléatoire pour ne pas resservir le même bloc.
    """
    if n <= 0:
        return []
    conn = get_connection()
    sql = """SELECT id, question, choices_json, answer, category
             FROM quiz_static_questions
             {where}
             ORDER BY RANDOM()
             LIMIT ?"""
    if subject:
        rows = conn.execute(
            sql.format(where="WHERE LOWER(category) = LOWER(?)"), (subject, n),
        ).fetchall()
    else:
        rows = conn.execute(sql.format(where=""), (n,)).fetchall()

    results: list[dict] = []
    for qid, question, choices_json, answer, category in rows:
        choices = None
        if choices_json:
            try:
                choices = json.loads(choices_json)
            except Exception:
                choices = None
        results.append({
            "id": STATIC_ID_OFFSET + int(qid),
            "question": question,
            "choices": choices,
            "answer": answer or "",
            # Le catalogue est écrit en QCM : le type le dit, pour que l'UI
            # affiche le bon badge et le bon widget de réponse.
            "question_type": "qcm" if choices else "open",
            "category": (category or "culture").lower(),
            "document": None,
            "document_id": None,
            "chapter_title": None,
            "source_context": "",
            "course_context": "",
            "source": "static",
        })
    return results


def get_quiz_subjects(user_id: int = 1) -> list[dict]:
    """Matières ayant des questions exploitables pour le quiz (lecture + catalogue).

    Renvoie ``[{"subject": str, "count": int}]`` trié par effectif décroissant,
    pour ne proposer dans le sélecteur que des thèmes réellement disponibles. Le
    catalogue statique est compté avec les lectures parce que la session le
    complète (cf. :func:`get_static_quiz_questions`) : l'omettre affichait un
    sélecteur vide sur une base neuve, alors qu'un quiz était jouable.
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
    for category, count in conn.execute(
        """SELECT LOWER(category), COUNT(*)
           FROM quiz_static_questions
           WHERE TRIM(COALESCE(category, '')) <> ''
           GROUP BY LOWER(category)""",
    ).fetchall():
        counts[category] = counts.get(category, 0) + int(count)
    return [
        {"subject": subject, "count": count}
        for subject, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
