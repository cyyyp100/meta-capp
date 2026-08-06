"""Lecture de fichiers de code (services/code_reader.py) — sans DB ni serveur."""
from __future__ import annotations

import pytest

from services import code_reader


def _write(tmp_path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_is_code_file_by_extension_and_name(tmp_path):
    assert code_reader.is_code_file(_write(tmp_path, "a.py", "x = 1\n"))
    assert code_reader.is_code_file(_write(tmp_path, "Dockerfile", "FROM x\n"))
    assert code_reader.is_code_file(_write(tmp_path, "b.ts", "const x = 1\n"))
    assert not code_reader.is_code_file(_write(tmp_path, "photo.png", "\x89PNG"))


def test_detect_language(tmp_path):
    assert code_reader.detect_language(_write(tmp_path, "a.py", "")) == "python"
    assert code_reader.detect_language(_write(tmp_path, "a.rs", "")) == "rust"
    assert code_reader.detect_language(_write(tmp_path, "Makefile", "")) == "makefile"
    assert code_reader.detect_language(_write(tmp_path, "a.unknownext", "")) == "text"


def test_pagination_counts(tmp_path):
    lines = "\n".join(f"line {i}" for i in range(100))  # 100 lignes
    path = _write(tmp_path, "big.py", lines)
    assert code_reader.line_count(path) == 100
    # 45 lignes/page → 100 lignes = 3 pages.
    assert code_reader.page_count(path) == 3


def test_empty_file_is_one_page(tmp_path):
    path = _write(tmp_path, "empty.py", "")
    assert code_reader.page_count(path) == 1


def test_page_block_shape_and_slicing(tmp_path):
    lines = "\n".join(f"L{i}" for i in range(60))
    path = _write(tmp_path, "s.py", lines)
    block = code_reader.page_block(path, 2)
    assert block["type"] == "code"
    assert block["page"] == 2
    assert block["metadata"]["lang"] == "python"
    # Page 2 commence à la 46e ligne (index 45).
    assert block["metadata"]["start_line"] == 46
    assert block["text"].splitlines()[0] == "L45"


def test_page_text_is_numbered_for_llm(tmp_path):
    path = _write(tmp_path, "n.py", "alpha\nbeta\n")
    text = code_reader.page_text(path, 1)
    assert "n.py" in text and "python" in text
    assert "1 | alpha" in text
    assert "2 | beta" in text


def test_binary_file_rejected(tmp_path):
    p = tmp_path / "blob.py"
    p.write_bytes(b"\x00\x01\x02binary")
    with pytest.raises(ValueError):
        code_reader.page_count(str(p))
