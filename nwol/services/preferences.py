# services/preferences.py — Réglages d'application (surface /settings).
#
# UNE déclaration, une seule, de ce qu'est un réglage : son nom, ses valeurs
# admises, sa valeur par défaut. Le routeur ne fait que passer un dict ; il ne
# connaît ni les clés ni leurs bornes (cf. CLAUDE.md : la politique vit dans un
# service, jamais dans un routeur).
#
# Pourquoi la base plutôt que le `localStorage` du webview : ces réglages font
# partie des données de l'utilisateur. Le thème choisi, la visite guidée déjà
# faite, l'accord donné pour la vérification de mise à jour — tout cela doit
# survivre à « Restaurer une sauvegarde », et le stockage du navigateur embarqué
# n'est pas dans le fichier `.db` exporté.
#
# La LANGUE n'est pas ici : elle vit sur `user.lang` parce qu'elle pilote aussi
# les prompts LLM (`i18n.set_lang`), et elle garde son endpoint dédié.
from __future__ import annotations

import logging
from dataclasses import dataclass

from db.app_settings import get_settings, set_setting

logger = logging.getLogger("services.preferences")

__all__ = ["PREFERENCES", "get_preferences", "update_preferences", "get_bool", "set_bool"]


@dataclass(frozen=True)
class Pref:
    """Un réglage : sa valeur par défaut et le domaine qui l'accepte.

    `choices=None` + `kind="bool"` décrit un drapeau ; `choices` décrit une
    énumération fermée. Aucun réglage n'est du texte libre : une clé inconnue ou
    une valeur hors domaine est refusée, jamais persistée telle quelle."""

    key: str
    default: str
    kind: str = "enum"
    choices: tuple[str, ...] = ()


PREFERENCES: dict[str, Pref] = {
    # « system » suit le thème de l'OS : c'est l'option qui manquait, et la seule
    # raison pour laquelle `prefers-color-scheme` existait dans tokens.css sans
    # que rien ne puisse la choisir.
    "theme": Pref("theme", "light", choices=("light", "dark", "system")),
    "density": Pref("density", "comfortable", choices=("comfortable", "compact")),
    "text_size": Pref("text_size", "normal", choices=("small", "normal", "large")),
    # Vérification des mises à jour : DÉSACTIVÉE PAR DÉFAUT. C'est le seul appel
    # sortant de l'édition locale ; il ne part jamais sans un oui explicite.
    "updates_check": Pref("updates_check", "false", kind="bool"),
    # Visite guidée du premier lancement. DEUX réglages et non un :
    #   * `tour_done` — terminée ou refusée définitivement, on n'y revient plus ;
    #   * `tour_step` — l'étape la plus avancée déjà montrée, pour qu'une visite
    #     interrompue reprenne où elle en était au lieu de rejouer sa première
    #     bulle à chaque lancement.
    # Le second est en base et non dans le `localStorage` pour la même raison que
    # le reste : le stockage du webview ne survit pas à une restauration de
    # sauvegarde, et la visite recommencerait alors chez quelqu'un qui l'a faite.
    "tour_done": Pref("tour_done", "false", kind="bool"),
    "tour_step": Pref(
        "tour_step", "none",
        choices=("none", "import", "gemma", "intervention", "exit", "profil"),
    ),
}


def get_preferences() -> dict[str, str]:
    """Tous les réglages, complétés par leurs valeurs par défaut.

    Une valeur stockée devenue invalide (clé retirée d'une énumération entre deux
    versions) retombe sur le défaut plutôt que de remonter telle quelle."""
    stored = _safe_read()
    return {key: _coerce(pref, stored.get(key)) for key, pref in PREFERENCES.items()}


def update_preferences(patch: dict[str, object]) -> dict[str, str]:
    """Applique un patch partiel et renvoie l'état complet après écriture.

    Lève `ValueError` sur une clé inconnue ou une valeur hors domaine : un
    réglage refusé doit être une erreur visible, pas un silence qui laisse
    l'interface croire qu'elle a enregistré quelque chose."""
    for raw_key, raw_value in (patch or {}).items():
        pref = PREFERENCES.get(str(raw_key))
        if pref is None:
            raise ValueError(f"Réglage inconnu : {raw_key}")
        set_setting(pref.key, _validate(pref, raw_value))
    logger.info("Réglages mis à jour : %s", ", ".join(sorted(map(str, (patch or {})))))
    return get_preferences()


def get_bool(key: str) -> bool:
    """Lecture typée d'un drapeau — le chemin qu'utilisent les services."""
    pref = PREFERENCES[key]
    if pref.kind != "bool":
        raise ValueError(f"{key} n'est pas un drapeau")
    return _coerce(pref, _safe_read().get(key)) == "true"


def set_bool(key: str, value: bool) -> None:
    update_preferences({key: bool(value)})


def _safe_read() -> dict[str, str]:
    try:
        return get_settings()
    except Exception:  # base absente/verrouillée : les défauts font l'affaire
        logger.debug("Lecture des réglages impossible, défauts appliqués", exc_info=True)
        return {}


def _validate(pref: Pref, value: object) -> str:
    if pref.kind == "bool":
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "on"):
            return "true"
        if text in ("false", "0", "no", "off"):
            return "false"
        raise ValueError(f"Valeur booléenne attendue pour {pref.key} : {value!r}")
    text = str(value).strip().lower()
    if text not in pref.choices:
        raise ValueError(f"Valeur non admise pour {pref.key} : {value!r}")
    return text


def _coerce(pref: Pref, stored: str | None) -> str:
    if stored is None:
        return pref.default
    try:
        return _validate(pref, stored)
    except ValueError:
        return pref.default
