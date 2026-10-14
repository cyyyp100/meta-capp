# services/llm_models.py — Quel modèle fait tourner Clikoda, et peut-il tourner ?
#
# Le modèle était un nom en dur (`config/settings.OLLAMA_MODEL`), figé dans 31
# valeurs par défaut d'argument évaluées à l'import de `llm/ollama_client` : rien
# ne pouvait le changer, et sur une machine qui ne pouvait pas le charger,
# Clikoda se taisait sans jamais dire pourquoi. Ce module est la réponse aux
# trois questions que personne ne posait : quel modèle tourne, tient-il dans
# cette machine, et que dire à l'étudiant quand non.
#
# Et une quatrième, depuis le palier minuscule : faut-il économiser ? Le mode
# économe (`economy()`) se décide ici, une fois, et tout le reste n'en lit que
# la réponse (cf. config/settings.py, § Mode économe).
#
# Il vit dans `services/` et non dans `llm/` pour deux raisons :
#   1. c'est une POLITIQUE, et elle lit une préférence en base (`llm_model` →
#      `db/app_settings`) — cf. CLAUDE.md, « la politique vit dans un service » ;
#   2. rien, dans `nwol/llm/`, ne touche `db/` : y mettre cette table ferait
#      descendre la base de données d'un étage, dans la couche transport.
#
# ⚠️ Les cycles d'import sont RÉELS et tous fermés dans des corps de fonction,
# comme `settings._slowdown()` le fait déjà. Personne ne doit les « nettoyer »
# en imports de module :
#       config.settings     → (tardif) services.llm_models.active_profile() / economy()
#       llm.throughput      → (tardif) services.llm_models.profile()
#       services.llm_models → (tardif) llm.ollama_client.list_models()
#       services.llm_models → (tardif) llm.throughput.slowdown() (wait_estimate_s)
#
# Et rien ici ne lève : un budget temps, une génération ou l'écran de réglages
# n'ont pas le droit d'échouer parce qu'Ollama est éteint ou la base verrouillée.
from __future__ import annotations

import logging
import os
import threading
import time

from config.settings import (
    LLM_ECONOMY_AUTO,
    LLM_ECONOMY_RAM_GB,
    LLM_MODEL_AUTO,
    LLM_MODELS,
    LLM_REFERENCE_PROFILE,
    LLM_SLOW_MACHINE_FACTOR,
    LLM_TAGS_CACHE_TTL_S,
    OLLAMA_MODEL,
    ModelProfile,
)
from services import preferences

logger = logging.getLogger("services.llm_models")

__all__ = [
    "MODELS", "active", "active_profile", "auto_pick", "economy", "economy_decision",
    "economy_preference", "economy_reason", "fits", "host_ram_gb", "installed", "invalidate", "preference",
    "profile", "refresh_active", "resolve", "status", "tier", "wait_estimate_s",
]

# Ré-export : le catalogue est déclaré avec les autres faits du modèle
# (`config/settings.py`), pas ici. Ce module en décide l'usage.
MODELS = LLM_MODELS

# Raisons pour lesquelles Clikoda ne répond pas — une énumération FERMÉE, parce
# que les phrases qui les expliquent doivent vivre dans un seul couple de
# dictionnaires i18n (celui du front), et pas en double.
REASONS = ("ollama_down", "model_missing", "model_too_big", "no_model")
# Pourquoi le mode économe est actif — même règle : une énumération, des mots
# dans les dictionnaires. `None` = mode économe coupé.
ECONOMY_REASONS = ("preference", "tiny_model", "low_ram")

_LOCK = threading.Lock()
# Catalogue d'Ollama, mis en cache : `active()` est appelé à chaque génération et
# à chaque calcul de budget (cf. LLM_TAGS_CACHE_TTL_S).
_catalog_cache: dict = {"at": 0.0, "reachable": False, "installed": []}
# `None` est une réponse de première classe pour la RAM (« inconnue ») : il faut
# donc un autre témoin pour « pas encore mesurée ».
_UNMEASURED = object()
_ram_gb: object = _UNMEASURED
# Un modèle n'est calibré qu'une fois par lancement (`refresh_active`).
_calibrated: set[str] = set()
_last_logged = ""


