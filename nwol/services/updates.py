# services/updates.py — Vérification des mises à jour. LE SEUL APPEL SORTANT.
#
# ─────────────────────────────────────────────────────────────────────────────
# DÉROGATION EXPLICITE à la règle de l'édition locale (« aucun appel réseau
# au-delà de 127.0.0.1:11434 », cf. CLAUDE.md § Éditions et
# architecture/13-mises-a-jour-et-distribution.md). Un seul GET, vers un seul
# hôte, DÉSACTIVÉ PAR DÉFAUT, jamais joué sans un oui explicite de
# l'utilisateur. Aucun identifiant, aucune télémétrie, aucun paramètre de
# requête : la requête elle-même est tout ce qui part.
# ─────────────────────────────────────────────────────────────────────────────
#
# La réponse de GitHub est une ENTRÉE NON FIABLE. Elle est traitée comme telle :
#
#   1. L'URL de téléchargement est EN DUR ici. Ni `html_url` ni
#      `browser_download_url` de la réponse ne sont jamais ouverts : sur macOS,
#      `webbrowser.open()` passe par `open(1)`, qui honore `file://` et les
#      schémas d'application arbitraires. Un MITM, ou un compte GitHub
#      compromis, y gagnerait une primitive d'exécution locale. De la réponse on
#      n'extrait QUE le numéro de version.
#   2. Ce numéro est validé par une regex stricte avant tout usage, tout
#      stockage et tout affichage.
#   3. Les notes de version ne sont PAS remontées. Du markdown non fiable rendu
#      dans un webview qui expose `window.pywebview.api` est un XSS avec une
#      surface d'exécution native derrière.
#   4. TLS strict, aucune redirection suivie (l'hôte est connu et fixe), timeout
#      court, échec SILENCIEUX — une panne de GitHub ne doit ni bloquer l'app ni
#      alerter l'utilisateur.
#   5. Aucun paramètre d'entrée : ni URL, ni hôte, ni version. Un endpoint local
#      qui accepterait une URL serait un SSRF joignable par n'importe quel
#      processus de la machine.
#
# Ce que le code NE couvre pas : si le compte GitHub est compromis, une release
# malveillante sera installée volontairement par les utilisateurs. Les
# contre-mesures sont organisationnelles (2FA matérielle, signature +
# notarisation des builds) et documentées dans architecture/13. C'est aussi
# pourquoi il n'y a pas de téléchargement ni d'installation automatiques : sans
# vérification de signature de l'artefact, un updater automatique EST une porte
# dérobée.
from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.error
import urllib.request

from server.config import APP_VERSION
from services.preferences import get_bool

logger = logging.getLogger("services.updates")

__all__ = ["check_for_update", "RELEASES_PAGE", "LATEST_RELEASE_API"]

# Hôte et chemin figés dans le binaire. Rien de tout cela ne vient de la réponse.
LATEST_RELEASE_API = "https://api.github.com/repos/cyyyp100/meta-capp/releases/latest"
# La SEULE URL que l'application ouvrira jamais dans le navigateur système.
RELEASES_PAGE = "https://github.com/cyyyp100/meta-capp/releases/latest"

# Une version, et rien d'autre. Pas de schéma, pas de chemin, pas d'espace.
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")

# Court : une vérification de mise à jour n'a le droit de faire attendre personne.
TIMEOUT_S = 4.0
# La réponse de l'API releases fait quelques kilo-octets. Au-delà, on abandonne
# plutôt que de charger en mémoire ce qu'un hôte hostile voudrait y mettre.
MAX_BYTES = 256 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Aucune redirection suivie : l'hôte est connu, fixe et final.

    Suivre une 302 revient à laisser la réponse choisir la prochaine cible —
    c'est-à-dire à rendre à un attaquant le contrôle qu'on vient de lui retirer
    en figeant l'URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def check_for_update() -> dict:
    """État de mise à jour. Ne lève jamais, ne bloque jamais.

    Renvoie toujours la même forme :
      {"enabled", "current", "latest", "update_available", "url", "checked"}

    - `enabled=False` (l'état par défaut) → aucune requête n'est émise, point.
    - `checked=False` → la requête a échoué (hors ligne, panne, réponse
      illisible) ; l'appelant n'affiche rien. Un échec de vérification n'est pas
      un événement pour l'utilisateur.
    - `url` est TOUJOURS `RELEASES_PAGE`, jamais une URL issue de la réponse."""
    base = {
        "enabled": False,
        "current": APP_VERSION,
        "latest": None,
        "update_available": False,
        "url": RELEASES_PAGE,
        "checked": False,
    }
    if not _enabled():
        return base
    base["enabled"] = True

    latest = _fetch_latest_version()
    if latest is None:
        return base
    base["latest"] = latest
    base["checked"] = True
    base["update_available"] = _is_newer(latest, APP_VERSION)
    return base


def _enabled() -> bool:
    try:
        return get_bool("updates_check")
    except Exception:  # base illisible : on ne sort pas sur le réseau « au cas où »
        logger.debug("Drapeau de mise à jour illisible, vérification abandonnée", exc_info=True)
        return False


def _fetch_latest_version() -> str | None:
    """Un GET, un seul, et on n'en garde que le numéro de version.

    `ssl.create_default_context()` vérifie la chaîne ET le nom d'hôte. Rien ici
    ne doit jamais le désactiver, même temporairement pour déboguer : ce serait
    rendre la réponse — donc l'URL, donc l'exécution — modifiable en transit."""
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            # Un User-Agent est exigé par l'API GitHub. Il ne porte QUE le nom du
            # produit et sa version : ni identifiant machine, ni identifiant
            # d'installation, rien qui permette de suivre quelqu'un.
            "User-Agent": f"Meta-Capp/{APP_VERSION}",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(
        _NoRedirect,
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with opener.open(request, timeout=TIMEOUT_S) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read(MAX_BYTES).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        # Hors ligne, TLS refusé, redirection, JSON illisible : silence complet.
        logger.debug("Vérification de mise à jour sans réponse exploitable", exc_info=True)
        return None

    if not isinstance(payload, dict):
        return None
    return _clean_version(payload.get("tag_name") or payload.get("name"))


def _clean_version(raw: object) -> str | None:
    """N'accepte qu'un `1.4` ou `v1.4.2`. Tout le reste est jeté.

    C'est la seule donnée de la réponse qui entre dans l'application : elle est
    donc validée avant d'exister, et pas au moment de l'afficher."""
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if len(candidate) > 32 or not VERSION_RE.match(candidate):
        return None
    return candidate.lstrip("v")


def _is_newer(latest: str, current: str) -> bool:
    """Comparaison numérique. Une version courante illisible → aucune proposition.

    `APP_VERSION` vaut aujourd'hui « 1.3-web » : la regex la rejette, et on
    préfère ne rien proposer plutôt que d'annoncer une mise à jour à partir d'une
    comparaison qu'on ne sait pas faire."""
    left, right = _parts(latest), _parts(current)
    if left is None or right is None:
        return False
    return left > right


def _parts(version: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.match((version or "").strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)
