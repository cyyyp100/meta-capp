# services/flashcard_check.py — Clikoda relit les flashcards, une fois par semaine.
"""Relecture hebdomadaire des flashcards.

Une carte créée sur une réponse fausse, une question ambiguë ou une formule
cassée restait telle quelle ; une question de lecture trop collée au PDF
donnait une carte qui renvoie à « ce passage » ou « la figure », illisible
sans le document. Au plus une fois par
`FLASHCARD_CHECK_INTERVAL_DAYS`, à l'ouverture de l'app et en travail de fond,
Clikoda relit jusqu'à `FLASHCARD_CHECK_BATCH` cartes (jamais relues, ou
modifiées depuis) et propose :

* une version corrigée (`fix`) pour une vraie erreur, ou pour une carte qui
  renvoie à un contexte absent quand la carte elle-même permet de l'écrire ;
* sa suppression (`remove`) quand la carte dépend d'un contexte absent que
  rien sur elle ne permet de rétablir.

Rien n'est réécrit ni supprimé sans l'élève : la proposition attend sur la
page des flashcards, où il l'applique ou la laisse. En mode économe la relecture ne
part pas (tâche de fond suspendue, `ollama_client.background_suspended`) et la
semaine n'est pas comptée : elle repartira quand le mode sera levé.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Callable

from config.settings import FLASHCARD_CHECK_BATCH, FLASHCARD_CHECK_INTERVAL_DAYS
from core.math_text import repair_common_inline_math_artifacts
from db import flashcard_checks
from db.app_settings import get_setting, set_setting
from db.flashcards import flashcard_key, get_flashcard, update_flashcard
from db.user import DEFAULT_USER_ID
from llm.ollama_client import background_suspended, background_tasks, check_flashcard_async
from services.flashcards import delete_flashcards
from services.llm_bridge import run_llm_sync

logger = logging.getLogger("services.flashcard_check")

_TASK = "flashcard_check"
# Date de la dernière passe menée à bien (app_settings, réglage interne).
_LAST_RUN_KEY = "flashcard_check_last"
# Une formule : $$…$$, $…$, \(…\) ou \[…\].
_MATH_RE = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$|\\\(.+?\\\)|\\\[.+?\\\]", re.S)


def is_due(now: datetime | None = None) -> bool:
    """La dernière passe date-t-elle d'au moins une semaine ?"""
    last = get_setting(_LAST_RUN_KEY)
    if not last:
        return True
    try:
        when = datetime.fromisoformat(last)
    except ValueError:
        return True
    return (now or datetime.now()) - when >= timedelta(days=FLASHCARD_CHECK_INTERVAL_DAYS)


def run_if_due(user_id: int = DEFAULT_USER_ID, *, checker: Callable = check_flashcard_async) -> int:
    """Au démarrage, en thread : relit un lot de cartes si la semaine est passée.

    Renvoie le nombre de cartes relues. Une passe dont aucune carte n'a pu
    être relue (Ollama éteint) n'est pas comptée : elle repartira au prochain
    lancement plutôt que dans une semaine."""
    try:
        if background_suspended(_TASK) or not is_due():
            return 0
        cards = flashcard_checks.cards_to_check(FLASHCARD_CHECK_BATCH, user_id)
        checked = suggested = failed = 0
        with background_tasks():
            for card in cards:
                try:
                    result = run_llm_sync(
                        lambda ok, err, c=card: checker({"front": c["front"], "back": c["back"]}, ok, err),
                    )
                except Exception as exc:
                    failed += 1
                    logger.info("Relecture de la flashcard %s impossible : %s", card["id"], exc)
                    continue
                checked += 1
                suggested += int(_record(card, result) == "suggested")
        if cards and checked == 0:
            return 0
        set_setting(_LAST_RUN_KEY, datetime.now().isoformat(timespec="seconds"))
        logger.info(
            "Relecture des flashcards : %d relue(s), %d correction(s) proposée(s), %d échec(s)",
            checked, suggested, failed,
        )
        return checked
    except Exception:  # pragma: no cover - un thread de fond ne remonte rien
        logger.exception("Relecture des flashcards échouée")
        return 0