# ── Les faits ────────────────────────────────────────────────────────────────


def profile(model: str) -> ModelProfile:
    """Profil d'un modèle — JAMAIS None. Un modèle installé que la table ignore
    (l'utilisateur a choisi le sien dans Ollama) garde les budgets de la
    référence plutôt que pas de budget du tout."""
    return LLM_MODELS.get(_canonical(model)) or LLM_REFERENCE_PROFILE


def tier(model: str) -> str:
    return profile(model).tier


def fits(model: str, ram_gb: float | None) -> bool:
    """Cette machine peut-elle charger ce modèle ? RAM inconnue → oui : un
    inconnu n'est pas un refus (cf. `host_ram_gb`)."""
    if ram_gb is None:
        return True
    return ram_gb + 1e-9 >= profile(model).min_ram_gb


def host_ram_gb() -> float | None:
    """RAM totale de la machine, en Gio, ou None si on ne sait pas.

    Sans psutil (absent de `requirements.txt`, et l'y ajouter pour quinze lignes
    toucherait aussi `desktop/metacapp.spec`) : `sysconf` sous Unix,
    `GlobalMemoryStatusEx` sous Windows. Surtout pas l'ancienne `MEMORYSTATUS`,
    dont le champ sature à 4 Gio — soit exactement la machine qu'on cherche à
    reconnaître. None n'est JAMAIS traité comme 0 : le choix automatique prend
    alors le plus gros modèle installé plutôt que de tout refuser. Mesurée une
    fois par processus."""
    global _ram_gb
    if _ram_gb is not _UNMEASURED:
        return _ram_gb  # type: ignore[return-value]
    _ram_gb = _measure_ram_gb()
    logger.info("RAM de la machine : %s Gio", round(_ram_gb, 1) if _ram_gb else "inconnue")
    return _ram_gb  # type: ignore[return-value]


def _measure_ram_gb() -> float | None:
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        if total > 0:
            return total / 1024 ** 3
    except (AttributeError, ValueError, OSError):
        pass  # `sysconf` absent (Windows) ou nom inconnu
    if os.name == "nt":
        try:
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return float(status.ullTotalPhys) / 1024 ** 3
        except Exception:  # pragma: no cover - dépend de l'OS
            logger.debug("RAM de la machine illisible", exc_info=True)
    return None


def installed(*, refresh: bool = False) -> list[dict]:
    """Modèles qu'Ollama a en magasin : `name` (tag canonique), `size_gb`,
    `parameter_size`, `known` (la table le connaît-elle). Liste vide si Ollama
    ne répond pas — `status()["ollama_up"]` fait la différence."""
    return list(_catalog(refresh=refresh)["installed"])


def invalidate() -> None:
    """Oublie le catalogue (changement de préférence, tests)."""
    with _LOCK:
        _catalog_cache.update(at=0.0, reachable=False, installed=[])


# ── La politique, en deux fonctions PURES ────────────────────────────────────


def auto_pick(names: list[str], ram_gb: float | None) -> str:
    """Choix AUTOMATIQUE : le modèle le mieux classé parmi ceux qui sont
    installés, connus, et que la machine peut charger. Chaîne vide si aucun
    modèle connu n'est installé.

    Pure — ni HTTP, ni base : c'est la décision la plus importante du module, et
    elle se teste seule. Le tri est sur `rank` et JAMAIS sur la taille du
    téléchargement : `gemma4:12b` pèse moins que `gemma4:e4b` tout en répondant
    mieux. Si rien ne tient dans la RAM, on prend le plus petit installé plutôt
    que de se taire : un modèle trop lourd qui rame reste préférable à pas de
    Clikoda du tout, et `status()` dit pourquoi c'est lent (`model_too_big`)."""
    known = [LLM_MODELS[name] for name in {_canonical(n) for n in names} if name in LLM_MODELS]
    if not known:
        return ""
    fitting = [p for p in known if fits(p.name, ram_gb)]
    if fitting:
        return max(fitting, key=lambda p: p.rank).name
    return min(known, key=lambda p: p.rank).name


