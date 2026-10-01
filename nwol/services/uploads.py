# services/uploads.py — Documents ENVOYÉS par le navigateur (mode sans coque).
#
# Dans la fenêtre native, le dialogue de fichier rend un CHEMIN : le document est
# lu sur place et jamais copié (`services/library.delete_document`). Un
# navigateur ne donne jamais de chemin, seulement le contenu (`<input type=file>`).
# Quand Meta-Capp tourne dans le navigateur (Linux sans GTK ni Qt, Windows sans
# WebView2, `--browser`), le fichier envoyé est donc copié ici, dans le dossier
# de données, puis importé par le chemin habituel — le reste de l'application ne
# voit aucune différence.
#
# Rangement : `<données>/uploads/<empreinte>/<nom>`. L'empreinte (SHA-256 du
# contenu) dédoublonne : renvoyer le même fichier retrouve le même document,
# deux fichiers différents de même nom ne s'écrasent jamais.
#
# Ce module n'efface QUE ce rangement-là (`_stored_copy`, `discard_all`), jamais
# le dossier entier : son emplacement dérive de celui de la base, que
# `NWOL_DB_PATH` déplace en dev. Base posée dans le dossier personnel, un
# dossier nommé `documents` y était `~/Documents` — macOS et Windows ignorent la
# casse — et « Effacer toutes mes données » l'aurait vidé.
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

import db
from config.settings import UPLOAD_MAX_BYTES

_CHUNK = 1024 * 1024
_UNSAFE_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_DIGEST_DIR = re.compile(r"[0-9a-f]{16}")
_TMP_PREFIX = ".upload-"
# Noms de périphériques de Windows, quelle que soit l'extension : `aux.c` ou
# `con.h` y désignent la console ou un port, pas un fichier.
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"{port}{i}" for port in ("com", "lpt") for i in range(1, 10)}
)
_MAX_NAME_CHARS = 120
# ext4 et btrfs bornent un nom à 255 OCTETS : 120 caractères chinois en font 360.
_MAX_NAME_BYTES = 200


def uploads_dir() -> Path:
    """À côté de la base : même sauvegarde, même effacement, même isolation en test."""
    return Path(db.DB_PATH).parent / "uploads"


def safe_filename(name: str) -> str:
    """Nom de fichier sans chemin ni caractère interdit, écrivable partout :
    noms de périphériques de Windows et limite en octets de Linux compris."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE_CHARS.sub("_", base).strip(" .")
    if not base:
        return "document.pdf"
    if base.split(".", 1)[0].rstrip(" ").lower() in _WINDOWS_RESERVED:
        base = "_" + base
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    # On raccourcit le nom avant l'extension : c'est elle qui dit PDF ou code
    # (une extension démesurée, elle, n'est de toute façon pas un format lu).
    while len(base) > _MAX_NAME_CHARS or len(base.encode("utf-8")) > _MAX_NAME_BYTES:
        if stem:
            stem = stem[:-1]
        else:
            ext = ext[:-1]
        base = stem + dot + ext
    return base


def _stored_copy(path: str | None) -> Path | None:
    """La copie que désigne `path` si elle suit le rangement de `store`
    (`<envois>/<empreinte>/<nom>`), None pour tout autre chemin — un fichier
    de l'utilisateur, ou n'importe quoi d'autre que ce module n'a pas écrit."""
    if not path:
        return None
    try:
        real = Path(os.path.realpath(path))
        root = Path(os.path.realpath(uploads_dir()))
    except (OSError, ValueError):
        return None
    if real.parent.parent != root or not _DIGEST_DIR.fullmatch(real.parent.name):
        return None
    return real


def is_upload(path: str | None) -> bool:
    return _stored_copy(path) is not None


def store(filename: str, stream: BinaryIO) -> tuple[str, bool]:
    """Copie `stream` sous le dossier des documents envoyés.

    Renvoie (chemin, nouveau) — `nouveau` est faux quand ce contenu avait déjà
    été envoyé sous ce nom : un import raté ne doit alors PAS effacer une copie
    qu'un document existant référence. ValueError au-delà de
    `UPLOAD_MAX_BYTES` ou si le fichier est vide."""
    root = uploads_dir()
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=root, prefix=_TMP_PREFIX)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := stream.read(_CHUNK):
                size += len(chunk)
                if size > UPLOAD_MAX_BYTES:
                    raise ValueError(f"Fichier trop volumineux (> {UPLOAD_MAX_BYTES // (1024 * 1024)} Mo)")
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise ValueError("Fichier vide")
        target_dir = root / digest.hexdigest()[:16]
        target_dir.mkdir(exist_ok=True)
        target = target_dir / safe_filename(filename)
        if target.exists():
            # Même contenu, même nom : déjà là. Surtout ne pas le remplacer —
            # sous Windows, un fichier ouvert par le lecteur ne se remplace pas.
            os.unlink(tmp_name)
            return str(target), False
        os.replace(tmp_name, target)
        return str(target), True
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def discard(path: str | None) -> None:
    """Efface la COPIE d'un document envoyé. Ne touche jamais un fichier de
    l'utilisateur : tout chemin qui ne suit pas le rangement des envois est ignoré."""
    real = _stored_copy(path)
    if real is None:
        return
    try:
        real.unlink()
        real.parent.rmdir()  # n'aboutit que si le dossier de l'empreinte est vide
    except OSError:
        pass


def discard_all() -> None:
    """Effacement total (S10) : toutes les copies envoyées — et rien d'autre.

    Pas de `rmtree` du dossier lui-même (voir l'en-tête) : seuls les dossiers
    d'empreinte et les envois interrompus partent ; le dossier n'est retiré
    que s'il ne contient plus rien."""
    root = uploads_dir()
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if _DIGEST_DIR.fullmatch(entry.name) and entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        elif entry.name.startswith(_TMP_PREFIX) and entry.is_file():
            try:
                entry.unlink()
            except OSError:
                pass
    try:
        root.rmdir()
    except OSError:
        pass
