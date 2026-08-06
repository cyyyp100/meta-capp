from __future__ import annotations

from typing import Any


_TYPE_LABELS: dict[str, str] = {
    "definition": "Définition",
    "abstract": "Résumé",
    "theorem": "Théorème",
    "example": "Exemple",
    "remark": "Remarque",
    "warning": "Attention",
    "formula": "Formule",
    "figure": "Figure",
    "table": "Tableau",
    "code": "Code",
    "exercise": "Exercice",
    "question": "Question",
    "heading": "Titre",
    "subheading": "Sous-titre",
}


def build_llm_context(
    blocks: list[dict[str, Any]],
    current_block_id: str | None = None,
    window: int = 8,
    document_title: str = "",
    current_section: str = "",
) -> dict[str, Any]:
    current_index = _find_block_index(blocks, current_block_id)
    if current_index is None and blocks:
        current_index = len(blocks) - 1

    current_block = blocks[current_index] if current_index is not None else None

    nearby_blocks: list[dict] = []
    if current_index is not None:
        half = window // 2
        start = max(0, current_index - half)
        end = min(len(blocks), current_index + half + 1)
        for i in range(start, end):
            if i != current_index:
                nearby_blocks.append(_slim_block(blocks[i]))

    section = current_section
    if not section and current_index is not None:
        for i in range(current_index, -1, -1):
            if blocks[i].get("type") in {"heading", "subheading", "subsubheading"}:
                section = blocks[i].get("text", "")
                break

    current_page = _block_page(current_block) if current_block else None

    formulas = [
        {
            "id": b.get("id"),
            "latex": b.get("latex") or b.get("text", ""),
            "page_number": _block_page(b),
            "llm_assets": _block_asset_entries(b),
        }
        for b in blocks
        if b.get("type") == "formula" and _page_distance(b, current_page) <= 2
    ][:4]

    figures = [
        {
            "id": b.get("id"),
            "caption": b.get("caption") or b.get("text", ""),
            "page_number": _block_page(b),
            "image_path": b.get("image_path"),
            "llm_assets": _block_asset_entries(b),
        }
        for b in blocks
        if b.get("type") == "figure" and _page_distance(b, current_page) <= 2
    ][:3]

    tables = [
        {
            "id": b.get("id"),
            "markdown": (b.get("markdown") or b.get("text", ""))[:300],
            "page_number": _block_page(b),
            "llm_assets": _block_asset_entries(b),
        }
        for b in blocks
        if b.get("type") == "table" and _page_distance(b, current_page) <= 2
    ][:2]

    return {
        "document_title": document_title,
        "current_section": section,
        "current_block": _slim_block(current_block) if current_block else None,
        "nearby_blocks": nearby_blocks,
        "formulas": formulas,
        "figures": figures,
        "tables": tables,
        "learning_goals": [],
    }


def build_llm_context_markdown(
    blocks: list[dict[str, Any]],
    current_block_id: str | None = None,
    window: int = 8,
    document_title: str = "",
) -> str:
    ctx = build_llm_context(blocks, current_block_id, window, document_title)
    lines: list[str] = []

    if ctx.get("document_title"):
        lines.append(f"# {ctx['document_title']}\n")
    if ctx.get("current_section"):
        lines.append(f"## {ctx['current_section']}\n")

    current = ctx.get("current_block")
    if current:
        label = _TYPE_LABELS.get(current.get("type", ""), "")
        text = current.get("text", "")
        if label:
            lines.append(f"### {label}\n\n{text}\n")
        else:
            lines.append(f"{text}\n")

    nearby = ctx.get("nearby_blocks", [])
    if nearby:
        lines.append("### Contexte adjacent\n")
        for b in nearby:
            label = _TYPE_LABELS.get(b.get("type", ""), "")
            text = b.get("text", "")[:200]
            if text:
                prefix = f"**{label}** — " if label else ""
                lines.append(f"{prefix}{text}\n")

    formulas = ctx.get("formulas", [])
    if formulas:
        lines.append("### Formules associées\n")
        for f in formulas:
            lines.append(f"- `{f.get('latex') or ''}`\n")

    return "\n".join(lines)


def _find_block_index(blocks: list[dict], block_id: str | None) -> int | None:
    if not block_id:
        return None
    for i, b in enumerate(blocks):
        if b.get("id") == block_id:
            return i
    return None


def _slim_block(block: dict) -> dict:
    data = {
        "id": block.get("id"),
        "type": block.get("type", "paragraph"),
        "text": (block.get("text") or "")[:500],
    }
    page = _block_page(block)
    if page is not None:
        data["page_number"] = page
    assets = _block_asset_entries(block)
    if assets:
        data["llm_assets"] = assets
    return data


def _block_page(block: dict) -> int | None:
    val = block.get("page_number") or block.get("page") or block.get("page_start")
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _page_distance(block: dict, reference_page: int | None) -> int:
    if reference_page is None:
        return 0
    page = _block_page(block)
    if page is None:
        return 0
    return abs(page - reference_page)


def _block_asset_entries(block: dict) -> list[dict[str, str]]:
    metadata = block.get("metadata") or {}
    entries: list[dict[str, str]] = []

    for asset in metadata.get("llm_assets") or []:
        if isinstance(asset, dict) and asset.get("type") == "image" and asset.get("path"):
            entries.append({
                "type": "image",
                "path": str(asset.get("path")),
                "reason": str(asset.get("reason") or "context_asset"),
            })

    for key, reason in (
        ("visible_asset_path", "visible_asset"),
        ("block_crop_path", "block_crop"),
        ("context_asset_path", "context_crop"),
        ("formula_image_path", "formula_crop"),
        ("table_image_path", "table_crop"),
    ):
        path = metadata.get(key)
        if path:
            entries.append({"type": "image", "path": str(path), "reason": reason})

    image_path = block.get("image_path")
    if image_path and block.get("type") in {"figure", "formula"}:
        entries.append({"type": "image", "path": str(image_path), "reason": str(block.get("type"))})

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        path = entry["path"]
        if path in seen:
            continue
        deduped.append(entry)
        seen.add(path)
    return deduped[:4]