def resolve(preference_value: str, names: list[str], ram_gb: float | None) -> dict:
    """Du réglage au modèle qui tournera vraiment — pure, et seule écriture de
    cette logique.

    Ordre : (1) préférence explicite installée → elle, même trop lourde (c'est
    un choix, pas un accident : `reason` le signale sans rien bloquer) ;
    (2) préférence explicite absente du magasin → repli automatique, `reason`
    `model_missing` et le nom manquant conservé pour la commande `ollama pull` ;
    (3) « auto » → `auto_pick` ; (4) rien d'installé → le modèle de dernier
    recours, pour que les budgets restent définis et que le message ait un nom à
    citer."""
    canonical = {_canonical(name) for name in names}
    requested = (preference_value or LLM_MODEL_AUTO).strip().lower()
    requested_missing = None
    reason = None

    if requested != LLM_MODEL_AUTO and requested in canonical:
        model = requested
    elif requested != LLM_MODEL_AUTO:
        requested_missing = requested
        reason = "model_missing"
        model = auto_pick(list(canonical), ram_gb) or OLLAMA_MODEL
    else:
        model = auto_pick(list(canonical), ram_gb)
        if not model:
            model, reason = OLLAMA_MODEL, "no_model"

    # `auto_pick` ne rend qu'un nom issu de `canonical` : si on est ici sans
    # raison, le modèle est bien installé. Reste à savoir s'il tient.
    if reason is None and not fits(model, ram_gb):
        reason = "model_too_big"
    return {
        "model": model,
        "preference": requested,
        "requested_missing": requested_missing,
        "reason": reason,
        "fits": fits(model, ram_gb),
    }


# ── Le modèle actif ──────────────────────────────────────────────────────────


def preference() -> str:
    """Le réglage `llm_model` (« auto » par défaut), jamais une exception :
    sans base lisible, c'est « auto »."""
    try:
        return preferences.get_preferences().get("llm_model") or LLM_MODEL_AUTO
    except Exception:  # pragma: no cover - base absente/verrouillée
        logger.debug("Préférence de modèle illisible", exc_info=True)
        return LLM_MODEL_AUTO


def active() -> str:
    """Nom du modèle à utiliser — jamais « auto », jamais vide, SANS effet de
    bord : il est appelé depuis le worker LLM et depuis chaque calcul de budget.
    Les effets (journal, recalibrage) vivent dans `refresh_active()`."""
    try:
        return resolve(preference(), [e["name"] for e in installed()], host_ram_gb())["model"]
    except Exception:  # pragma: no cover - rien ici ne doit casser une génération
        logger.debug("Résolution du modèle impossible", exc_info=True)
        return OLLAMA_MODEL


def active_profile() -> ModelProfile:
    return profile(active())


# ── Le mode économe ──────────────────────────────────────────────────────────


def economy_decision(preference_value: str, model_tier: str, ram_gb: float | None) -> str | None:
    """Pourquoi le mode économe est actif (une de ECONOMY_REASONS), ou None.

    Pure, comme `resolve` : c'est la seule écriture de cette règle, et elle se
    teste seule. « on » et « off » sont des choix explicites, toujours
    respectés — il faut pouvoir forcer dans les deux sens : une machine de
    16 Go qui veut économiser sa batterie, une de 4 Go qui accepte d'attendre
    pour garder l'aide autonome. « auto » : le palier minuscule, ou une machine
    sous LLM_ECONOMY_RAM_GB. Une RAM inconnue n'active rien (`host_ram_gb`)."""
    value = (preference_value or LLM_ECONOMY_AUTO).strip().lower()
    if value == "on":
        return "preference"
    if value == "off":
        return None
    if model_tier == "tiny":
        return "tiny_model"
    if ram_gb is not None and ram_gb < LLM_ECONOMY_RAM_GB:
        return "low_ram"
    return None


