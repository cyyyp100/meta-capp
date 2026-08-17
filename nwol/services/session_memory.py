# reader/session_memory.py — Mémoire courte de la session de lecture
#
# Alimente la politique d'intervention et la synthèse de fin de session :
# pages vues (avec temps cumulé et nombre de visites), questions posées à
# l'assistant, réponses aux questions pédagogiques, difficultés détectées.
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class SessionMemory:
    dwell_by_page: dict[int, float] = field(default_factory=dict)
    visits_by_page: dict[int, int] = field(default_factory=dict)
    questions_by_page: dict[int, int] = field(default_factory=dict)
    answers: list[dict] = field(default_factory=list)
    difficulties: list[dict] = field(default_factory=list)

    _current_page: int | None = None
    _entered_at: float = 0.0

    # ------------------------------------------------------------------
    # Événements
    # ------------------------------------------------------------------
    def on_page_view(self, page: int, now: float | None = None) -> None:
        """La page dominante du viewport a changé."""
        now = time.monotonic() if now is None else now
        if page == self._current_page:
            return
        self._flush_dwell(now)
        self._current_page = page
        self._entered_at = now
        self.visits_by_page[page] = self.visits_by_page.get(page, 0) + 1
        self.dwell_by_page.setdefault(page, 0.0)

    def on_user_question(self, page: int, question: str = "") -> None:
        self.questions_by_page[page] = self.questions_by_page.get(page, 0) + 1

    def on_answer(self, page: int, verdict: str | None) -> None:
        self.answers.append({"page": page, "verdict": verdict})
        if verdict == "incorrect":
            self.difficulties.append({"page": page, "kind": "incorrect_answer"})

    # ------------------------------------------------------------------
    # Lectures (politique d'intervention / synthèse)
    # ------------------------------------------------------------------
    def current_dwell(self, now: float | None = None) -> float:
        """Secondes passées sur la page dominante actuelle."""
        if self._current_page is None:
            return 0.0
        now = time.monotonic() if now is None else now
        return max(0.0, now - self._entered_at)

    def visits(self, page: int) -> int:
        return self.visits_by_page.get(page, 0)

    def questions_on(self, page: int) -> int:
        return self.questions_by_page.get(page, 0)

    def pages_seen(self) -> set[int]:
        return set(self.dwell_by_page)

    def help_pages(self, top_n: int = 3) -> list[dict]:
        ranked = sorted(self.questions_by_page.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"page": page, "questions_count": count} for page, count in ranked[:top_n]]

    def flush(self, now: float | None = None) -> None:
        """Fige le temps de la page courante (avant persistance)."""
        self._flush_dwell(time.monotonic() if now is None else now)

    def summary(self) -> dict:
        self._flush_dwell(time.monotonic())
        total_questions = sum(self.questions_by_page.values())
        return {
            "pages_seen": len(self.dwell_by_page),
            "assistant_questions": total_questions,
            "help_pages": self.help_pages(),
            "difficulties": list(self.difficulties[-10:]),
        }

    def _flush_dwell(self, now: float) -> None:
        if self._current_page is not None:
            elapsed = max(0.0, now - self._entered_at)
            self.dwell_by_page[self._current_page] = (
                self.dwell_by_page.get(self._current_page, 0.0) + elapsed
            )
            self._entered_at = now
