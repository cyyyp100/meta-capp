# services/reading_pace.py — L'allure de lecture mesurée, et ce qu'il reste à lire.
#
# La carte « Reprendre » annonçait la médiane des dernières séances, toutes
# catégories confondues : un quiz de cinq minutes y pesait autant qu'une heure
# de lecture, et la durée ne dépendait pas du document. Elle annonce ici le
# temps qu'il RESTE au document : pages restantes × secondes par page.
#
# L'allure est la médiane des temps par page LUE (au moins PAGE_READ_MIN_DWELL_S,
# dans une séance qui a lu quelque chose), cherchée du plus précis au plus
# général : ce document, puis les documents de même nature (PDF ou fichier de
# code), puis READING_ESTIMATE_DEFAULT_PAGE_S, annoncé comme une estimation.
# La médiane plutôt que la moyenne : une page laissée ouverte pendant un repas
# ne fausse pas l'allure, d'où l'absence de plafond.
#
# Rien ici ne lève : une base illisible donne l'allure par défaut, pas une
# bibliothèque qui ne s'ouvre plus.
from __future__ import annotations

import logging
import math
from statistics import median

from config.settings import (
    PAGE_READ_MIN_DWELL_S,
    READING_ESTIMATE_DEFAULT_PAGE_S,
    READING_ESTIMATE_MIN_PAGES,
    READING_ESTIMATE_WINDOW,
)
from db.page_dwell import reading_dwell_samples
from services.library import bookmark_page

logger = logging.getLogger("services.reading_pace")


def _is_code(doc: dict) -> bool:
    return doc.get("extraction_engine") == "code"


def seconds_per_page(doc: dict) -> dict:
    """Allure de l'élève pour ce document : `{seconds, measured, samples, scope}`.

    `scope` dit d'où vient la mesure : `document`, `kind` (même nature) ou
    `default` (rien de mesuré, `measured` faux)."""
    try:
        scopes = (
            ("document", {"document_id": int(doc["id"])}),
            ("kind", {"code": _is_code(doc)}),
        )
        for scope, where in scopes:
            samples = reading_dwell_samples(
                min_dwell_s=PAGE_READ_MIN_DWELL_S, limit=READING_ESTIMATE_WINDOW, **where,
            )
            if len(samples) >= READING_ESTIMATE_MIN_PAGES:
                return {
                    "seconds": round(float(median(samples)), 1),
                    "measured": True,
                    "samples": len(samples),
                    "scope": scope,
                }
    except Exception:
        logger.debug("Allure de lecture illisible, repli sur le défaut", exc_info=True)
    return {
        "seconds": float(READING_ESTIMATE_DEFAULT_PAGE_S),
        "measured": False,
        "samples": 0,
        "scope": "default",
    }


def remaining(doc: dict | None) -> dict | None:
    """Ce qu'il reste à lire de `doc`, à l'allure mesurée :
    `{pages, seconds_per_page, minutes, measured, samples, scope}`.

    Le départ est le marque-page posé par l'élève, sinon la dernière page
    vue ; il compte comme restant à lire : on reprend là où l'on s'est
    arrêté, pas après. None pour un document sans page (ou illisible)."""
    try:
        page_count = int((doc or {}).get("page_count") or 0)
        if page_count <= 0:
            return None
        start = bookmark_page(doc) or min(max(1, int(doc.get("last_page") or 1)), page_count)
        pages = page_count - start + 1
        pace = seconds_per_page(doc)
        return {
            "pages": pages,
            "seconds_per_page": pace["seconds"],
            "minutes": max(1, math.ceil(pages * pace["seconds"] / 60)),
            "measured": pace["measured"],
            "samples": pace["samples"],
            "scope": pace["scope"],
        }
    except Exception:
        logger.debug("Temps restant non calculé", exc_info=True)
        return None
