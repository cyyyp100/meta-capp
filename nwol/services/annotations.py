# services/annotations.py — La prise de notes du lecteur (schéma v45).
#
# Seul responsable de la validation : les routeurs (server/routers/highlights.py,
# server/routers/annotations.py) ne font que traduire ses erreurs en 400 / 404,
# et la couche db/ écrit ce qu'on lui donne.
#
#   * étiquettes : un nom et une couleur de la palette FERMÉE
#     (settings.ANNOTATION_COLORS), globales à l'élève, semées à la demande ;
#   * surlignages : une citation, ses rects (PDF) ou son ancrage texte (code),
#     une étiquette, un style (settings.ANNOTATION_STYLES), une note ;
#   * post-it (posé sur la page) et signets (un par page) ;
#   * l'export Markdown du carnet d'un document.
#
# La page est contrôlée contre `page_count` en base, sans ouvrir le fichier : un
# document dont le fichier a disparu garde ses notes.
from __future__ import annotations

import logging
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

from config.settings import (
    ANNOTATION_COLORS,
    ANNOTATION_DEFAULT_COLOR,
    ANNOTATION_LABEL_NAME_MAX,
    ANNOTATION_LEGACY_COLOR_PRESETS,
    ANNOTATION_MAX_LABELS,
    ANNOTATION_MAX_RECTS,
    ANNOTATION_NOTE_MAX_CHARS,
    ANNOTATION_PRESETS,
    ANNOTATION_QUOTE_MAX_CHARS,
    ANNOTATION_STYLES,
)
from db import annotation_labels as _labels
from db import reader_highlights as _highlights
from db import reader_notes as _notes
from db.documents import get_document
from db.user import DEFAULT_USER_ID, ensure_default_user
from i18n import t

logger = logging.getLogger("services.annotations")

__all__ = [
    "AnnotationNotFound",
    "labels_payload",
    "label_limits",
    "create_label",
    "update_label",
    "delete_label",
    "reorder_labels",
    "document_annotations",
    "create_highlight",
    "update_highlight",
    "delete_highlight",
    "create_note",
    "update_note",
    "delete_note",
    "export_markdown",
]

NOTE_KINDS = ("sticky", "signet")


class AnnotationNotFound(ValueError):
    """Document, étiquette, surlignage ou note introuvable (→ 404)."""


# ── Validation ──────────────────────────────────────────────────────────────


def _document(doc_id: int) -> dict:
    doc = get_document(int(doc_id))
    if doc is None:
        raise AnnotationNotFound(t("folders.document_missing"))
    return doc


def _is_code(doc: dict) -> bool:
    return doc.get("extraction_engine") == "code"


def _check_page(doc: dict, page: Any) -> int:
    try:
        number = int(page)
    except (TypeError, ValueError):
        raise ValueError(t("library.bookmark_page_invalid")) from None
    page_count = int(doc.get("page_count") or 0)
    if number < 1 or (page_count > 0 and number > page_count):
        raise ValueError(t("library.bookmark_page_invalid"))
    return number


def _check_color(color: Any) -> str:
    if color not in ANNOTATION_COLORS:
        raise ValueError(t("annotations.error.color"))
    return str(color)


def _check_style(style: Any) -> str:
    if style not in ANNOTATION_STYLES:
        raise ValueError(t("annotations.error.style"))
    return str(style)


def _clean_name(name: Any) -> str:
    clean = " ".join(str(name or "").split())
    if not clean or len(clean) > ANNOTATION_LABEL_NAME_MAX:
        raise ValueError(t("annotations.error.label_name", max=ANNOTATION_LABEL_NAME_MAX))
    return clean


def _clean_text(text: Any, limit: int) -> str:
    """Texte libre (note, post-it) : bords retirés, sauts de ligne gardés."""
    clean = str(text or "").replace("\r\n", "\n").strip()
    if len(clean) > limit:
        raise ValueError(t("annotations.error.too_long", max=limit))
    return clean


def _check_label(label_id: Any, user_id: int) -> int | None:
    if label_id is None:
        return None
    try:
        number = int(label_id)
    except (TypeError, ValueError):
        raise ValueError(t("annotations.error.label_missing")) from None
    if _labels.get_label(number, user_id) is None:
        raise ValueError(t("annotations.error.label_missing"))
    return number


