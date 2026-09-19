# db/embeddings.py — Vecteurs d'embedding des passages d'un document.
#
# Une ligne par document (services/pdf_rag) : tous les vecteurs de ses chunks,
# concaténés en float32, dans l'ordre de l'index lexical. La ligne n'est valable
# que pour UN découpage précis : `chunk_hash` (empreinte des textes des chunks)
# et `mtime` du fichier la lient au contenu ; `model` au modèle qui l'a produite.
# Une seule de ces trois choses change → la ligne est recalculée, jamais lue.
#
# Blob et non colonnes : les vecteurs ne sont jamais interrogés en SQL, ils sont
# chargés en bloc en mémoire à l'ouverture du lecteur. 768 floats × 4 octets ×
# ~80 chunks ≈ 250 Ko pour un article ; quelques Mo pour un livre.
from __future__ import annotations

import logging
from array import array

from db import get_connection

logger = logging.getLogger("db.embeddings")

__all__ = ["load_vectors", "save_vectors", "delete_vectors"]


def load_vectors(doc_id: int, mtime: float, model: str, chunk_hash: str) -> list[array] | None:
    """Vecteurs (un `array('f')` par chunk) si la ligne correspond exactement
    au fichier, au découpage et au modèle demandés ; None sinon."""
    row = get_connection().execute(
        "SELECT mtime, model, chunk_hash, dim, count, vectors FROM document_embeddings WHERE doc_id=?",
        (int(doc_id),),
    ).fetchone()
    if row is None or row["model"] != model or row["chunk_hash"] != chunk_hash or float(row["mtime"]) != float(mtime):
        return None
    dim, count = int(row["dim"]), int(row["count"])
    flat = array("f")
    flat.frombytes(row["vectors"])
    if dim <= 0 or len(flat) != dim * count:
        logger.warning("Embeddings doc %s : blob incohérent (%s floats pour %s×%s)", doc_id, len(flat), count, dim)
        return None
    return [flat[i * dim:(i + 1) * dim] for i in range(count)]


def save_vectors(doc_id: int, mtime: float, model: str, chunk_hash: str, vectors: list[array]) -> None:
    """Remplace les vecteurs du document (une ligne par document)."""
    dim = len(vectors[0]) if vectors else 0
    flat = array("f")
    for vector in vectors:
        flat.extend(vector)
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO document_embeddings (doc_id, mtime, model, chunk_hash, dim, count, vectors, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(doc_id) DO UPDATE SET
                   mtime=excluded.mtime, model=excluded.model, chunk_hash=excluded.chunk_hash,
                   dim=excluded.dim, count=excluded.count, vectors=excluded.vectors,
                   created_at=excluded.created_at""",
            (int(doc_id), float(mtime), model, chunk_hash, dim, len(vectors), flat.tobytes()),
        )


def delete_vectors(doc_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM document_embeddings WHERE doc_id=?", (int(doc_id),))
