# db/flashcards.py — CRUD flash cards
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from db import get_connection
from db.user import DEFAULT_USER_ID, ensure_default_user
from utils.tags import fallback_flashcard_tags, normalize_flashcard_tags
from utils.text import fingerprint

logger = logging.getLogger("DB.flashcards")

# Répétition espacée légère : facteur d'intervalle par verdict de révision.
_SR_FACTORS = {"correct": 2.5, "partial": 1.2}
_SR_MAX_INTERVAL_DAYS = 60.0
_SR_INITIAL_INTERVAL_DAYS = 1.0


def _sql_datetime(dt: datetime) -> str:
    """Format comparable aux datetime() de SQLite (heure locale, sans 'T')."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def flashcard_key(front: str, back: str) -> str:
    """Clé de doublon d'une carte : empreinte pliée du recto et du verso.

    UNE seule définition, partagée par l'écriture (`save_flashcard`), la
    recherche d'un doublon (`find_flashcard_id`) et la migration v29 qui a posé
    l'index UNIQUE — trois copies divergeraient.
    """
    return fingerprint(front or "", back or "")


def find_flashcard_id(user_id: int, dedup_key: str) -> int | None:
    """Id de la carte qui porte déjà cette clé, None si elle n'existe pas."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM flashcards WHERE user_id=? AND dedup_key=? LIMIT 1",
        (user_id or DEFAULT_USER_ID, dedup_key),
    ).fetchone()
    return int(row["id"]) if row else None


def save_flashcard(
    user_id: int,
    question_id: int | None,
    front: str,
    back: str,
    tags: list[str] | None = None,
    difficulty: int = 2,
    source: str = "auto",
    document_id: int | None = None,
    chapter_id: int | None = None,
    session_id: int | None = None,
    asset_paths: list[str] | None = None,
    language: str | None = None,
    dedup_key: str | None = None,
    pronunciation: str | None = None,
) -> int:
    """Enregistre une carte ; renvoie son id.

    JAMAIS DE DOUBLON : l'index UNIQUE (user_id, dedup_key) posé par la
    migration v29 fait de l'insertion un no-op quand la clé existe déjà, et
    c'est alors l'id de la carte EXISTANTE qui est renvoyé — l'appelant qui
    veut savoir si la carte est neuve compare avec `find_flashcard_id` avant.
    `dedup_key` par défaut = `flashcard_key(front, back)` ; une carte réécrite
    par le LLM depuis un échange passe l'empreinte de l'échange brut à la place
    (cf. services.flashcards.create_flashcard).
    """
    ensure_default_user()
    normalized_tags = normalize_flashcard_tags(tags)
    if not normalized_tags:
        normalized_tags = fallback_flashcard_tags(front, back, minimum=1)
    assets = _encode_flashcard_assets(asset_paths or [])
    key = dedup_key or flashcard_key(front, back)
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO flashcards
               (user_id, question_id, session_id, document_id, chapter_id, front, back,
                tags, assets_json, difficulty, source, due_at, interval_days, language,
                dedup_key, pronunciation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, dedup_key) DO NOTHING""",
            (
                user_id or DEFAULT_USER_ID,
                question_id,
                session_id,
                document_id,
                chapter_id,
                front.strip(),
                back.strip(),
                json.dumps(normalized_tags, ensure_ascii=False),
                json.dumps(assets, ensure_ascii=False) if assets else None,
                _normalize_difficulty(difficulty),
                source,
                _sql_datetime(datetime.now() + timedelta(days=_SR_INITIAL_INTERVAL_DAYS)),
                _SR_INITIAL_INTERVAL_DAYS,
                language,
                key,
                (pronunciation or "").strip() or None,
            ),
        )
    if cur.rowcount == 0:
        existing = find_flashcard_id(user_id, key)
        if existing is not None:
            logger.info("Flashcard déjà présente id=%s (doublon ignoré, source=%s)", existing, source)
            return existing
    logger.info("Flashcard créée id=%s source=%s", cur.lastrowid, source)
    return int(cur.lastrowid)


def lang_flashcard_exists(user_id: int, language: str, front: str) -> bool:
    """Dédup des flashcards de vocabulaire : même (utilisateur, langue, recto)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM flashcards WHERE user_id=? AND language=? AND lower(front)=lower(?) LIMIT 1",
        (user_id or DEFAULT_USER_ID, language, (front or "").strip()),
    ).fetchone()
    return row is not None


