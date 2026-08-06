# llm/lang_session.py — Séquenceur de session langue (20 min / 6 blocs)
from __future__ import annotations

import time

BLOCKS: list[tuple[str, int]] = [
    ("rappel",      120),   # 2 min
    ("ecoute",      300),   # 5 min
    ("lecture",     240),   # 4 min
    ("repetition",  300),   # 5 min
    ("notes",       180),   # 3 min
    ("exercices",    60),   # 1 min
]

SESSION_TOTAL_S: int = sum(d for _, d in BLOCKS)  # 1200 s = 20 min


class LangSession:
    """Timer sequencer for a 20-minute language session.

    Caller drives the clock by calling tick() at regular intervals.
    Callbacks run synchronously in the calling thread — use after(0, ...) around them
    when invoking from a Tkinter widget.
    """

    def __init__(
        self,
        profile: dict,
        lesson_data: dict,
        on_block_change,           # callable(name: str, index: int)
        on_session_end,            # callable(summary: dict)
        on_repetition_start=None,  # callable() — fired when repetition block begins
    ) -> None:
        self._profile = profile
        self._lesson_data = lesson_data
        self._on_block_change = on_block_change
        self._on_session_end = on_session_end
        self._on_repetition_start = on_repetition_start

        self._block_index: int = 0
        self._block_elapsed: float = 0.0
        self._total_elapsed: float = 0.0
        self._last_tick: float | None = None
        self._running: bool = False
        self._ended: bool = False

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._last_tick = time.monotonic()
        self._on_block_change(BLOCKS[0][0], 0)

    def tick(self) -> None:
        if not self._running or self._ended:
            return

        now = time.monotonic()
        delta = now - (self._last_tick or now)
        self._last_tick = now

        self._total_elapsed += delta
        self._block_elapsed += delta

        block_duration = BLOCKS[self._block_index][1]
        if self._block_elapsed >= block_duration:
            self._next_block()

    def stop(self) -> dict:
        self._running = False
        return self._build_summary()

    def force_next_block(self) -> None:
        if not self._running or self._ended:
            return
        self._next_block()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def current_block(self) -> str:
        return BLOCKS[self._block_index][0]

    @property
    def block_index(self) -> int:
        return self._block_index

    @property
    def block_progress(self) -> float:
        duration = BLOCKS[self._block_index][1]
        return min(1.0, self._block_elapsed / duration) if duration > 0 else 1.0

    @property
    def elapsed_total(self) -> float:
        return self._total_elapsed

    @property
    def is_running(self) -> bool:
        return self._running and not self._ended

    # ── Internal ──────────────────────────────────────────────────────────────

    def _next_block(self) -> None:
        self._block_elapsed = 0.0
        next_index = self._block_index + 1

        if next_index >= len(BLOCKS):
            self._ended = True
            self._running = False
            self._on_session_end(self._build_summary())
            return

        self._block_index = next_index
        block_name = BLOCKS[next_index][0]

        if block_name == "repetition" and self._on_repetition_start is not None:
            self._on_repetition_start()

        self._on_block_change(block_name, next_index)

    def _build_summary(self) -> dict:
        return {
            "profile_id": self._profile.get("id"),
            "lesson_n": self._profile.get("current_lesson", 1),
            "duration_s": int(self._total_elapsed),
            "score": 0.0,  # enriched in Plan 4 when exercises are scored
        }
