# services/relink.py — Retrouver un document dont le fichier a été déplacé.
#
# Un document n'est relié à son fichier que par `documents.path`, qui sert aussi
# d'identité à l'import (`ON CONFLICT(path)`). Déplacer le fichier cassait tout
# ce qui le relit, et le réimporter créait un NOUVEAU document : progression,
# surlignages, sessions, dossier et titre restaient attachés à l'ancien. Ici,
# c'est la MÊME ligne qui change d'adresse, et son historique la suit.
#
# L'identité du contenu est `documents.content_hash` : SHA-256 tronqué à 16
# caractères, comme le rangement des envois (services/uploads). Un document
# importé avant qu'on la calcule n'en a pas : `backfill_content_hashes` la
# remplit au démarrage tant que le fichier est en place ; celui qui a déjà
# disparu est reconnu à son nombre de pages, et seul « Localiser » le retrouve.
#
# Trois portes, une seule politique :
#   - `relink_document` : « Localiser le fichier… » (carte, lecteur) ;
#   - `relink_siblings` : les autres documents introuvables déplacés avec lui ;
#   - `adopt_missing_twin` : réimporter le même contenu retrouve l'ancien document.
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from collections.abc import Callable
from pathlib import PurePath

import db
from config.settings import LIBRARY_MAX_DOCUMENTS, RELINK_SIBLINGS_MAX
from db.chapters import save_chapters
from db.documents import (
    get_document,
    get_document_by_path,
    list_all_documents,
    list_documents_by_hash,
    list_documents_without_hash,
    set_content_hash_if_unset,
    set_document_path,
    update_page_count,
)
from i18n import t
from pdf_viewer.chapter_index import build_chapter_index
from pdf_viewer.pdf_document import PdfDocument
from services import code_reader, library, pdf_rag, uploads

logger = logging.getLogger("services.relink")

__all__ = [
    "RelinkError",
    "file_digest",
    "relink_document",
    "relink_siblings",
    "sibling_roots",
    "adopt_missing_twin",
    "backfill_content_hashes",
]

_CHUNK = 1024 * 1024
# Même troncature que le dossier d'un envoi (services/uploads) : un document
# envoyé porte ainsi la même empreinte que le dossier qui le range.
_DIGEST_CHARS = 16


class RelinkError(ValueError):
    """Re-liaison refusée. `code` pour l'interface, `status` pour HTTP.

    `wrong_kind` (400), `unreadable` (400), `already_imported` (409),
    `different_file` (409 — l'interface propose de relier quand même),
    `not_found` (404)."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def file_digest(path: str) -> str:
    """Empreinte du CONTENU d'un fichier, lu en flux (un manuel scanné pèse
    plusieurs centaines de Mo)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()[:_DIGEST_CHARS]


def relink_document(
    doc_id: int,
    new_path: str,
    *,
    force: bool = False,
    path_allowed: Callable[[str], bool] | None = None,
) -> dict:
    """Relie le document `doc_id` au fichier `new_path`, en place.

    `force` accepte un contenu différent (nouvelle version du fichier) : le
    nombre de pages, les chapitres et le marque-page suivent. `path_allowed`
    (la garde S2 du routeur) active la passe sur les voisins ; sans lui, aucun
    autre document n'est touché. RelinkError en cas de refus."""
    doc = get_document(doc_id)
    if doc is None:
        raise RelinkError("not_found", t("folders.document_missing"), 404)
    old_path = doc.get("path") or ""
    target = _relink(doc, new_path, force=force)
    relinked: list[int] = []
    if target is not None and path_allowed is not None:
        relinked = relink_siblings(int(doc_id), old_path, target, path_allowed=path_allowed)
    return {"ok": True, "document": library.get_document(doc_id), "relinked": relinked}


