# reader/context_snapshot.py — Capture du contexte de page au moment du submit
#
# Point crucial du flux assistant : le contexte envoyé au LLM est figé au
# moment exact où l'utilisateur valide sa question (Entrée / « Envoyer »),
# jamais au moment où le panneau s'ouvre — il a pu scroller entre-temps.
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PageContextSnapshot:
    snapshot_id: str
    page_number: int
    page_text: str
    image_path: str | None
    doc_id: int | None
    doc_title: str
    chapter_title: str
    gauges: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    timestamp: float = 0.0


def make_snapshot(
    page_number: int,
    page_text: str,
    image_path: str | None,
    doc_id: int | None,
    doc_title: str,
    chapter_title: str = "",
    gauges: dict | None = None,
    history: list | None = None,
) -> PageContextSnapshot:
    return PageContextSnapshot(
        snapshot_id=uuid.uuid4().hex[:12],
        page_number=int(page_number),
        page_text=page_text or "",
        image_path=image_path or None,
        doc_id=doc_id,
        doc_title=doc_title or "",
        chapter_title=chapter_title or "",
        gauges=dict(gauges or {}),
        history=list(history or [])[-5:],
        timestamp=time.monotonic(),
    )