def _check_rects(rects: Any) -> list[list[float]]:
    if not isinstance(rects, list) or len(rects) > ANNOTATION_MAX_RECTS:
        raise ValueError(t("annotations.error.rects"))
    out: list[list[float]] = []
    for rect in rects:
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ValueError(t("annotations.error.rects"))
        try:
            values = [float(v) for v in rect]
        except (TypeError, ValueError):
            raise ValueError(t("annotations.error.rects")) from None
        if not all(math.isfinite(v) for v in values):
            raise ValueError(t("annotations.error.rects"))
        out.append(values)
    return out


def _check_position(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(t("annotations.error.position")) from None
    if not math.isfinite(number) or number < 0:
        raise ValueError(t("annotations.error.position"))
    return number


def _ensure_labels(user_id: int) -> None:
    """Base neuve ou effacée : les étiquettes prédéfinies sont semées ici."""
    ensure_default_user()
    _labels.seed_presets(ANNOTATION_PRESETS, user_id)


def _legacy_label(color: str | None, user_id: int) -> int | None:
    """L'ancienne couleur (« key », « explain », « reference ») en étiquette."""
    preset = ANNOTATION_LEGACY_COLOR_PRESETS.get(color or "key", ANNOTATION_LEGACY_COLOR_PRESETS["key"])
    return _labels.preset_label_id(preset, user_id)


# ── Étiquettes ──────────────────────────────────────────────────────────────


def labels_payload(user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Les étiquettes de l'élève, dans son ordre : `{id, preset, name, color,
    position, usage}`. `name` est None pour une étiquette prédéfinie jamais
    renommée — l'interface la nomme dans sa langue (`annotations.preset.*`)."""
    _ensure_labels(user_id)
    return _labels.list_labels(user_id)


def label_limits() -> dict:
    """Ce que l'interface doit savoir pour ne pas proposer ce que le serveur
    refuserait : la longueur d'un nom, le nombre d'étiquettes, la couleur
    proposée pour une nouvelle. La source est `config/settings.py`."""
    return {
        "name_max": ANNOTATION_LABEL_NAME_MAX,
        "max_labels": ANNOTATION_MAX_LABELS,
        "default_color": ANNOTATION_DEFAULT_COLOR,
    }


def _label_or_404(label_id: int, user_id: int) -> dict:
    label = _labels.get_label(label_id, user_id)
    if label is None:
        raise AnnotationNotFound(t("annotations.error.label_missing"))
    return label


def create_label(name: Any, color: Any, user_id: int = DEFAULT_USER_ID) -> dict:
    _ensure_labels(user_id)
    clean = _clean_name(name)
    clean_color = _check_color(color)
    if _labels.count_labels(user_id) >= ANNOTATION_MAX_LABELS:
        raise ValueError(t("annotations.error.label_limit", max=ANNOTATION_MAX_LABELS))
    label_id = _labels.create_label(clean, clean_color, user_id)
    return _label_or_404(label_id, user_id)


def update_label(label_id: int, fields: dict, user_id: int = DEFAULT_USER_ID) -> dict:
    """`fields` : `name` (None = revenir au nom traduit, pour une étiquette
    prédéfinie seulement ; renommée, elle devient personnelle) et/ou `color`."""
    label = _label_or_404(label_id, user_id)
    changes: dict[str, Any] = {}
    if "name" in fields:
        if fields["name"] is None:
            if label.get("preset") is None:
                raise ValueError(t("annotations.error.label_name", max=ANNOTATION_LABEL_NAME_MAX))
            changes["name"] = None
        else:
            changes["name"] = _clean_name(fields["name"])
    if "color" in fields:
        changes["color"] = _check_color(fields["color"])
    _labels.update_label(label_id, changes, user_id)
    return _label_or_404(label_id, user_id)


def delete_label(label_id: int, user_id: int = DEFAULT_USER_ID) -> dict:
    """Supprime l'étiquette ; ses éléments restent, sans étiquette. La dernière
    ne se supprime pas : surligner demande au moins une étiquette."""
    _label_or_404(label_id, user_id)
    if _labels.count_labels(user_id) <= 1:
        raise ValueError(t("annotations.error.last_label"))
    usage = next((row["usage"] for row in _labels.list_labels(user_id) if row["id"] == int(label_id)), 0)
    _labels.delete_label(label_id, user_id)
    return {"removed": True, "released": int(usage)}


def reorder_labels(ordered_ids: list[int], user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Range les étiquettes : `ordered_ids` est exactement l'ensemble des
    étiquettes de l'élève, dans le nouvel ordre."""
    _ensure_labels(user_id)
    current = {row["id"] for row in _labels.list_labels(user_id)}
    ids = [int(i) for i in ordered_ids]
    if len(ids) != len(set(ids)) or set(ids) != current:
        raise ValueError(t("annotations.error.label_order"))
    _labels.set_positions(ids, user_id)
    return _labels.list_labels(user_id)


# ── Surlignages ─────────────────────────────────────────────────────────────


def _highlight_payload(row: dict) -> dict:
    return {
        "id": row["id"],
        "page": row["page"],
        "quote": row.get("quote") or "",
        "rects": row.get("rects") or [],
        "anchor": row.get("anchor"),
        "color": row.get("color") or "key",
        "label_id": row.get("label_id"),
        "style": row.get("style") or "highlight",
        "note": row.get("note"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at") or row.get("created_at"),
    }


def _highlight_or_404(doc_id: int, highlight_id: int, user_id: int) -> dict:
    row = _highlights.get_highlight(highlight_id, doc_id, user_id)
    if row is None:
        raise AnnotationNotFound(t("annotations.error.missing"))
    return _highlight_payload(row)


def create_highlight(doc_id: int, data: dict, user_id: int = DEFAULT_USER_ID) -> dict:
    """Surligne un passage. `data` : page, quote, rects, et en option anchor,
    label_id, style, note, color (l'ancienne couleur, traduite en étiquette).

    Le même passage surligné deux fois reste UN surlignage
    (db.reader_highlights.add_highlight) : l'étiquette et le style ne changent
    que s'ils sont fournis, la note existante n'est jamais effacée. Un nouveau
    passage sans étiquette reçoit celle de sa couleur (« Important » par
    défaut)."""
    doc = _document(doc_id)
    _ensure_labels(user_id)
    page = _check_page(doc, data.get("page"))
    quote = str(data.get("quote") or "").strip()
    if not quote or len(quote) > ANNOTATION_QUOTE_MAX_CHARS:
        raise ValueError(t("annotations.error.quote", max=ANNOTATION_QUOTE_MAX_CHARS))
    rects = _check_rects(data.get("rects") or [])
    style = _check_style(data["style"]) if data.get("style") is not None else None
    note = _clean_text(data.get("note"), ANNOTATION_NOTE_MAX_CHARS) or None
    color = data.get("color")
    if "label_id" in data and data["label_id"] is not None:
        label_id = _check_label(data["label_id"], user_id)
    elif color is not None:
        label_id = _legacy_label(str(color), user_id)
    elif _highlights.find_highlight(doc_id, page, quote, user_id) is None:
        label_id = _legacy_label(None, user_id)
    else:
        label_id = None  # déjà surligné : son étiquette reste
    highlight_id = _highlights.add_highlight(
        document_id=int(doc_id),
        page=page,
        quote=quote,
        rects=rects,
        color=str(color) if color is not None else "key",
        user_id=user_id,
        anchor=data.get("anchor"),
        label_id=label_id,
        style=style,
        note=note,
    )
    return _highlight_or_404(doc_id, highlight_id, user_id)


def update_highlight(doc_id: int, highlight_id: int, fields: dict, user_id: int = DEFAULT_USER_ID) -> dict:
    """Édition partielle : seules les clés présentes changent. `label_id` None
    retire l'étiquette, `note` None ou vide efface la note."""
    _document(doc_id)
    _highlight_or_404(doc_id, highlight_id, user_id)
    changes: dict[str, Any] = {}
    if "label_id" in fields:
        changes["label_id"] = _check_label(fields["label_id"], user_id)
    if "style" in fields:
        changes["style"] = _check_style(fields["style"])
    if "note" in fields:
        changes["note"] = _clean_text(fields["note"], ANNOTATION_NOTE_MAX_CHARS) or None
    _highlights.update_highlight(highlight_id, doc_id, changes, user_id)
    return _highlight_or_404(doc_id, highlight_id, user_id)


def delete_highlight(doc_id: int, highlight_id: int, user_id: int = DEFAULT_USER_ID) -> int:
    """Supprime le surlignage DE CE DOCUMENT ; renvoie le nombre supprimé."""
    return _highlights.delete_highlight(highlight_id, user_id, document_id=int(doc_id))


# ── Post-it et signets ──────────────────────────────────────────────────────


def _note_or_404(doc_id: int, note_id: int, user_id: int) -> dict:
    row = _notes.get_note(note_id, doc_id, user_id)
    if row is None:
        raise AnnotationNotFound(t("annotations.error.missing"))
    return row


def create_note(doc_id: int, data: dict, user_id: int = DEFAULT_USER_ID) -> dict:
    """Un post-it (`kind: sticky`) ou un signet (`kind: signet`).

    Post-it d'un PDF : `x`, `y` en points PDF, finis et positifs. Post-it d'un
    fichier de code, et signet : sans position. Un signet de plus sur une page
    qui en a déjà un le remplace (un par page)."""
    doc = _document(doc_id)
    _ensure_labels(user_id)
    kind = data.get("kind")
    if kind not in NOTE_KINDS:
        raise ValueError(t("annotations.error.kind"))
    page = _check_page(doc, data.get("page"))
    body = _clean_text(data.get("body"), ANNOTATION_NOTE_MAX_CHARS)
    label_id = _check_label(data.get("label_id"), user_id)
    if kind == "signet":
        existing = _notes.signet_on_page(doc_id, page, user_id)
        if existing is not None:
            _notes.update_note(existing["id"], doc_id, {"body": body, "label_id": label_id}, user_id)
            return _note_or_404(doc_id, existing["id"], user_id)
        x = y = None
    elif _is_code(doc):
        x = y = None
    else:
        x, y = _check_position(data.get("x")), _check_position(data.get("y"))
    note_id = _notes.create_note(doc_id, page, kind, x=x, y=y, body=body, label_id=label_id, user_id=user_id)
    return _note_or_404(doc_id, note_id, user_id)


def update_note(doc_id: int, note_id: int, fields: dict, user_id: int = DEFAULT_USER_ID) -> dict:
    """Édition partielle : `body`, `label_id` (None = sans étiquette), et pour
    un post-it de PDF `x`, `y`."""
    doc = _document(doc_id)
    note = _note_or_404(doc_id, note_id, user_id)
    changes: dict[str, Any] = {}
    if "body" in fields:
        changes["body"] = _clean_text(fields["body"], ANNOTATION_NOTE_MAX_CHARS)
    if "label_id" in fields:
        changes["label_id"] = _check_label(fields["label_id"], user_id)
    if note["kind"] == "sticky" and not _is_code(doc):
        for axis in ("x", "y"):
            if axis in fields:
                changes[axis] = _check_position(fields[axis])
    _notes.update_note(note_id, doc_id, changes, user_id)
    return _note_or_404(doc_id, note_id, user_id)


def delete_note(doc_id: int, note_id: int, user_id: int = DEFAULT_USER_ID) -> int:
    return _notes.delete_note(note_id, doc_id, user_id)


# ── Lecture et export ───────────────────────────────────────────────────────


def _reading_order(highlight: dict) -> tuple:
    """Rang d'un surlignage dans sa page : de haut en bas puis de gauche à
    droite (PDF : ses rects), ou dans l'ordre du texte (fichier de code : son
    ancrage). Le premier élément sépare les deux familles, qui ne se comparent
    pas entre elles."""
    rects = highlight.get("rects") or []
    if rects:
        return (highlight["page"], 0, min(r[1] for r in rects), min(r[0] for r in rects), "", 0, highlight["id"])
    anchor = highlight.get("anchor") or {}
    return (highlight["page"], 1, 0.0, 0.0, str(anchor.get("block_id") or ""), int(anchor.get("start") or 0), highlight["id"])


def document_annotations(doc_id: int, user_id: int = DEFAULT_USER_ID) -> dict:
    """Tout ce que l'élève a noté sur le document : `{highlights, notes}`, dans
    l'ORDRE DE LECTURE — celui du carnet comme de l'export : page par page, les
    surlignages de haut en bas, puis les post-it et signets (db/reader_notes)."""
    _document(doc_id)
    highlights = [_highlight_payload(row) for row in _highlights.list_highlights(doc_id, user_id)]
    return {
        "highlights": sorted(highlights, key=_reading_order),
        "notes": _notes.list_notes(doc_id, user_id),
    }


# Une ligne qui deviendrait de la structure Markdown : titre, citation, liste,
# liste numérotée, bloc de code, tableau, règle, soulignement setext.
_MD_STRUCTURE = re.compile(r"^(\s{0,3})([#>*+\-=|`~_]|\d+[.)](?=\s|$))")


