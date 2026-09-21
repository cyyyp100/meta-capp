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
    # Dernière interaction physique avec la page (défilement, souris, clavier).
    # 0.0 tant que rien n'a été observé : la stagnation retombe alors sur le
    # seul temps passé sur la page.
    _last_interaction: float = 0.0

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
        self._last_interaction = now
        self.visits_by_page[page] = self.visits_by_page.get(page, 0) + 1
        self.dwell_by_page.setdefault(page, 0.0)

    def on_interaction(self, now: float | None = None) -> None:
        """Le lecteur a bougé (scroll, souris, clavier) : l'étudiant est là.

        Une page longue, une deuxième colonne, un retour sur un schéma : autant
        de lectures légitimes qui laissent la page dominante inchangée pendant
        plusieurs minutes. Sans ce signal, la dérive passive les prenait pour du
        décrochage."""
        self._last_interaction = time.monotonic() if now is None else now

    def on_user_question(self, page: int, question: str = "") -> None:
        self.questions_by_page[page] = self.questions_by_page.get(page, 0) + 1

    def on_answer(
        self,
        page: int,
        verdict: str | None,
        chars: int = 0,
        response_time_ms: int | None = None,
    ) -> None:
        """Enregistre une réponse évaluée — verdict ET forme.

        `chars` (longueur de ce que l'étudiant a écrit) et `response_time_ms`
        étaient calculés puis jetés : ils ne servaient qu'à la jauge du moment.
        Gardés en série, ils disent si la production RÉTRÉCIT au fil de la
        session, c'est-à-dire si l'étudiant a décroché (cf.
        `services/intervention.detect_answer_fatigue`)."""
        self.answers.append({
            "page": page,
            "verdict": verdict,
            "chars": max(0, int(chars)),
            "response_time_ms": response_time_ms,
        })
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

    def stagnant_since(self, now: float | None = None) -> float:
        """Secondes d'immobilité réelle : sur la même page ET sans interaction.

        C'est la mesure que la dérive passive d'attention doit lire — pas le
        seul `current_dwell`, qui ignore tout ce que fait l'étudiant sur la page."""
        now = time.monotonic() if now is None else now
        dwell = self.current_dwell(now)
        if not self._last_interaction:
            return dwell
        return max(0.0, min(dwell, now - self._last_interaction))

    def visits(self, page: int) -> int:
        return self.visits_by_page.get(page, 0)

    def questions_on(self, page: int) -> int:
        return self.questions_by_page.get(page, 0)

    def pages_seen(self) -> set[int]:
        return set(self.dwell_by_page)

    def answers_count(self) -> int:
        return len(self.answers)

    def recent_answer_lengths(self, window: int) -> list[int]:
        """Longueurs des `window` dernières réponses écrites, dans l'ordre.

        Les réponses vides ne sont pas comptées : un envoi vide n'est pas une
        production plus courte, c'est une absence de production."""
        lengths = [int(a.get("chars") or 0) for a in self.answers if int(a.get("chars") or 0) > 0]
        return lengths[-max(0, int(window)):] if window else []

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
