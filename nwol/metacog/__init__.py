# metacog — Profil et signaux métacognitifs MetaC-App
from metacog.gauges import GaugeState, make_gauges
from metacog.profile import compute_alpha, update_profile
from metacog.signals import compute_session_score

__all__ = [
    "GaugeState",
    "make_gauges",
    "compute_alpha",
    "update_profile",
    "compute_session_score",
]