def _md_line(line: str) -> str:
    return _MD_STRUCTURE.sub(lambda m: m.group(1) + "\\" + m.group(2), line)


def _md_text(text: str) -> list[str]:
    return [_md_line(line) for line in (text or "").splitlines()]


def _label_name(label: dict | None) -> str:
    if label is None:
        return t("annotations.md.no_label")
    if label.get("name"):
        return str(label["name"])
    return t(f"annotations.preset.{label.get('preset')}")


def _filename(title: str) -> str:
    """Nom de fichier lisible et sûr : lettres, chiffres, tirets."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_title).strip("-").lower()[:60] or "document"
    return f"{slug}-{t('annotations.md.file_suffix')}.md"


def export_markdown(doc_id: int, user_id: int = DEFAULT_USER_ID) -> tuple[str, str]:
    """Le carnet du document en Markdown : `(nom de fichier, texte)`.

    En tête, le marque-page et les signets ; puis page par page, chaque
    citation en `> `, suivie de « *Étiquette* · style » et de sa note, puis
    les post-it. Seules les lignes qui deviendraient de la structure Markdown
    sont échappées. Les noms viennent de l'i18n : l'export suit la langue de
    l'interface."""
    from services.library import bookmark_page

    doc = _document(doc_id)
    labels = {row["id"]: row for row in labels_payload(user_id)}
    data = document_annotations(doc_id, user_id)
    title = str(doc.get("title") or doc.get("filename") or "")
    lines = [f"# {_md_line(t('annotations.md.title', title=title))}", ""]

    marked = bookmark_page(doc)
    signets = [n for n in data["notes"] if n["kind"] == "signet"]
    if marked is not None:
        lines.append(t("annotations.md.bookmark_line", page=marked))
    if signets:
        if marked is not None:
            lines.append("")
        lines.append(f"**{t('annotations.md.signets')}**")
        lines.append("")
        for signet in signets:
            entry = f"- {t('annotations.md.page', page=signet['page'])} — *{_label_name(labels.get(signet['label_id']))}*"
            body = " ".join((signet.get("body") or "").split())
            lines.append(f"{entry} — {body}" if body else entry)
    if marked is not None or signets:
        lines.append("")

    pages = sorted({h["page"] for h in data["highlights"]} | {n["page"] for n in data["notes"] if n["kind"] == "sticky"})
    if not pages and marked is None and not signets:
        lines.append(t("annotations.md.empty"))
        lines.append("")
    for page in pages:
        lines.append(f"## {t('annotations.md.page', page=page)}")
        lines.append("")
        for highlight in (h for h in data["highlights"] if h["page"] == page):
            lines.extend(f"> {line}" if line else ">" for line in _md_text(highlight["quote"]))
            lines.append("")
            style = t(f"annotations.md.style.{highlight['style']}")
            lines.append(f"*{_label_name(labels.get(highlight['label_id']))}* · {style}")
            if highlight.get("note"):
                lines.append("")
                lines.extend(_md_text(highlight["note"]))
            lines.append("")
        for sticky in (n for n in data["notes"] if n["kind"] == "sticky" and n["page"] == page):
            lines.append(f"**{t('annotations.md.sticky')}** (*{_label_name(labels.get(sticky['label_id']))}*)")
            lines.append("")
            lines.extend(_md_text(sticky.get("body") or ""))
            lines.append("")
    text = "\n".join(lines).rstrip("\n") + "\n"
    logger.info("Carnet exporté doc=%s : %d surlignage(s), %d note(s)", doc_id, len(data["highlights"]), len(data["notes"]))
    # Un titre qui n'est que le nom du fichier perd son extension : « cours-notes.md ».
    stem = Path(title).stem if title and title == doc.get("filename") else title
    return _filename(stem), text