def economy_preference() -> str:
    """Le réglage `llm_economy` (« auto » par défaut), jamais une exception."""
    try:
        return preferences.get_preferences().get("llm_economy") or LLM_ECONOMY_AUTO
    except Exception:  # pragma: no cover - base absente/verrouillée
        logger.debug("Préférence du mode économe illisible", exc_info=True)
        return LLM_ECONOMY_AUTO


def economy_reason() -> str | None:
    """`economy_decision` appliquée au modèle actif et à cette machine."""
    try:
        return economy_decision(economy_preference(), tier(active()), host_ram_gb())
    except Exception:  # pragma: no cover - un budget temps ne doit jamais échouer ici
        logger.debug("Décision du mode économe impossible", exc_info=True)
        return None


def economy() -> bool:
    """Le mode économe est-il actif ? Décidé ICI et nulle part ailleurs : les
    budgets (config/settings), la file (llm/ollama_client), l'aide autonome
    (services/intervention) et la recherche (services/pdf_rag) n'en lisent que
    la réponse. Sans effet de bord ; appelé à chaque calcul de budget."""
    return economy_reason() is not None


def wait_estimate_s(task: str) -> int | None:
    """L'attente à annoncer à l'étudiant pour `task`, en secondes — ou None
    quand il n'y a rien à annoncer.

    C'est le budget TOTAL de la tâche (`settings.task_wall_timeout_s`), celui
    après lequel le serveur renonce : un « au plus », honnête par construction,
    et le seul chiffre — l'interface n'en recalcule aucun. Annoncé en mode
    économe, ou quand la machine s'est révélée nettement plus lente que la
    référence de son modèle (LLM_SLOW_MACHINE_FACTOR) : sur une machine rapide,
    la réponse arrive avant qu'on ait lu l'annonce."""
    from config.settings import task_wall_timeout_s
    from llm import throughput

    try:
        slow = max(throughput.slowdown()) >= LLM_SLOW_MACHINE_FACTOR
        if not (slow or economy()):
            return None
        return int(round(task_wall_timeout_s(task)))
    except Exception:  # pragma: no cover - une annonce ne casse jamais une demande
        logger.debug("Estimation de l'attente impossible", exc_info=True)
        return None


def refresh_active() -> str:
    """Comme `active()`, mais c'est LA fonction à effets : elle rafraîchit le
    catalogue, journalise un changement de modèle et calibre le débit du nouveau
    modèle (une fois par lancement et par modèle).

    Appelée au démarrage (lifespan) et par `GET /api/llm/status`, c'est-à-dire
    juste après que l'interface a écrit la préférence : le recalibrage part là,
    explicitement, et pas dans un thread caché au milieu du chemin chaud."""
    global _last_logged
    invalidate()
    state = status()
    model = state["model"]
    # Le mode économe change les budgets de toutes les générations : il se lit
    # dans la même ligne que le modèle, et un changement de l'un OU de l'autre
    # se journalise.
    logged = f"{model}|{state['economy_reason']}"
    if logged != _last_logged:
        _last_logged = logged
        logger.info(
            "Modèle de Clikoda : %s (réglage %s, RAM %s Gio%s) — mode économe %s",
            model, state["preference"], state["ram_gb"],
            f", {state['reason']}" if state["reason"] else "",
            f"actif ({state['economy_reason']})" if state["economy"] else "coupé",
        )
    if state["available"] and model not in _calibrated:
        _calibrated.add(model)
        from llm.ollama_client import calibrate_throughput

        calibrate_throughput()
    return model


