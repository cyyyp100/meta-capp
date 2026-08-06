# services/code_reader.py — Lecture de fichiers de CODE dans le lecteur.
#
# Un fichier source (n'importe quel langage) est traité comme un « document »
# paginé : le texte est découpé en pages de LINES_PER_PAGE lignes pour réutiliser
# tel quel l'infrastructure du lecteur reconstruit (observer de page dominante,
# marque-page, sélection/surlignage par bloc, contexte LLM par page). Chaque page
# devient UN bloc de type "code" — rendu monospace + numéros de ligne côté client.
#
# Aucune reconstruction, aucun appel réseau : le contenu est relu à la demande
# depuis le chemin d'origine (même politique que le rendu PyMuPDF des PDF).
from __future__ import annotations

import math
import os

__all__ = [
    "is_code_file",
    "detect_language",
    "line_count",
    "page_count",
    "page_block",
    "page_text",
    "supported_extensions",
]

# Découpage en « pages » : compromis lisibilité / nombre de pages.
LINES_PER_PAGE = 45
# Garde-fou : on refuse d'ouvrir un fichier plus gros (probablement pas du code
# à lire, et protège la mémoire).
MAX_BYTES = 5 * 1024 * 1024

# Extension (sans point, minuscule) → étiquette de langage (indicative, sert au
# rendu et au contexte LLM). "text" = pas de coloration particulière.
_EXT_LANG: dict[str, str] = {
    "py": "python", "pyw": "python", "pyi": "python",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript", "jsx": "jsx",
    "ts": "typescript", "tsx": "tsx",
    "java": "java", "kt": "kotlin", "kts": "kotlin", "scala": "scala", "groovy": "groovy",
    "c": "c", "h": "c", "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "hh": "cpp", "hxx": "cpp",
    "cs": "csharp", "go": "go", "rs": "rust", "swift": "swift", "dart": "dart",
    "rb": "ruby", "php": "php", "pl": "perl", "pm": "perl", "lua": "lua",
    "sh": "bash", "bash": "bash", "zsh": "bash", "fish": "bash", "ps1": "powershell", "bat": "batch",
    "sql": "sql", "r": "r", "jl": "julia",
    "m": "objectivec", "mm": "objectivec",
    "html": "html", "htm": "html", "xml": "xml", "svg": "xml",
    "css": "css", "scss": "scss", "sass": "sass", "less": "less",
    "vue": "vue", "svelte": "svelte", "astro": "text",
    "json": "json", "jsonc": "json", "yaml": "yaml", "yml": "yaml", "toml": "toml",
    "ini": "ini", "cfg": "ini", "conf": "ini", "env": "text", "properties": "ini",
    "md": "markdown", "markdown": "markdown", "rst": "text", "tex": "latex",
    "txt": "text", "log": "text", "csv": "text", "tsv": "text",
    "mk": "makefile", "cmake": "cmake", "gradle": "gradle",
    "clj": "clojure", "cljs": "clojure", "cljc": "clojure", "edn": "clojure",
    "ex": "elixir", "exs": "elixir", "erl": "erlang", "hrl": "erlang",
    "hs": "haskell", "ml": "ocaml", "mli": "ocaml", "fs": "fsharp", "fsx": "fsharp",
    "el": "lisp", "lisp": "lisp", "scm": "scheme", "rkt": "scheme",
    "vim": "vim", "tf": "terraform", "hcl": "terraform", "proto": "protobuf",
    "asm": "asm", "s": "asm",
    "graphql": "graphql", "gql": "graphql", "prisma": "text", "sol": "solidity",
    "ipynb": "text",
}

# Fichiers reconnus par leur NOM (sans extension utile).
_NAME_LANG: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    "cmakelists.txt": "cmake",
    "rakefile": "ruby",
    "gemfile": "ruby",
    "vagrantfile": "ruby",
    "brewfile": "ruby",
    ".gitignore": "text",
    ".gitattributes": "text",
    ".dockerignore": "text",
    ".editorconfig": "ini",
    ".env": "text",
    ".bashrc": "bash",
    ".zshrc": "bash",
    ".vimrc": "vim",
}


def supported_extensions() -> set[str]:
    """Extensions (sans point) reconnues comme du code/texte lisible."""
    return set(_EXT_LANG)


def _basename_lower(path: str) -> str:
    return os.path.basename(path).lower()


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lstrip(".").lower()


def is_code_file(path: str) -> bool:
    """Vrai si le chemin ressemble à un fichier source/texte lisible."""
    return _ext(path) in _EXT_LANG or _basename_lower(path) in _NAME_LANG


def detect_language(path: str) -> str:
    """Étiquette de langage (indicative) — 'text' par défaut."""
    ext = _ext(path)
    if ext in _EXT_LANG:
        return _EXT_LANG[ext]
    return _NAME_LANG.get(_basename_lower(path), "text")


def _read_source(path: str) -> str:
    """Lit le fichier en texte (UTF-8 tolérant). Lève ValueError si binaire."""
    size = os.path.getsize(path)
    if size > MAX_BYTES:
        raise ValueError("Fichier trop volumineux pour le lecteur de code (> 5 Mo)")
    with open(path, "rb") as fh:
        raw = fh.read(MAX_BYTES)
    # Un octet nul dans l'entête trahit un binaire (image/exécutable renommé).
    if b"\x00" in raw[:8192]:
        raise ValueError("Le fichier n'est pas du texte lisible")
    return raw.decode("utf-8", errors="replace")


def _lines(path: str) -> list[str]:
    # splitlines() gère \n, \r\n et \r sans laisser de \n résiduel.
    return _read_source(path).splitlines()


def line_count(path: str) -> int:
    return len(_lines(path))


def page_count(path: str) -> int:
    """Nombre de pages (≥ 1) pour la pagination du lecteur."""
    n = len(_lines(path))
    return max(1, math.ceil(n / LINES_PER_PAGE))


def _slice(lines: list[str], page: int) -> tuple[list[str], int]:
    """(lignes de la page, index 0-based de la 1re ligne)."""
    start = max(0, (page - 1) * LINES_PER_PAGE)
    return lines[start : start + LINES_PER_PAGE], start


def page_block(path: str, page: int) -> dict:
    """Bloc unique de type 'code' pour une page — consommé par BlockRenderer.

    `text` = code BRUT de la page (les numéros de ligne sont ajoutés côté client,
    hors du texte, pour ne pas polluer la sélection ni la recherche de citations).
    """
    lines, start = _slice(_lines(path), page)
    return {
        "id": f"code-{page}",
        "type": "code",
        "page": page,
        "reading_order": 0,
        "text": "\n".join(lines),
        "metadata": {"lang": detect_language(path), "start_line": start + 1},
    }


def page_text(path: str, page: int) -> str:
    """Texte de page pour le LLM : code NUMÉROTÉ (Gemma peut citer des lignes).

    Diffère du bloc de rendu (numéros inclus ici) afin d'aider le compagnon à
    localiser et expliquer/déboguer une ligne précise.
    """
    lines, start = _slice(_lines(path), page)
    lang = detect_language(path)
    header = f"# {os.path.basename(path)} — {lang} — lignes {start + 1}–{start + len(lines)}"
    body = "\n".join(f"{start + i + 1:>5} | {line}" for i, line in enumerate(lines))
    return f"{header}\n{body}"
