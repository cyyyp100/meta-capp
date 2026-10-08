# db/quiz_questions.py — Questions statiques du quizz de niveau + sélection adaptative
from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from config import question_types
from config.subjects import FALLBACK_SUBJECT, canonical_subject
from db import get_connection
from utils.text import document_reference

logger = logging.getLogger("DB.quiz")

_GENERIC_QUESTION_FRAGMENTS: tuple[str, ...] = (
    "la relation ou les données du passage",
    "les données du passage à un cas",
    "du passage à un cas simple",
    "appliquerais-tu la relation",
)


def _is_unusable_for_quiz(question_text: str, source_context: str | None = None) -> bool:
    t = (question_text or "").lower()
    if any(frag in t for frag in _GENERIC_QUESTION_FRAGMENTS):
        return True
    # Une question qui renvoie au document (« selon le passage », « according to
    # the text », « Table 3.5 ») sans le contexte de lecture qui l'accompagne :
    # le quiz la servirait seule. Patrons partagés avec les cartes (utils/text).
    if not (source_context or "").strip() and document_reference(question_text):
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
    # ── Anglais : vocabulaire (dont quelques faux amis) ────────────────────
    {
        "question": "Que signifie le mot anglais « to achieve » ?",
        "choices": ["Accomplir", "Échouer", "Hériter", "Éviter"],
        "answer": "Accomplir",
        "category": "anglais",
        "difficulty": 1,
    },
    {
        "question": "Que signifie le mot anglais « to borrow » ?",
        "choices": ["Emprunter", "Prêter", "Acheter", "Rendre"],
        "answer": "Emprunter",
        "category": "anglais",
        "difficulty": 2,
    },
    {
        "question": "Que signifie le mot anglais « to gather » ?",
        "choices": ["Rassembler", "Disperser", "Oublier", "Réparer"],
        "answer": "Rassembler",
        "category": "anglais",
        "difficulty": 2,
    },
    {
        "question": "Que signifie l'adjectif anglais « harmful » ?",
        "choices": ["Nuisible", "Utile", "Inoffensif", "Agréable"],
        "answer": "Nuisible",
        "category": "anglais",
        "difficulty": 2,
    },
    {
        "question": "Que signifie l'adverbe anglais « actually » ?",
        "choices": ["En réalité", "Actuellement", "Activement", "Éventuellement"],
        "answer": "En réalité",
        "category": "anglais",
        "difficulty": 2,
    },
    {
        "question": "Que signifie l'adverbe anglais « eventually » ?",
        "choices": ["Finalement", "Éventuellement", "Rarement", "Immédiatement"],
        "answer": "Finalement",
        "category": "anglais",
        "difficulty": 3,
    },
    {
        "question": "Que signifie le verbe anglais « to attend » ?",
        "choices": ["Assister à", "Attendre", "Prétendre", "Tenter"],
        "answer": "Assister à",
        "category": "anglais",
        "difficulty": 2,
    },
    {
        "question": "Que signifie le mot anglais « a library » ?",
        "choices": ["Une bibliothèque", "Une librairie", "Un magasin", "Un laboratoire"],
        "answer": "Une bibliothèque",
        "category": "anglais",
        "difficulty": 1,
    },
    {
        "question": "Que signifie le mot anglais « weather » ?",
        "choices": ["Le temps qu'il fait", "Le temps qui passe", "Une tempête", "Un rassemblement"],
        "answer": "Le temps qu'il fait",
        "category": "anglais",
        "difficulty": 1,
    },
    {
        "question": "Que signifie le verbe anglais « to spend » ?",
        "choices": ["Dépenser (ou passer du temps)", "Économiser", "Suspendre", "Envoyer"],
        "answer": "Dépenser (ou passer du temps)",
        "category": "anglais",
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
    user_id: int = 1, n: int = 10, subject: str | None = None, shuffle: bool = False
) -> list[dict]:
    """Questions de lecture (``scope_type='page'``) pour une session de quiz.

    On prend **toutes** les questions générées pendant les lectures (pas seulement
    celles ratées) et **sans** complément de questions statiques : la longueur suit
    le stock réel par thème (borné par ``n``). Les types survivent au passage — le
    quiz les rejoue tels quels (cf. `services.quiz.build_quiz`), et pas uniquement
    en QCM. ``document_id`` est exposé pour permettre le deep-link vers le reader.

    **Cette fonction ne choisit pas la session : elle fournit un VIVIER.** L'ordre
    « ratées d'abord, puis les plus récentes » n'est qu'un ordre de chargement
    stable ; le tri qui compte (amortissement des questions déjà servies, bonus
    des ratées, fraîcheur bornée) est appliqué par `services.quiz._pick` sur le
    vivier entier. Laisser ce ``LIMIT`` trancher la session — ce qu'il faisait
    quand l'appelant passait ``n = count`` — rendait indéfiniment les mêmes
    questions à chaque session sur une même matière.

    Les colonnes de sélection ``created_at`` et ``failed`` remontent avec chaque
    ligne pour que ce calcul soit possible sans seconde requête.

    ``shuffle`` échange l'ordre de chargement contre un tirage aléatoire, pour que
    la pratique entrelacée voie un vivier qui ne soit pas concentré sur le dernier
    document lu.
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
    # Le vivier est ÉCHANTILLONNÉ, jamais pris par le haut. `ORDER BY created_at DESC`
    # en faisait une fenêtre de récence : passé `n` questions sur une matière, les
    # plus anciennes ne pouvaient plus JAMAIS entrer dans un quiz, quel que soit le
    # nombre de sessions. Un tirage SQL uniforme les rend toutes atteignables ; la
    # préférence pour le matériel récent est réintroduite — bornée — par le facteur
    # de fraîcheur de `services.quiz._weights`, qui lui n'exclut rien.
    # `failed DESC` reste en tête : les questions ratées forment un petit ensemble
    # qu'on veut voir entrer dans le vivier à coup sûr.
    order_by = "RANDOM()" if shuffle else "failed DESC, RANDOM()"
    rows = conn.execute(
        f"""
        SELECT q.id, q.question, q.choices_json, q.answer, q.question_type,
               q.source_context, q.scope_label, q.page_start, q.page_end,
               q.document_id, q.created_at,
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
        ORDER BY {order_by}
        LIMIT ?
        """,
        params,
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        (
            qid, question, choices_json, answer, qtype, source_context,
            scope_label, page_start, page_end, document_id, created_at, document_title,
            row_subject, doc_summary, doc_keywords, chapter_title, failed,
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
            "category": canonical_subject(row_subject) or FALLBACK_SUBJECT,
            "document": document_title or None,
            "document_id": document_id,
            "chapter_title": chapter_title or None,
            "source_context": source_context or "",
            "course_context": course_context,
            "course_search": _course_search_text(
                document_title, row_subject, chapter_title, scope_label,
                doc_summary, doc_keywords,
            ),
            # Champs internes de sélection (`services.quiz` les pondère, puis
            # `_assemble_quiz` les laisse tomber : ils ne partent pas au client).
            "created_at": created_at,
            "failed": bool(failed),
            "source": "reading",
        })
    return results


def get_static_quiz_questions(
    n: int = 10,
    subject: str | None = None,
    subjects: Iterable[str] | None = None,
) -> list[dict]:
    """Questions du catalogue statique, au format d'une question de session de quiz.

    Complément — et non remplacement — des questions de lecture : une matière
    dont aucun document n'a encore été lu doit quand même pouvoir lancer un quiz.
    Tirage aléatoire pour ne pas resservir le même bloc.

    ``subjects`` borne le tirage aux matières de l'apprenant
    (`services.subjects.owned_subjects`) : le catalogue complète ses matières, il
    ne lui en donne pas de nouvelles. Vide : rien.
    """
    if n <= 0:
        return []
    clauses: list[str] = []
    params: list = []
    if subject:
        clauses.append("LOWER(category) = LOWER(?)")
        params.append(subject)
    if subjects is not None:
        allowed = sorted({str(s).lower() for s in subjects if s})
        if not allowed:
            return []
        clauses.append(f"LOWER(category) IN ({', '.join('?' for _ in allowed)})")
        params.extend(allowed)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT id, question, choices_json, answer, category
            FROM quiz_static_questions
            {where}
            ORDER BY RANDOM()
            LIMIT ?""",
        (*params, n),
    ).fetchall()

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
            "category": canonical_subject(category) or FALLBACK_SUBJECT,
            "document": None,
            "document_id": None,
            "chapter_title": None,
            "source_context": "",
            "course_context": "",
            "source": "static",
        })
    return results