def _record(card: dict, result: dict | None) -> str | None:
    """Garde la conclusion de la relecture ; renvoie le statut posé.

    La carte est relue au moment d'écrire : modifiée par l'élève pendant que
    Clikoda la relisait, la conclusion porte sur un texte qui n'existe plus."""
    current = get_flashcard(int(card["id"]))
    if not current or current.get("dedup_key") != card["dedup_key"]:
        return None
    result = result or {}
    verdict, reason = result.get("verdict"), str(result.get("reason") or "")
    if verdict == "remove":
        flashcard_checks.save_check(int(card["id"]), card["dedup_key"], "suggested", kind="remove", reason=reason)
        return "suggested"
    front, back = str(result.get("front") or ""), str(result.get("back") or "")
    unchanged = _same(front, card["front"]) and _same(back, card["back"])
    if verdict != "fix" or unchanged or _notation_only(card, front, back):
        flashcard_checks.save_check(int(card["id"]), card["dedup_key"], "ok")
        return "ok"
    flashcard_checks.save_check(
        int(card["id"]), card["dedup_key"], "suggested", kind="fix", front=front, back=back, reason=reason,
    )
    return "suggested"


def _same(a: str, b: str) -> bool:
    return " ".join(str(a or "").split()) == " ".join(str(b or "").split())


def _notation_only(card: dict, front: str, back: str) -> bool:
    """La correction ne réécrit-elle que des formules déjà bien formées ?

    Mesuré sur gemma4 : malgré la consigne, une formule juste revient en
    `\\frac` « pour la lisibilité ». Ce n'est pas une erreur à signaler. Une
    formule cassée (accolade ou `$` orphelin, artefact connu), elle, reste
    corrigeable."""
    for old, new in ((card["front"], front), (card["back"], back)):
        if not _same(_MATH_RE.sub(" ", old), _MATH_RE.sub(" ", new)):
            return False
    return _well_formed(card["front"]) and _well_formed(card["back"])


def _well_formed(text: str) -> bool:
    if text.replace("\\$", "").count("$") % 2:
        return False
    for formula in _MATH_RE.findall(text):
        depth = 0
        for char in formula:
            depth += (char == "{") - (char == "}")
            if depth < 0:
                return False
        if depth:
            return False
    return repair_common_inline_math_artifacts(text) == text


def suggestions(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Les corrections qui attendent l'élève (page des flashcards)."""
    return flashcard_checks.get_suggestions(user_id)


def accept(card_id: int) -> dict:
    """Applique la proposition : la carte corrigée, ou supprimée. LookupError
    si la carte n'en a plus (déjà traitée, ou modifiée depuis) ; ValueError si
    le texte corrigé est celui d'une autre carte. Renvoie la carte réécrite, ou
    `{"id", "removed": True}`."""
    check, card = flashcard_checks.get_check(card_id), get_flashcard(card_id)
    if not check or not card or check["status"] != "suggested" or check["checked_key"] != card.get("dedup_key"):
        raise LookupError(card_id)
    if check.get("kind") == "remove":
        delete_flashcards([card_id])  # la relecture part avec elle (ON DELETE CASCADE)
        return {"id": card_id, "removed": True}
    update_flashcard(card_id, front=check["front"], back=check["back"])
    # Relue et acceptée : la carte réécrite n'a pas à repasser la semaine suivante.
    flashcard_checks.set_status(card_id, "accepted", flashcard_key(check["front"], check["back"]))
    return get_flashcard(card_id) or {}


def dismiss(card_id: int) -> None:
    """L'élève garde sa carte : elle ne sera relue que s'il la modifie."""
    check = flashcard_checks.get_check(card_id)
    if not check or check["status"] != "suggested":
        raise LookupError(card_id)
    flashcard_checks.set_status(card_id, "dismissed")