def status() -> dict:
    """Tout ce que l'interface (et le journal) doivent savoir de Clikoda.

    UN aller-retour vers Ollama (le catalogue, mis en cache) : `ollama_up` est
    « le catalogue a répondu », et non une seconde requête qui pourrait dire le
    contraire de la première. `reason` reste une énumération — les phrases
    vivent dans les dictionnaires i18n du front. `pull_command` n'est que du
    texte à copier : un bouton qui lancerait `ollama pull` serait un
    téléchargement réseau initié par l'application, et l'édition locale n'a
    qu'un seul appel sortant (`services/updates.py`)."""
    from llm import throughput

    state = _catalog()
    entries = state["installed"]
    names = [entry["name"] for entry in entries]
    ram_gb = host_ram_gb()
    resolution = resolve(preference(), names, ram_gb)
    model = resolution["model"]
    available = bool(state["reachable"] and model in names)
    economy_value = economy_preference()
    economy_why = economy_decision(economy_value, tier(model), ram_gb)
    return {
        "available": available,
        "ollama_up": bool(state["reachable"]),
        "model": model,
        "preference": resolution["preference"],
        "tier": tier(model),
        "supports_images": profile(model).supports_images,
        "installed": [{**entry, "fits": fits(entry["name"], ram_gb)} for entry in entries],
        "catalog": [
            {
                "name": p.name, "tier": p.tier, "download_gb": p.download_gb,
                "min_ram_gb": p.min_ram_gb, "installed": p.name in names,
                "fits": fits(p.name, ram_gb),
            }
            for p in LLM_MODELS.values()
        ],
        "ram_gb": round(ram_gb, 1) if ram_gb else None,
        "fits": resolution["fits"],
        # Ollama éteint rend les autres raisons muettes : inutile de signaler un
        # modèle « absent » d'un magasin qu'on n'a pas pu ouvrir.
        "reason": "ollama_down" if not state["reachable"] else resolution["reason"],
        "requested_missing": resolution["requested_missing"],
        # La commande cite ce qu'il MANQUE : quand la préférence nomme un modèle
        # jamais tiré, c'est celui-là qu'il faut installer, pas le repli qui
        # tourne en attendant.
        "pull_command": f"ollama pull {resolution['requested_missing'] or model}",
        "throughput": throughput.snapshot(model),
        # Le mode économe, son réglage et sa raison (une de ECONOMY_REASONS).
        "economy": economy_why is not None,
        "economy_preference": economy_value,
        "economy_reason": economy_why,
    }


# ── Interne ──────────────────────────────────────────────────────────────────


def _canonical(name: str) -> str:
    """`gemma4:e4b:latest` et `embeddinggemma:latest` ne sont pas des tags :
    Ollama suffixe `:latest` ce qui n'en a pas. Le catalogue, lui, n'écrit que
    des noms canoniques."""
    name = (name or "").strip()
    return name[: -len(":latest")] if name.endswith(":latest") else name


def _catalog(*, refresh: bool = False) -> dict:
    """Le magasin d'Ollama, mis en cache LLM_TAGS_CACHE_TTL_S.

    La requête part HORS du verrou : trois secondes de HTTP tenues sous un
    verrou bloqueraient toutes les générations. Deux appels simultanés peuvent
    donc la faire deux fois — sans conséquence, le dernier gagne."""
    with _LOCK:
        fresh = time.monotonic() - _catalog_cache["at"] < LLM_TAGS_CACHE_TTL_S
        if fresh and not refresh:
            return dict(_catalog_cache)

    from llm.ollama_client import list_models

    models = list_models()
    entries = [] if models is None else [_entry(m) for m in models]
    with _LOCK:
        _catalog_cache.update(
            at=time.monotonic(), reachable=models is not None,
            installed=[e for e in entries if e["name"]],
        )
        return dict(_catalog_cache)


def _entry(model: dict) -> dict:
    name = _canonical(str(model.get("name") or ""))
    details = model.get("details") or {}
    try:
        size_gb = round(float(model.get("size") or 0) / 1024 ** 3, 1)
    except (TypeError, ValueError):
        size_gb = 0.0
    return {
        "name": name,
        "size_gb": size_gb,
        "parameter_size": str(details.get("parameter_size") or ""),
        "known": name in LLM_MODELS,
    }