def fill_lang_flashcard_pronunciation(
    user_id: int, language: str, front: str, pronunciation: str,
) -> bool:
    """Complète la prononciation d'une carte de vocabulaire qui n'en a pas encore.

    Jamais d'écrasement : une prononciation déjà posée reste. Renvoie True si
    une carte a été complétée."""
    pronunciation = (pronunciation or "").strip()
    if not pronunciation:
        return False
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """UPDATE flashcards SET pronunciation=?
               WHERE user_id=? AND language=? AND lower(front)=lower(?)
                 AND (pronunciation IS NULL OR pronunciation='')""",
            (pronunciation, user_id or DEFAULT_USER_ID, language, (front or "").strip()),
        )
    return cur.rowcount > 0


def get_flashcard(card_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM flashcards WHERE id=?", (card_id,)).fetchone()
    return _decode_flashcard(row) if row else None


def get_flashcards(
    user_id: int = DEFAULT_USER_ID,
    filters: dict | int | None = None,
    document_id: int | None = None,
    tags: list[str] | str | None = None,
    difficulty: int | None = None,
) -> list[dict]:
    if filters is not None and not isinstance(filters, dict):
        document_id = int(filters)
        filters = {}
    filters = dict(filters or {})
    if document_id is not None:
        filters["document_id"] = document_id
    if tags:
        filters["tags"] = tags
    if difficulty is not None:
        filters["difficulty"] = difficulty

    clauses = ["flashcards.user_id=?"]
    params: list = [user_id]

    for key in ("document_id", "chapter_id", "question_id", "difficulty", "source"):
        if filters.get(key) is not None:
            clauses.append(f"flashcards.{key}=?")
            params.append(filters[key])

    tag_filters = filters.get("tags") or filters.get("tag")
    if isinstance(tag_filters, str):
        tag_filters = [tag_filters]
    for tag in tag_filters or []:
        clean_tag = str(tag).strip()
        if clean_tag:
            clauses.append("flashcards.tags LIKE ?")
            params.append(f"%{clean_tag}%")

    query = (
        """SELECT flashcards.*,
                  documents.filename AS document_title,
                  chapters.title AS chapter_title
           FROM flashcards
           LEFT JOIN documents ON documents.id=flashcards.document_id
           LEFT JOIN chapters ON chapters.id=flashcards.chapter_id
           WHERE """
        + " AND ".join(clauses)
        + " ORDER BY document_title COLLATE NOCASE, chapter_title COLLATE NOCASE, flashcards.created_at DESC, flashcards.id DESC"
    )
    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    return [_decode_flashcard(row) for row in rows]


def get_session_start_cards(
    user_id: int = DEFAULT_USER_ID,
    n: int = 5,
    doc_id: int | None = None,
) -> list[dict]:
    """Cartes d'échauffement du sas d'entrée : les dues d'abord, puis un tirage pondéré.

    Le tirage évite trois pièges, tous présents dans la version d'origine :

    - un ``LIMIT 60`` sur ``created_at DESC`` rendait toute carte hors des 60 plus
      récentes DÉFINITIVEMENT inatteignable en échauffement ;
    - une demi-vie de récence de 7 jours éteignait le stock d'avant-hier, si bien
      que l'échauffement ne montrait plus que les dernières cartes créées ;
    - `random.choices` tirait AVEC remise, et chaque collision était réparée en
      rebouchant dans l'ordre de récence — ce qui ramenait sournoisement le
      tirage vers ce qu'il était censé éviter.

    L'amortissement s'appuie sur ``last_reviewed``, que l'échauffement écrit
    lui-même (le composant WarmUp appelle `/review` sur chaque carte montrée) :
    le signal « déjà vue à la session précédente » existait déjà, il n'était pas lu.
    """
    from config.settings import (
        FLASHCARD_POOL,
        FLASHCARD_RECENCY_FLOOR,
        FLASHCARD_RECENCY_HALF_LIFE_DAYS,
        FLASHCARD_REVIEW_COOLDOWN_DAYS,
        FLASHCARD_REVIEW_FLOOR,
        FLASHCARD_SUBJECT_BONUS,
    )
    from db.documents import get_document_subject
    from services import selection

    # Les cartes dues (répétition espacée) passent en priorité absolue. `doc_id`
    # n'est VOLONTAIREMENT pas transmis : une carte due l'est quel que soit le
    # document ouvert, et la filtrer par document repousserait indéfiniment la
    # révision d'une notion d'un autre cours. Le bonus de sujet plus bas suffit à
    # orienter le reste de l'échauffement.
    due_cards = get_due_flashcards(user_id, limit=n)
    if len(due_cards) >= n:
        logger.info("Sas d'entrée : %d cartes dues sélectionnées", n)
        return due_cards[:n]
    due_ids = {card["id"] for card in due_cards}

    conn = get_connection()
    rows = conn.execute(
        """SELECT flashcards.*,
                  documents.filename AS document_title,
                  documents.subject  AS document_subject,
                  chapters.title     AS chapter_title
           FROM flashcards
           LEFT JOIN documents ON documents.id = flashcards.document_id
           LEFT JOIN chapters  ON chapters.id  = flashcards.chapter_id
           WHERE flashcards.user_id = ?
           ORDER BY flashcards.created_at DESC
           LIMIT ?""",
        (user_id, FLASHCARD_POOL),
    ).fetchall()

    if not rows:
        logger.info("Sas d'entrée : aucune flashcard disponible")
        return due_cards

    session_subject = get_document_subject(doc_id) if doc_id else None
    logger.info("Sas d'entrée : sujet session=%s, %d candidats", session_subject or "—", len(rows))

    cards: list[dict] = []
    weights: list[float] = []
    for row in rows:
        card = _decode_flashcard(row)
        if card["id"] in due_ids:
            continue
        # Fraîcheur bornée : le matériel récent garde un avantage, sans écraser
        # le reste du stock.
        recency = max(
            FLASHCARD_RECENCY_FLOOR,
            selection.decay(
                selection.age_days(card.get("created_at")),
                FLASHCARD_RECENCY_HALF_LIFE_DAYS,
            ),
        )
        card_subject = card.get("document_subject") or ""
        bonus = (
            FLASHCARD_SUBJECT_BONUS
            if (session_subject and card_subject == session_subject)
            else 1.0
        )
        seen = selection.cooldown(
            card.get("last_reviewed"), FLASHCARD_REVIEW_COOLDOWN_DAYS, FLASHCARD_REVIEW_FLOOR,
        )
        weight = recency * bonus * seen
        logger.debug(
            "  carte id=%s sujet=%s recency=%.3f bonus=%.1f vue=%.3f poids=%.3f | %s",
            card["id"], card_subject or "—", recency, bonus, seen, weight,
            (card.get("front") or "")[:60],
        )
        cards.append(card)
        weights.append(weight)

    if not cards:
        return due_cards
    # Sans remise : plus de doublon à réparer, donc plus de rebouchage biaisé.
    result = selection.weighted_sample(cards, weights, n - len(due_cards))
    for card in result:
        logger.info(
            "  → carte id=%s sujet=%s | %s",
            card["id"], card.get("document_subject") or "—", (card.get("front") or "")[:60],
        )
    return due_cards + result


def get_existing_tags(user_id: int = DEFAULT_USER_ID, limit: int = 100) -> list[str]:
    cards = get_flashcards(user_id)
    tags: list[str] = []
    seen: set[str] = set()
    for card in cards:
        for tag in normalize_flashcard_tags(card.get("tags") or []):
            if tag in seen:
                continue
            tags.append(tag)
            seen.add(tag)
            if len(tags) >= limit:
                return tags
    return tags


def update_review(card_id: int, verdict: str) -> None:
    """Révision + répétition espacée légère : ×2.5 correct, ×1.2 partial, retour à 1 j sinon."""
    conn = get_connection()
    row = conn.execute("SELECT interval_days FROM flashcards WHERE id=?", (card_id,)).fetchone()
    try:
        interval = float(row["interval_days"]) if row and row["interval_days"] is not None else _SR_INITIAL_INTERVAL_DAYS
    except (TypeError, ValueError):
        interval = _SR_INITIAL_INTERVAL_DAYS
    factor = _SR_FACTORS.get(verdict)
    interval = min(_SR_MAX_INTERVAL_DAYS, interval * factor) if factor else _SR_INITIAL_INTERVAL_DAYS
    due_at = _sql_datetime(datetime.now() + timedelta(days=interval))
    with conn:
        conn.execute(
            """UPDATE flashcards
               SET last_reviewed=?, review_count=review_count + 1, last_verdict=?,
                   interval_days=?, due_at=?
               WHERE id=?""",
            (datetime.now().isoformat(), verdict, interval, due_at, card_id),
        )


def get_due_flashcards(
    user_id: int = DEFAULT_USER_ID,
    limit: int = 5,
    doc_id: int | None = None,
) -> list[dict]:
    """Cartes dont l'échéance de révision est passée, les plus en retard d'abord."""
    clauses = [
        "flashcards.user_id=?",
        "flashcards.due_at IS NOT NULL",
        "flashcards.due_at <= datetime('now', 'localtime')",
    ]
    params: list = [user_id]
    if doc_id is not None:
        clauses.append("flashcards.document_id=?")
        params.append(doc_id)
    conn = get_connection()
    rows = conn.execute(
        f"""SELECT flashcards.*,
                   documents.filename AS document_title,
                   chapters.title     AS chapter_title
            FROM flashcards
            LEFT JOIN documents ON documents.id = flashcards.document_id
            LEFT JOIN chapters  ON chapters.id  = flashcards.chapter_id
            WHERE {' AND '.join(clauses)}
            ORDER BY flashcards.due_at ASC
            LIMIT ?""",
        (*params, limit),
    ).fetchall()
    return [_decode_flashcard(row) for row in rows]


def get_related_flashcards(
    user_id: int = DEFAULT_USER_ID,
    doc_id: int | None = None,
    chapter_id: int | None = None,
    limit: int = 3,
) -> list[dict]:
    """Cartes liées au contexte de lecture courant (chapitre prioritaire, sinon document)."""
    if doc_id is None and chapter_id is None:
        return []
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM flashcards
           WHERE user_id=? AND (chapter_id=? OR document_id=?)
           ORDER BY (chapter_id=?) DESC, created_at DESC
           LIMIT ?""",
        (user_id, chapter_id, doc_id, chapter_id, limit),
    ).fetchall()
    return [_decode_flashcard(row) for row in rows]


def update_flashcard(
    card_id: int,
    front: str | None = None,
    back: str | None = None,
    tags: list[str] | None = None,
    difficulty: int | None = None,
) -> None:
    updates = []
    params: list = []
    if front is not None:
        updates.append("front=?")
        params.append(front.strip())
    if back is not None:
        updates.append("back=?")
        params.append(back.strip())
    if tags is not None:
        updates.append("tags=?")
        params.append(json.dumps(normalize_flashcard_tags(tags), ensure_ascii=False))
    if difficulty is not None:
        updates.append("difficulty=?")
        params.append(_normalize_difficulty(difficulty))
    if not updates:
        return

    conn = get_connection()
    # La clé de doublon suit le texte : une carte réécrite doit être retrouvée
    # par son NOUVEAU recto/verso (et libérer l'ancien). Sinon la même carte
    # retapée passait l'index, et l'ancien texte restait bloqué pour rien.
    if front is not None or back is not None:
        current = conn.execute(
            "SELECT front, back FROM flashcards WHERE id=?", (card_id,)
        ).fetchone()
        if current is None:
            return
        new_key = flashcard_key(
            front if front is not None else current["front"],
            back if back is not None else current["back"],
        )
        updates.append("dedup_key=?")
        params.append(new_key)

    params.append(card_id)
    try:
        with conn:
            conn.execute(f"UPDATE flashcards SET {', '.join(updates)} WHERE id=?", params)
    except sqlite3.IntegrityError as exc:
        # Une AUTRE carte porte déjà ce recto/verso : l'index UNIQUE refuse, et
        # c'est le bon comportement — on ne fabrique pas un doublon par édition.
        raise ValueError("Une flashcard identique existe déjà") from exc


def delete_flashcard(card_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM flashcards WHERE id=?", (card_id,))


def _decode_flashcard(row) -> dict:
    item = dict(row)
    try:
        item["tags"] = json.loads(item.get("tags") or "[]")
    except json.JSONDecodeError:
        item["tags"] = []
    try:
        item["assets"] = json.loads(item.get("assets_json") or "[]")
    except json.JSONDecodeError:
        item["assets"] = []
    return item


def _normalize_difficulty(difficulty: int) -> int:
    return max(1, min(3, int(difficulty)))


def _encode_flashcard_assets(paths: list[str]) -> list[dict]:
    assets: list[dict] = []
    seen: set[str] = set()
    for raw_path in paths:
        path_text = str(raw_path or "").strip()
        if not path_text or path_text in seen:
            continue
        seen.add(path_text)
        path = Path(path_text)
        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning("Asset flashcard ignoré, lecture impossible %s: %s", path_text, exc)
            continue
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        assets.append({
            "filename": path.name,
            "source_path": path_text,
            "mime_type": mime_type,
            "size_bytes": len(data),
            "data_base64": base64.b64encode(data).decode("ascii"),
        })
    return assets
