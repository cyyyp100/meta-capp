# reader/state.py — État courant du lecteur scroll libre
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("Reader.state")


@dataclass
class ReaderState:
    """État minimal partagé entre l'app, le lecteur scroll libre et le companion.

    Le lecteur n'avance plus page par page : ``current_page`` suit la page
    dominante du viewport et ``pages_seen`` accumule les pages réellement vues.
    """

    # Document courant
    doc_id: int | None = None
    current_page: int = 1
    total_pages: int = 0
    pages_seen: set[int] = field(default_factory=set)

    # Contexte de lecture (pour le companion / les jauges)
    chapter_title: str = ""
    doc_title: str = ""
    session_gauges: dict[str, float] = field(default_factory=dict)

    # Session de lecture active
    chapter_mode: bool = False

    # Boucle Q&R adaptative
    qa_active: bool = False
    current_question: dict[str, Any] | None = None
    attempt_count: int = 0
    consecutive_incorrect: int = 0
    session_history: list[dict[str, Any]] = field(default_factory=list)

    def mark_page_seen(self, page: int) -> None:
        if page >= 1:
            self.current_page = page
            self.pages_seen.add(page)

    def pages_read_count(self) -> int:
        """Nombre de pages vues pendant la session (pour ``pages_read``)."""
        if self.pages_seen:
            return len(self.pages_seen)
        return max(0, self.current_page)

    def reset_playback(self) -> None:
        self.qa_active = False
        self.current_question = None
        self.attempt_count = 0
        self.consecutive_incorrect = 0

    def push_session_history(self, item: dict[str, Any], limit: int = 5) -> None:
        self.session_history.append(item)
        if len(self.session_history) > limit:
            self.session_history = self.session_history[-limit:]
