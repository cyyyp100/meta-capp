# services/warmup.py — La révision éclair du sas d'entrée : ce que dit son RYTHME.
#
# Le warm-up est clic-only : un clic retourne la carte, le suivant passe à la
# carte suivante, et rien ne permet de l'écourter. Il n'y a rien à corriger,
# mais il y a un temps — celui passé sur la question, celui passé sur la
# réponse — et ce temps dit quelque chose :
#
#   * cliquer plus vite qu'on ne peut lire, c'est ne pas se tester : attention
#     et métacognition baissent ;
#   * traîner, surtout sur la réponse, c'est une trace fragile : la rétention
#     baisse ;
#   * rester vraiment longtemps sur une face, c'est être parti : l'attention
#     baisse, et ce temps-là ne dit plus rien de la mémoire.
#
# Les seuils sont rapportés au texte de chaque face — une question de trente
# mots ne se lit pas comme « Capitale du Pérou ? » — et déclarés dans
# config/settings.py. Le routeur du lecteur ne fait que relayer les temps ; la
# règle, les effets sur les jauges et le résumé remis au bilan de Clikoda vivent
# ici, seuls.
from __future__ import annotations

import logging

from config.settings import (
    WARMUP_CHECK_ALLOWANCE_S,
    WARMUP_DRIFT_ATTENTION,
    WARMUP_DRIFT_S,
    WARMUP_MAX_CARDS,
    WARMUP_MIN_FACE_MS,
    WARMUP_READ_MS_PER_WORD,
    WARMUP_RECALL_ALLOWANCE_S,
    WARMUP_RUSH_ATTENTION,
    WARMUP_RUSH_META,
    WARMUP_SKIM_MS_PER_WORD,
    WARMUP_SLOW_BACK_RETENTION,
    WARMUP_SLOW_FRONT_RETENTION,
)
from db.flashcards import get_flashcard
from db.session_warmup import get_session_warmup, save_session_warmup

logger = logging.getLogger("services.warmup")

__all__ = ["PACES", "face_pace", "assess", "gauge_deltas", "record", "session_deltas", "summary"]

PACES = ("rushed", "steady", "slow", "drifted")
_FACES = ("front", "back")


def face_pace(text: str | None, ms: float, face: str) -> str:
    """Rythme d'une face : `rushed`, `steady`, `slow` ou `drifted`.

    `face` vaut `front` (la question : on y cherche la réponse) ou `back` (la
    réponse : on la confronte à la sienne) — seule la marge diffère."""
    words = len(str(text or "").split())
    seconds = max(0.0, float(ms)) / 1000.0
    skim_s = max(WARMUP_MIN_FACE_MS, words * WARMUP_SKIM_MS_PER_WORD) / 1000.0
    read_s = words * WARMUP_READ_MS_PER_WORD / 1000.0
    allowance = WARMUP_RECALL_ALLOWANCE_S if face == "front" else WARMUP_CHECK_ALLOWANCE_S
    if seconds < skim_s:
        return "rushed"
    if seconds > read_s + WARMUP_DRIFT_S:
        return "drifted"
    if seconds > read_s + allowance:
        return "slow"
    return "steady"


def assess(cards: list[dict]) -> list[dict]:
    """Juge les temps reçus du lecteur, carte par carte (`WARMUP_MAX_CARDS` au plus).

    Le texte des faces est relu en base, jamais pris du client. Une carte
    supprimée depuis est jugée sur les seuls planchers, et n'est plus référencée."""
    rows: list[dict] = []
    for position, card in enumerate(list(cards or [])[:WARMUP_MAX_CARDS]):
        card_id = card.get("card_id")
        stored = (get_flashcard(int(card_id)) if card_id else None) or {}
        front_ms = int(card.get("front_ms") or 0)
        back_ms = int(card.get("back_ms") or 0)
        rows.append({
            "position": position,
            "card_id": stored.get("id"),
            "front_ms": front_ms,
            "back_ms": back_ms,
            "front_pace": face_pace(stored.get("front"), front_ms, "front"),
            "back_pace": face_pace(stored.get("back"), back_ms, "back"),
        })
    return rows


def gauge_deltas(rows: list[dict]) -> dict[str, float]:
    """Effet cumulé du warm-up sur les jauges (deltas négatifs, jauges touchées seulement)."""
    deltas: dict[str, float] = {}

    def cost(gauge: str, points: float) -> None:
        deltas[gauge] = deltas.get(gauge, 0.0) - float(points)

    for row in rows:
        for face in _FACES:
            pace = row.get(f"{face}_pace")
            if pace == "rushed":
                cost("attention", WARMUP_RUSH_ATTENTION)
                cost("meta_cognition", WARMUP_RUSH_META)
            elif pace == "slow":
                cost("retention", WARMUP_SLOW_FRONT_RETENTION if face == "front" else WARMUP_SLOW_BACK_RETENTION)
            elif pace == "drifted":
                cost("attention", WARMUP_DRIFT_ATTENTION)
    return {gauge: round(value, 2) for gauge, value in deltas.items() if value}


def record(session_id: int, cards: list[dict]) -> dict[str, float] | None:
    """Juge et persiste le warm-up d'une séance ; renvoie les deltas à verser.

    None si rien n'est à verser : aucune carte, ou warm-up déjà enregistré pour
    cette séance (un `start_reading` renvoyé à la reconnexion ne compte pas deux
    fois)."""
    rows = assess(cards)
    if not rows or not save_session_warmup(int(session_id), rows):
        return None
    deltas = gauge_deltas(rows)
    logger.info("Warm-up de la session %s : %s", session_id, deltas or "rythme régulier")
    return deltas


def session_deltas(session_id: int) -> dict[str, float]:
    """Les deltas du warm-up d'une séance, relus depuis ses rythmes stockés."""
    return gauge_deltas(get_session_warmup(int(session_id)))


def summary(session_id: int) -> dict | None:
    """Ce que le bilan de Clikoda reçoit du warm-up : temps par carte et total.

    None quand la séance n'a pas eu de warm-up (aucune carte prête)."""
    rows = get_session_warmup(int(session_id))
    if not rows:
        return None
    counts = {pace: 0 for pace in PACES if pace != "steady"}
    for row in rows:
        for face in _FACES:
            pace = row.get(f"{face}_pace")
            if pace in counts:
                counts[pace] += 1
    return {
        "cards": len(rows),
        "total_s": round(sum(int(r["front_ms"]) + int(r["back_ms"]) for r in rows) / 1000.0, 1),
        "per_card": [
            {
                "question_s": round(int(r["front_ms"]) / 1000.0, 1),
                "question_pace": r["front_pace"],
                "answer_s": round(int(r["back_ms"]) / 1000.0, 1),
                "answer_pace": r["back_pace"],
            }
            for r in rows
        ],
        # Faces (deux par carte) jugées hors du rythme régulier.
        "faces_rushed": counts["rushed"],
        "faces_slow": counts["slow"],
        "faces_drifted": counts["drifted"],
    }
