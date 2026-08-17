# services/intervention.py — Politique d'intervention autonome de l'assistant.
#
# Surveille la lecture (temps sur page, retours, jauges, densité mathématique,
# questions répétées) et demande au LLM une décision structurée
# {should_intervene, kind, message, question}. Les cooldowns global et par page
# évitent un assistant trop bavard ; le mode « discret » coupe tout.
#
# UI-agnostique : tout entre et sort par callbacks, et TOUS les seuils viennent
# de `config/settings.py` — c'est la source de vérité unique de la cadence de
# Gemma. Ne jamais réintroduire de valeur en dur ici ou chez un appelant.
from __future__ import annotations

import logging
import re
import time
from typing import Callable

from config.settings import (
    ASSISTANT_DWELL_TRIGGER_S,
    ASSISTANT_GLOBAL_COOLDOWN,
    ASSISTANT_LOW_ATTENTION,
    ASSISTANT_MAX_INTERVENTIONS,
    ASSISTANT_PAGE_COOLDOWN,
    ASSISTANT_QUESTIONS_TRIGGER,
    ASSISTANT_REVISIT_TRIGGER,
    ASSISTANT_WARMUP_S,
)
from services.session_memory import SessionMemory

logger = logging.getLogger("services.intervention")

INTERVENTION_KINDS = {"offer_help", "ask_question", "suggest_pause", "rephrase_offer", "review_flashcard"}

# Densité de symboles mathématiques au-delà de laquelle une page est jugée « dure ».
_MATH_CHARS_RE = re.compile(r"[=∑∫√±×÷≈≤≥∂∇λμσΩπθ^_{}\\]|\b[a-z]\([a-z]\)")
_MATH_DENSITY_THRESHOLD = 0.02
_MIN_DWELL_FOR_SOFT_TRIGGERS = 30.0
_DECLINED_COOLDOWN = 90.0