def _relink(doc: dict, raw_path: str, *, force: bool) -> str | None:
    """Re-liaison d'UN document. Renvoie le nouveau chemin, None s'il n'a pas changé."""
    target, pages, digest = _inspect(doc, raw_path)
    if target == doc.get("path"):
        return None

    holder = get_document_by_path(target)
    if holder is None:
        # Même fichier sous une autre graphie (casse sous macOS et Windows,
        # lien physique) : la contrainte UNIQUE ne le verrait pas.
        holder = next(
            (
                other
                for other in list_documents_by_hash(digest)
                if other["id"] != doc["id"] and _same_file(other.get("path"), target)
            ),
            None,
        )
    if holder is not None and holder["id"] != doc["id"]:
        raise _already_imported(holder)

    known = doc.get("content_hash")
    # Document hérité sans empreinte : le nombre de pages est le seul témoin
    # qui reste d'un fichier qu'on ne peut plus relire.
    same = digest == known if known else pages == int(doc.get("page_count") or 0)
    if not same and not force:
        raise RelinkError("different_file", t("library.relink_different_file"), 409)

    _move(doc, target, digest, new_page_count=None if same else pages)
    return target


def _inspect(doc: dict, raw_path: str) -> tuple[str, int, str]:
    """(chemin normalisé, nombre de pages, empreinte) du fichier proposé.

    Le chemin est normalisé EXACTEMENT comme à l'import (orchestrator) : sinon
    un réimport ultérieur du même fichier raterait `ON CONFLICT(path)` et
    recréerait un doublon."""
    is_code = doc.get("extraction_engine") == "code"
    if is_code:
        right_kind = code_reader.is_code_file(raw_path)
    else:
        right_kind = raw_path.lower().endswith(".pdf")
    if not right_kind:
        raise RelinkError("wrong_kind", t("library.relink_wrong_kind"))
    try:
        if is_code:
            target = os.path.realpath(raw_path)
            pages = code_reader.page_count(target)
        else:
            with PdfDocument(raw_path) as pdf:
                target, pages = pdf.path, pdf.page_count()
        digest = file_digest(target)
    except Exception as exc:
        raise RelinkError("unreadable", t("library.relink_unreadable")) from exc
    return target, pages, digest


def _move(doc: dict, target: str, digest: str, *, new_page_count: int | None = None) -> None:
    """Écrit la nouvelle adresse, puis oublie tout ce qui dépendait de l'ancienne."""
    doc_id = int(doc["id"])
    old_path = doc.get("path") or ""
    try:
        set_document_path(doc_id, target, digest)
    except sqlite3.IntegrityError:
        # Un import a pris ce chemin entre la vérification et l'écriture.
        raise _already_imported(get_document_by_path(target) or {}) from None
    if new_page_count is not None:
        # Autre version du fichier, acceptée : on refait ce que ferait un import.
        update_page_count(doc_id, new_page_count)
        if doc.get("extraction_engine") != "code":
            try:
                save_chapters(doc_id, build_chapter_index(target))
            except Exception:  # des chapitres périmés valent mieux qu'une re-liaison perdue
                logger.warning("Chapitres non reconstruits pour doc=%s", doc_id, exc_info=True)
    library.forget_path_caches(doc_id, old_path, doc.get("extraction_engine"))
    pdf_rag.clear_index(doc_id)
    # Ancienne copie d'un document ENVOYÉ : elle nous appartient et ne sert plus.
    # Sans effet sur un fichier de l'utilisateur.
    uploads.discard(old_path)
    logger.info("Document id=%s relié : %s -> %s", doc_id, old_path, target)


def _same_file(a: str | None, b: str) -> bool:
    try:
        return bool(a) and os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def _already_imported(holder: dict) -> RelinkError:
    return RelinkError(
        "already_imported",
        t("library.relink_already_imported", name=holder.get("filename") or "?"),
        409,
    )


