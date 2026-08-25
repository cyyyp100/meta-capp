# services/folders.py — Rangement de la bibliothèque : arbre de dossiers et
# affectation des documents.
#
# TOUTE la politique est ici — cycles, profondeur maximale, nettoyage des noms,
# et surtout ce que devient un document quand son dossier disparaît.
# `db/folders.py` ne fait que du SQL. Un routeur ne doit jamais re-décider l'une
# de ces règles.
from __future__ import annotations

import logging

from config.settings import LIBRARY_FOLDER_NAME_MAX, LIBRARY_MAX_FOLDER_DEPTH
from db import folders as _folders
from db.documents import get_document
from db.user import DEFAULT_USER_ID
from i18n import t

logger = logging.getLogger("services.folders")

__all__ = [
    "folder_tree",
    "create_folder",
    "rename_folder",
    "move_folder",
    "delete_folder",
    "move_document",
]


def folder_tree(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Arbre imbriqué prêt pour l'API, racines au premier niveau.

    Chaque nœud : {id, name, parent_id, position, doc_count, total_count,
    children}. `doc_count` = documents directement dans le dossier ;
    `total_count` inclut le sous-arbre — c'est ce qu'un rail replié doit
    afficher. Défensif : un nœud dont le parent est introuvable est raccroché à
    la racine plutôt que perdu.
    """
    flat = _folders.list_folders(user_id)
    counts = _folders.count_documents_by_folder()
    by_id: dict[int, dict] = {
        folder["id"]: {**folder, "doc_count": counts.get(folder["id"], 0), "children": []}
        for folder in flat
    }
    roots: list[dict] = []
    for node in by_id.values():
        parent = by_id.get(node["parent_id"]) if node["parent_id"] is not None else None
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)
    for root in roots:
        _fill_total_counts(root)
    return roots


def create_folder(name: str, parent_id: int | None = None) -> dict:
    """Crée un dossier. Nom vide → libellé par défaut traduit."""
    clean = _clean_name(name)
    _check_parent(parent_id)
    if parent_id is not None and _depth(parent_id) + 1 >= LIBRARY_MAX_FOLDER_DEPTH:
        raise ValueError(t("folders.too_deep", n=LIBRARY_MAX_FOLDER_DEPTH))
    folder_id = _folders.create_folder(clean, parent_id)
    return _node(folder_id)


def rename_folder(folder_id: int, name: str) -> dict:
    _require(folder_id)
    _folders.rename_folder(folder_id, _clean_name(name))
    return _node(folder_id)


def move_folder(folder_id: int, parent_id: int | None) -> dict:
    """Reparente un dossier.

    GARDE-FOU DE CYCLE : `parent_id` ne peut être ni `folder_id` ni l'un de ses
    descendants. `descendant_ids` inclut le dossier lui-même, donc le dépôt sur
    soi-même est couvert par le même test.
    """
    _require(folder_id)
    if parent_id is not None:
        _check_parent(parent_id)
        if parent_id in _folders.descendant_ids(folder_id):
            raise ValueError(t("folders.cycle"))
        if _depth(parent_id) + 1 + _subtree_height(folder_id) > LIBRARY_MAX_FOLDER_DEPTH:
            raise ValueError(t("folders.too_deep", n=LIBRARY_MAX_FOLDER_DEPTH))
    _folders.set_folder_parent(folder_id, parent_id, _folders.next_position(parent_id))
    return _node(folder_id)


def delete_folder(folder_id: int) -> dict:
    """Supprime le dossier ET ses sous-dossiers (cascade SQL).

    Les documents du sous-arbre ne sont PAS supprimés : `documents.folder_id`
    repasse à NULL et ils réapparaissent dans « Non classés ». Les compteurs sont
    calculés avant la suppression, sinon il n'y a plus rien à compter.
    """
    _require(folder_id)
    subtree = _folders.descendant_ids(folder_id)
    counts = _folders.count_documents_by_folder()
    detached = sum(counts.get(fid, 0) for fid in subtree)
    _folders.delete_folder(folder_id)
    logger.info(
        "Dossier supprimé id=%s : %s dossier(s), %s document(s) détaché(s)",
        folder_id, len(subtree), detached,
    )
    return {"deleted_folders": len(subtree), "detached_documents": detached}


def move_document(doc_id: int, folder_id: int | None) -> None:
    """Range un document. `folder_id=None` = racine (« Non classés »)."""
    if get_document(doc_id) is None:
        raise ValueError(t("folders.document_missing"))
    if folder_id is not None:
        _check_parent(folder_id)
    _folders.set_document_folder(doc_id, folder_id)


# ── Internes ────────────────────────────────────────────────────────────────


def _clean_name(name: str) -> str:
    clean = " ".join(str(name or "").split())[:LIBRARY_FOLDER_NAME_MAX]
    return clean or t("folders.default_name")


def _require(folder_id: int) -> dict:
    folder = _folders.get_folder(folder_id)
    if folder is None:
        raise ValueError(t("folders.missing"))
    return folder


def _check_parent(parent_id: int | None) -> None:
    if parent_id is not None and _folders.get_folder(parent_id) is None:
        raise ValueError(t("folders.parent_missing"))


def _node(folder_id: int) -> dict:
    """Un nœud isolé (après création/renommage/déplacement), enfants exclus."""
    folder = _folders.get_folder(folder_id) or {}
    counts = _folders.count_documents_by_folder()
    direct = counts.get(folder_id, 0)
    return {
        **folder,
        "doc_count": direct,
        "total_count": sum(counts.get(fid, 0) for fid in _folders.descendant_ids(folder_id)),
        "children": [],
    }


def _fill_total_counts(node: dict) -> int:
    total = node["doc_count"]
    for child in node["children"]:
        total += _fill_total_counts(child)
    node["total_count"] = total
    return total


def _depth(folder_id: int | None) -> int:
    """Profondeur d'un dossier (racine = 0).

    La boucle est bornée : une base incohérente ne doit pas figer le serveur.
    """
    depth = 0
    current = folder_id
    while current is not None and depth <= LIBRARY_MAX_FOLDER_DEPTH:
        folder = _folders.get_folder(current)
        if folder is None:
            break
        current = folder["parent_id"]
        depth += 1
    return max(0, depth - 1)


def _subtree_height(folder_id: int) -> int:
    """Nombre de niveaux sous `folder_id` (feuille = 0)."""
    by_parent: dict[int | None, list[dict]] = {}
    for folder in _folders.list_folders():
        by_parent.setdefault(folder["parent_id"], []).append(folder)

    def height(fid: int, guard: int) -> int:
        if guard <= 0:
            return 0
        children = by_parent.get(fid, [])
        return 1 + max((height(c["id"], guard - 1) for c in children), default=-1)

    return height(folder_id, LIBRARY_MAX_FOLDER_DEPTH)