def count_quiz_questions() -> dict[str, int]:
    """Questions jouables en quiz, par matière (clé canonique).

    Les questions de lecture comptent sous la matière de leur document, le
    catalogue statique sous sa catégorie ; les types que le quiz ne pose jamais
    (réflexifs) et les énoncés inutilisables hors lecture n'y sont pas. Ce n'est
    PAS la liste des matières proposées — ce sont celles de l'apprenant
    (`services.subjects`) —, c'est l'effectif affiché à côté de chacune.
    """
    conn = get_connection()
    excluded = question_types.quiz_excluded_keys()
    where_type = ""
    if excluded:
        where_type = f"AND COALESCE(q.question_type, '') NOT IN ({', '.join('?' for _ in excluded)})"
    rows = conn.execute(
        f"""
        SELECT d.subject, q.question, q.source_context
        FROM questions q
        JOIN documents d ON d.id = q.document_id
        WHERE q.scope_type = 'page'
          AND TRIM(COALESCE(q.question, '')) <> ''
          AND TRIM(COALESCE(d.subject, '')) <> ''
          {where_type}
        """,
        tuple(excluded),
    ).fetchall()
    counts: dict[str, int] = {}
    for raw_subject, question, source_context in rows:
        subject = canonical_subject(raw_subject)
        if subject is None or _is_unusable_for_quiz(question, source_context):
            continue
        counts[subject] = counts.get(subject, 0) + 1
    for category, count in conn.execute(
        """SELECT category, COUNT(*)
           FROM quiz_static_questions
           WHERE TRIM(COALESCE(category, '')) <> ''
           GROUP BY category""",
    ).fetchall():
        subject = canonical_subject(category)
        if subject is not None:
            counts[subject] = counts.get(subject, 0) + int(count)
    return counts