def sibling_roots(old: str, new: str) -> tuple[PurePath, PurePath] | None:
    """Les deux dossiers entre lesquels un déplacement a eu lieu.

    Retire la plus longue suite commune de noms de dossiers en fin de chemin :
    `…/Documents/Recherche/Papiers/x.pdf` → `…/Documents/Archives/Recherche/Papiers/x.pdf`
    donne `…/Documents` → `…/Documents/Archives`. None pour un simple
    renommage (même dossier), ou si un chemin n'est pas absolu ici — une base
    restaurée depuis un autre système."""
    old_dir, new_dir = PurePath(old).parent, PurePath(new).parent
    if not (old_dir.is_absolute() and new_dir.is_absolute()):
        return None
    old_parts, new_parts = list(old_dir.parts), list(new_dir.parts)
    if [os.path.normcase(p) for p in old_parts] == [os.path.normcase(p) for p in new_parts]:
        return None
    # `parts[0]` est l'ancre (`/`, `C:\`) : elle reste, la racine reste absolue.
    while (
        len(old_parts) > 1
        and len(new_parts) > 1
        and os.path.normcase(old_parts[-1]) == os.path.normcase(new_parts[-1])
    ):
        old_parts.pop()
        new_parts.pop()
    return PurePath(*old_parts), PurePath(*new_parts)


def relink_siblings(
    doc_id: int,
    old_path: str,
    new_path: str,
    *,
    path_allowed: Callable[[str], bool],
) -> list[int]:
    """Les AUTRES documents introuvables rangés sous l'ancienne racine, essayés
    au même emplacement relatif sous la nouvelle. Renvoie leurs ids.

    Identité stricte, jamais forcée : relier en silence un fichier différent
    serait pire que de le laisser introuvable. Chaque candidat passe la garde
    S2 (`path_allowed`), comme un import. Au plus `RELINK_SIBLINGS_MAX` essais
    (chacun relit tout le fichier pour son empreinte)."""
    roots = sibling_roots(old_path, new_path)
    if roots is None:
        return []
    old_root, new_root = roots
    relinked: list[int] = []
    tried = 0
    for other in list_all_documents(LIBRARY_MAX_DOCUMENTS):
        if tried >= RELINK_SIBLINGS_MAX:
            break
        path = other.get("path") or ""
        if other["id"] == doc_id or not path:
            continue
        try:
            relative = PurePath(path).relative_to(old_root)
        except ValueError:
            continue
        if not library.file_missing(path):
            continue
        candidate = str(new_root / relative)
        if not os.path.isfile(candidate) or not path_allowed(candidate):
            continue
        tried += 1
        try:
            if _relink(other, candidate, force=False) is not None:
                relinked.append(int(other["id"]))
        except RelinkError as exc:
            logger.info("Voisin id=%s non relié à %s (%s)", other["id"], candidate, exc.code)
    return relinked


def adopt_missing_twin(path: str, content_hash: str, *, code: bool) -> int | None:
    """À l'import d'un chemin inconnu : un document INTROUVABLE de même contenu
    est relié à ce chemin au lieu d'en créer un doublon. Renvoie son id.

    Pas de passe sur les voisins ici : l'orchestrateur est aussi appelé par la
    coque (document passé en ligne de commande), hors de la garde S2."""
    for twin in list_documents_by_hash(content_hash):
        if (twin.get("extraction_engine") == "code") != code:
            continue
        if not library.file_missing(twin.get("path")):
            continue
        try:
            _move(twin, path, content_hash)
        except RelinkError:
            return None
        return int(twin["id"])
    return None


def backfill_content_hashes() -> int:
    """Calcule l'empreinte des documents importés avant qu'elle existe, tant que
    leur fichier est encore en place : c'est ce qui permettra de les reconnaître
    après un déplacement. Lancé en tâche de fond au démarrage (server/app.py).
    Renvoie le nombre d'empreintes écrites."""
    filled = 0
    try:
        for doc in list_documents_without_hash():
            path = doc.get("path") or ""
            if library.file_missing(path):
                continue
            try:
                digest = file_digest(path)
            except OSError:
                continue
            if set_content_hash_if_unset(int(doc["id"]), path, digest):
                filled += 1
        if filled:
            logger.info("Empreinte calculée pour %s document(s) importé(s) sans elle.", filled)
    except Exception:  # un démarrage ne doit jamais échouer là-dessus
        logger.warning("Calcul des empreintes interrompu", exc_info=True)
    finally:
        # Thread dédié : sa connexion SQLite (une par thread) part avec lui.
        db.close_connection()
    return filled
