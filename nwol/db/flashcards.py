# db/flashcards.py — CRUD flash cards
from __future__ import annotations

import base64
import json
import logging
import mimetypes
from datetime import datetime, timedelta
from pathlib import Path

from db import get_connection
from db.user import DEFAULT_USER_ID, ensure_default_user
from utils.flashcard_tags import fallback_flashcard_tags, normalize_flashcard_tags

logger = logging.getLogger("DB.flashcards")

# Répétition espacée légère : facteur d'intervalle par verdict de révision.
_SR_FACTORS = {"correct": 2.5, "partial": 1.2}
_SR_MAX_INTERVAL_DAYS = 60.0
_SR_INITIAL_INTERVAL_DAYS = 1.0


def _sql_datetime(dt: datetime) -> str:
    """Format comparable aux datetime() de SQLite (heure locale, sans 'T')."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


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
) -> int:
    ensure_default_user()
    normalized_tags = normalize_flashcard_tags(tags)
    if not normalized_tags:
        normalized_tags = fallback_flashcard_tags(front, back, minimum=1)
    assets = _encode_flashcard_assets(asset_paths or [])
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO flashcards
               (user_id, question_id, session_id, document_id, chapter_id, front, back,
                tags, assets_json, difficulty, source, due_at, interval_days, language)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            ),
        )
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
    import math
    import random
    from datetime import datetime

    from db.documents import get_document_subject

    # Les cartes dues (répétition espacée) passent en priorité absolue.
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
           LIMIT 60""",
        (user_id,),
    ).fetchall()

    if not rows:
        logger.info("Sas d'entrée : aucune flashcard disponible")
        return due_cards

    session_subject = get_document_subject(doc_id) if doc_id else None
    logger.info("Sas d'entrée : sujet session=%s, %d candidats", session_subject or "—", len(rows))
    now = datetime.now()
    HALF_LIFE_DAYS = 7.0
    SUBJECT_BONUS = 2.0

    scored: list[tuple[float, dict]] = []
    for row in rows:
        card = _decode_flashcard(row)
        if card["id"] in due_ids:
            continue
        try:
            created = datetime.fromisoformat(card["created_at"])
            age_days = max(0.0, (now - created).total_seconds() / 86400)
        except (TypeError, ValueError, KeyError):
            age_days = 30.0
        recency = math.exp(-age_days * math.log(2) / HALF_LIFE_DAYS)
        card_subject = card.get("document_subject") or ""
        bonus = SUBJECT_BONUS if (session_subject and card_subject == session_subject) else 1.0
        score = recency * bonus
        logger.debug(
            "  carte id=%s age=%.1fj sujet=%s recency=%.3f bonus=%.1f score=%.3f | %s",
            card["id"], age_days, card_subject or "—", recency, bonus, score,
            (card.get("front") or "")[:60],
        )
        scored.append((score, card))

    weights = [s for s, _ in scored]
    cards = [c for _, c in scored]
    if not cards:
        return due_cards
    k = min(n - len(due_cards), len(cards))
    selected = random.choices(population=cards, weights=weights, k=k)

    seen_ids: set[int] = set()
    result: list[dict] = []
    for card in selected:
        if card["id"] not in seen_ids:
            seen_ids.add(card["id"])
            result.append(card)
    if len(result) < k:
        for _, card in scored:
            if card["id"] not in seen_ids and len(result) < k:
                result.append(card)
                seen_ids.add(card["id"])
    score_by_id = {c["id"]: s for s, c in scored}
    for card in result:
        card_id = card["id"]
        score = score_by_id.get(card_id, 0.0)
        try:
            age_days = max(0.0, (now - datetime.fromisoformat(card["created_at"])).total_seconds() / 86400)
        except (TypeError, ValueError, KeyError):
            age_days = 0.0
        card_subject = card.get("document_subject") or "—"
        logger.info(
            "  → carte id=%s score=%.3f age=%.1fj sujet=%s | %s",
            card_id, score, age_days, card_subject,
            (card.get("front") or "")[:60],
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

    params.append(card_id)
    conn = get_connection()
    with conn:
        conn.execute(f"UPDATE flashcards SET {', '.join(updates)} WHERE id=?", params)


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
