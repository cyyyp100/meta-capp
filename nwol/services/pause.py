# services/pause.py — Les pauses de lecture : ce qu'on mesure quand tout s'arrête.
#
# Pendant une pause, le lecteur fige TOUT : dérive passive d'attention, dwell,
# interventions, horloges de warm-up et de cooldown. Il ne reste à mesurer que
# la pause elle-même :
#
#   * sa durée (de l'arrêt à la reprise — la pause est ouverte, c'est l'élève
#     qui revient, pas un décompte qui le ramène) ;
#   * sa source : le bouton « Pause » de l'élève (`manual`) ou la carte de
#     Gemma acceptée (`suggested`) ;
#   * si elle SUIT une recommandation du LLM, laquelle et avec quel délai.
#
# UI-agnostique : le routeur du lecteur ne fait que relayer les événements
# (pause, reprise, intervention émise) et persister le résultat. La règle
# « après une recommandation » et le crédit d'attention vivent ici, seuls.
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime

from config.settings import PAUSE_ATTENTION_RECOVERY, PAUSE_RECOMMENDATION_WINDOW_S

PAUSE_SOURCES = ("manual", "suggested")


@dataclass(frozen=True)
class PauseRecord:
    """Une pause terminée, telle qu'elle est persistée (`session_pauses`)."""

    started_at: str
    page: int | None
    duration_s: float
    planned_s: float | None
    source: str
    after_recommendation: bool
    recommendation_kind: str | None
    recommendation_delay_s: float | None
    attention_at_start: float | None
    ended_by: str

    def as_row(self) -> dict:
        return asdict(self)


class PauseTracker:
    """État de pause d'UNE connexion de lecture.

    Toutes les horloges passées en `now` sont `time.monotonic()` : injectables
    pour les tests, comme dans `SessionMemory`. Seul `started_at` est une date
    murale, pour l'affichage."""

    def __init__(self) -> None:
        # Dernière recommandation du LLM : (type, instant). Écrite depuis le
        # thread de callback LLM ; l'affectation d'un tuple est atomique.
        self._last_recommendation: tuple[str, float] | None = None
        self._open: dict | None = None

    @property
    def active(self) -> bool:
        return self._open is not None

    def note_recommendation(self, kind: str, now: float | None = None) -> None:
        """Une recommandation du LLM vient d'atteindre l'élève.

        Toute intervention autonome (`suggest_pause`, `offer_help`,
        `ask_question`…) et le conseil de séance (`session_hint`) d'une question.
        Seule la dernière compte : c'est elle que l'élève a sous les yeux."""
        if kind:
            self._last_recommendation = (str(kind), time.monotonic() if now is None else now)

    def start(
        self,
        now: float | None = None,
        *,
        source: str = "manual",
        planned_s: float | None = None,
        page: int | None = None,
        attention: float | None = None,
    ) -> bool:
        """Ouvre une pause. False si une pause est déjà en cours (sans effet)."""
        if self._open is not None:
            return False
        now = time.monotonic() if now is None else now
        source = source if source in PAUSE_SOURCES else "manual"
        kind: str | None = None
        delay: float | None = None
        if self._last_recommendation is not None:
            kind = self._last_recommendation[0]
            delay = round(max(0.0, now - self._last_recommendation[1]), 1)
        self._open = {
            "mono": now,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "page": page,
            # Une durée conseillée n'a de sens que pour la carte de Gemma.
            "planned_s": float(planned_s) if source == "suggested" and planned_s else None,
            "source": source,
            # Accepter la carte EST suivre la recommandation ; sinon, il faut
            # qu'une recommandation soit arrivée dans la fenêtre.
            "after_recommendation": source == "suggested"
            or (delay is not None and delay <= PAUSE_RECOMMENDATION_WINDOW_S),
            "recommendation_kind": kind,
            "recommendation_delay_s": delay,
            "attention_at_start": None if attention is None else round(float(attention), 1),
        }
        return True

    def stop(self, now: float | None = None, ended_by: str = "resume") -> PauseRecord | None:
        """Ferme la pause en cours et la renvoie (None s'il n'y en avait pas)."""
        if self._open is None:
            return None
        now = time.monotonic() if now is None else now
        opened, self._open = self._open, None
        return PauseRecord(
            started_at=opened["started_at"],
            page=opened["page"],
            duration_s=round(max(0.0, now - opened["mono"]), 1),
            planned_s=opened["planned_s"],
            source=opened["source"],
            after_recommendation=bool(opened["after_recommendation"]),
            recommendation_kind=opened["recommendation_kind"],
            recommendation_delay_s=opened["recommendation_delay_s"],
            attention_at_start=opened["attention_at_start"],
            ended_by=ended_by,
        )


def attention_credit(record: PauseRecord) -> float:
    """Crédit d'attention versé au retour d'une pause.

    Seule la pause CONSEILLÉE et reprise en crédite une, au prorata du temps
    pris sur la durée conseillée : une reprise au bout de dix secondes n'est pas
    un repos, sans quoi « accepter puis reprendre » remonterait la jauge
    gratuitement. Une pause manuelle est neutre, et une pause interrompue par la
    fin de séance ne crédite rien — il n'y a plus de lecture à mesurer."""
    if record.source != "suggested" or record.ended_by != "resume" or not record.planned_s:
        return 0.0
    ratio = max(0.0, min(1.0, record.duration_s / record.planned_s))
    return PAUSE_ATTENTION_RECOVERY * ratio


def summarize(pauses: list[dict]) -> dict:
    """Agrégat d'une séance : nombre, temps total, pauses après recommandation."""
    return {
        "pauses": len(pauses),
        "pause_s": int(round(sum(float(p.get("duration_s") or 0.0) for p in pauses))),
        "pauses_after_recommendation": sum(1 for p in pauses if p.get("after_recommendation")),
    }