class AssistantInterventionPolicy:
    def __init__(
        self,
        memory: SessionMemory,
        get_mode: Callable[[], str],
        get_gauges: Callable[[], dict],
        get_current_page: Callable[[], int],
        get_page_text: Callable[[int], str],
        request_decision: Callable[[dict, Callable[[dict | None], None]], None],
        on_intervention: Callable[[dict], None],
        get_due_flashcard: Callable[[], dict | None] | None = None,
    ):
        self._memory = memory
        self._get_mode = get_mode
        self._get_gauges = get_gauges
        self._get_current_page = get_current_page
        self._get_page_text = get_page_text
        self._request_decision = request_decision
        self._on_intervention = on_intervention
        self._get_due_flashcard = get_due_flashcard

        self._busy = False
        self._pending = False
        self._last_global = 0.0
        self._last_by_page: dict[int, float] = {}
        self._fired_reasons: set[tuple[int, str]] = set()
        self._interventions_count = 0
        self._due_card: dict | None = None
        self._flashcard_prompted = False
        self._opened_at = time.monotonic()
        self._warmed_up = False

    # ------------------------------------------------------------------
    # Notifications externes
    # ------------------------------------------------------------------
    def set_busy(self, busy: bool) -> None:
        """L'assistant est occupé (réponse en cours, question Q&R active…)."""
        self._busy = busy

    def reset(self) -> None:
        self._busy = False
        self._pending = False
        self._last_global = 0.0
        self._last_by_page.clear()
        self._fired_reasons.clear()
        self._interventions_count = 0
        self._due_card = None
        self._flashcard_prompted = False
        self._opened_at = time.monotonic()
        self._warmed_up = False

    # ------------------------------------------------------------------
    # Boucle de décision
    # ------------------------------------------------------------------
    def tick(self) -> None:
        mode = self._get_mode()
        if mode == "discret" or self._busy or self._pending:
            return
        if self._interventions_count >= ASSISTANT_MAX_INTERVENTIONS:
            return

        now = time.monotonic()
        # Warm-up de début de lecture : silence le temps que le lecteur entre dans le
        # document. Une fois écoulé, le verrou est posé pour la session et seuls les
        # cooldowns par mode gouvernent.
        if not self._warmed_up:
            if now - self._opened_at < ASSISTANT_WARMUP_S.get(mode, 180.0):
                return
            self._warmed_up = True
        if now - self._last_global < ASSISTANT_GLOBAL_COOLDOWN.get(mode, 240.0):
            return

        page = self._get_current_page()
        if page < 1:
            return
        if now - self._last_by_page.get(page, 0.0) < ASSISTANT_PAGE_COOLDOWN.get(mode, 600.0):
            return

        reason = self._detect_trigger(page, mode, now)
        if reason is None or (page, reason) in self._fired_reasons:
            return

        self._fired_reasons.add((page, reason))
        self._pending = True
        logger.info("Intervention candidate page=%s raison=%s mode=%s", page, reason, mode)

        context = {
            "trigger": reason,
            "page": page,
            "page_text": (self._get_page_text(page) or "")[:2500],
            "gauges": self._get_gauges(),
            "dwell_s": round(self._memory.current_dwell(now), 1),
            "visits": self._memory.visits(page),
            "user_questions_on_page": self._memory.questions_on(page),
            "mode": mode,
        }
        if reason == "flashcard_due" and self._due_card:
            context["due_flashcard_front"] = str(self._due_card.get("front") or "")

        def _on_done(decision: dict | None) -> None:
            self._handle_decision(decision, page)

        try:
            self._request_decision(context, _on_done)
        except Exception as exc:
            logger.debug("Décision d'intervention impossible : %s", exc)
            self._pending = False

    def _handle_decision(self, decision: dict | None, trigger_page: int) -> None:
        self._pending = False
        now = time.monotonic()
        if not decision or not decision.get("should_intervene"):
            # Le LLM a jugé l'intervention inutile : petit cooldown quand même.
            self._last_global = max(self._last_global, now - ASSISTANT_GLOBAL_COOLDOWN.get(self._get_mode(), 240.0) + _DECLINED_COOLDOWN)
            return

        kind = str(decision.get("kind") or "offer_help")
        if kind not in INTERVENTION_KINDS:
            kind = "offer_help"
        if kind == "review_flashcard" and not self._due_card:
            kind = "offer_help"

        self._last_global = now
        self._last_by_page[trigger_page] = now
        self._interventions_count += 1
        self._on_intervention({
            "kind": kind,
            "message": str(decision.get("message") or "").strip(),
            "question": str(decision.get("question") or "").strip(),
            "page": trigger_page,
            "highlights": list(decision.get("highlights") or []),
            "flashcard": self._due_card if kind == "review_flashcard" else None,
        })

    # ------------------------------------------------------------------
    # Déclencheurs
    # ------------------------------------------------------------------
    def _detect_trigger(self, page: int, mode: str, now: float) -> str | None:
        dwell = self._memory.current_dwell(now)

        if self._memory.questions_on(page) >= ASSISTANT_QUESTIONS_TRIGGER:
            return "repeated_questions"

        if dwell >= ASSISTANT_DWELL_TRIGGER_S.get(mode, 150.0):
            return "long_dwell"

        if dwell < _MIN_DWELL_FOR_SOFT_TRIGGERS:
            return None

        if self._get_due_flashcard is not None and not self._flashcard_prompted:
            try:
                card = self._get_due_flashcard()
            except Exception:
                card = None
            if card:
                # Une seule proposition de révision par session.
                self._flashcard_prompted = True
                self._due_card = dict(card)
                return "flashcard_due"

        if self._memory.visits(page) >= ASSISTANT_REVISIT_TRIGGER:
            return "page_revisits"

        try:
            attention = float(self._get_gauges().get("attention", 100.0))
        except (TypeError, ValueError):
            attention = 100.0
        if attention < ASSISTANT_LOW_ATTENTION:
            return "low_attention"

        if _is_math_heavy(self._get_page_text(page) or ""):
            return "hard_page"

        return None


def _is_math_heavy(text: str) -> bool:
    if len(text) < 200:
        return False
    matches = len(_MATH_CHARS_RE.findall(text))
    return (matches / max(1, len(text))) >= _MATH_DENSITY_THRESHOLD
