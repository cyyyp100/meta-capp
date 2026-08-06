from __future__ import annotations

import re
import unicodedata


MATH_SPAN_PATTERN = re.compile(
    r"\$\$(.+?)\$\$"
    r"|\\\[(.+?)\\\]"
    r"|\\\((.+?)\\\)"
    r"|\$(.+?)\$",
    re.DOTALL,
)

_FOMAML_META_GRADIENT_SPLIT_RE = re.compile(
    r"\bg\s*FOMAM\s*\$+\s*L\s*=\s*g\s*\$+\s*k\b"
)
_FOMAML_META_GRADIENT_PLAIN_RE = re.compile(
    r"\bg\s*FOMAM\s*L\s*=\s*g\s*k\b"
)
_SCRIPTED_RUN_RE = re.compile(
    r"(?<![$\\\w])"
    r"("
    r"(?:[A-Za-z]{1,3}(?:[_^](?:\{[^{}$\n]{1,40}\}|[A-Za-z0-9]{1,20}))+){1,5}"
    r")"
    r"(?![$\w])"
)
_BARE_SQRT_RE = re.compile(
    r"(?<![$\\])"
    r"(\\sqrt\s*\{[^{}$\n]{1,40}\}(?:\s*[_^]\{[^{}$\n]{1,40}\})?)"
    r"(?!\$)"
)
_SQRT_DK_FRAGMENT_RE = re.compile(r"\^\{\s*√\s*\}_\{\s*d\s*\}_\{\s*k\s*\}")
_SQRT_DK_UNICODE_RE = re.compile(r"√\s*_?\{\s*d\s*\}\s*_?\{\s*k\s*\}")
_MALFORMED_ORPHAN_SQRT_DK_RE = re.compile(
    r"(?<![$\\\w])[_^]\s*\{\s*\\+sqrt\s*\{\s*\}\s*"
    r"(?:_\s*\{\s*d\s*k\s*\}|_\s*\{\s*d\s*\}\s*_\s*\{\s*k\s*\}|_\s*d\s*k)"
    r"\s*\}\s*[\.,;:]?",
    re.I,
)
_REPAIRED_ORPHAN_SQRT_DK_RE = re.compile(
    r"(?<![$\\\w])[_^]\s*\{\s*\\+sqrt\s*\{\s*d\s*_\s*k\s*\}\s*\}\s*[\.,;:]?",
    re.I,
)
_EMPTY_SQRT_COMMAND_RE = re.compile(r"\\+sqrt\s*\{\s*\}")
_ONE_OVER_SQRT_DK_TEXT_RE = re.compile(
    r"\b1\s*(?:/|\s+of\s+)?\s*√\s*\(?\s*d\s*(?:_\s*\{?\s*k\s*\}?|\{\s*k\s*\})\s*\)?",
    re.I,
)
_ONE_OVER_LATEX_SQRT_DK_RE = re.compile(
    r"\b1\s*(?:/|\s+of\s+)?\s*"
    r"\\sqrt\s*\{\s*d\s*(?:_\s*\{?\s*k\s*\}?|\{\s*k\s*\})?\s*\}"
    r"(?:\s*_\{\s*k\s*\})?",
    re.I,
)
_SQRT_DK_TEXT_RE = re.compile(
    r"(?<![$\\])√\s*\(?\s*d\s*(?:_\s*\{?\s*k\s*\}?|\{\s*k\s*\})\s*\)?",
    re.I,
)
_PLAIN_SQRT_PAREN_RE = re.compile(
    r"(?<![$\\\w])sqrt\s*\(\s*([^()$\n]{1,80})\s*\)(?!\s*\$)",
    re.I,
)
# Prose word (≥5 chars) followed by OCR-noise superscript ^{N} outside math.
# Example: "gradients^{4}" → "gradients"  (footnote ref, not math exponent)
_PROSE_WORD_OCR_SUPERSCRIPT_RE = re.compile(
    r"(?<![${\\])([A-Za-z]{5,})\s*\^\{?([1-9][0-9]?)\}?(?![A-Za-z0-9_{])",
)
# Bare open bracket followed by digit appended to a variable name (no closing ]).
# Example: "d_k[3"  →  "d_k"  (OCR bracket artifact, not array indexing)
_VARIABLE_BARE_BRACKET_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)?)\[(\d+)(?!\])",
)


def repair_common_inline_math_artifacts(text: str | None) -> str:
    """Repair common LLM/OCR math artifacts before persistence or UI rendering."""
    if not text:
        return ""

    repaired = _repair_split_fomaml_meta_gradient(str(text))
    repaired = _repair_undelimited_fomaml_meta_gradient(repaired)
    repaired = _strip_prose_word_ocr_superscripts(repaired)
    repaired = _strip_variable_bare_brackets(repaired)
    repaired = _repair_common_sqrt_fragments(repaired)
    repaired = _remove_malformed_orphan_sqrt_scripts(repaired)
    repaired = _wrap_plain_sqrt_functions(repaired)
    repaired = _wrap_bare_sqrt_commands(repaired)
    repaired = _wrap_undelimited_script_runs(repaired)
    return repaired


_MATH_SIGNAL_RE = re.compile(
    r"\$[^$\n]{1,200}\$|\\[A-Za-z]{2,}|[_^{}=<>]|[∑∫√∞≈≠≤≥→←↔∈∉∀∃αβγδλμσφψω]"
)


def text_contains_math_signal(text: str | None) -> bool:
    """Return True when text contains any LaTeX delimiter, command, or math symbol."""
    return bool(_MATH_SIGNAL_RE.search(text or ""))


def contains_renderable_math(text: str | None) -> bool:
    """Return True only when repaired text contains a delimited math span."""
    repaired = repair_common_inline_math_artifacts(text or "")
    for match in MATH_SPAN_PATTERN.finditer(repaired):
        latex = next((group for group in match.groups() if group is not None), "")
        if latex.strip() and not _EMPTY_SQRT_COMMAND_RE.search(latex):
            return True
    return False


def _repair_split_fomaml_meta_gradient(text: str) -> str:
    return _FOMAML_META_GRADIENT_SPLIT_RE.sub(r"$g^{FOMAML}=g^k$", text)


def _repair_undelimited_fomaml_meta_gradient(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end in _math_ranges(text):
        if cursor < start:
            parts.append(_FOMAML_META_GRADIENT_PLAIN_RE.sub(r"$g^{FOMAML}=g^k$", text[cursor:start]))
        parts.append(text[start:end])
        cursor = end

    if cursor < len(text):
        parts.append(_FOMAML_META_GRADIENT_PLAIN_RE.sub(r"$g^{FOMAML}=g^k$", text[cursor:]))

    return "".join(parts) if parts else _FOMAML_META_GRADIENT_PLAIN_RE.sub(r"$g^{FOMAML}=g^k$", text)


def _math_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    mode: str | None = None
    start = 0
    index = 0

    while index < len(text):
        if mode is None:
            if text.startswith(r"\(", index):
                mode = r"\)"
                start = index
                index += 2
                continue
            if text.startswith(r"\[", index):
                mode = r"\]"
                start = index
                index += 2
                continue
            if text.startswith("$$", index) and not _is_escaped(text, index):
                mode = "$$"
                start = index
                index += 2
                continue
            if text[index] == "$" and not _is_escaped(text, index):
                mode = "$"
                start = index
                index += 1
                continue
            index += 1
            continue

        if mode in {r"\)", r"\]"}:
            if text.startswith(mode, index):
                ranges.append((start, index + 2))
                mode = None
                index += 2
                continue
        elif mode == "$$":
            if text.startswith("$$", index) and not _is_escaped(text, index):
                ranges.append((start, index + 2))
                mode = None
                index += 2
                continue
        elif mode == "$" and text[index] == "$" and not _is_escaped(text, index):
            ranges.append((start, index + 1))
            mode = None
            index += 1
            continue

        index += 1

    return ranges


def _wrap_bare_subscripts(text: str) -> str:
    return _wrap_undelimited_script_runs(text)


def _repair_common_sqrt_fragments(text: str) -> str:
    def replace_one_over_sqrt(match: re.Match[str]) -> str:
        return r"$\frac{1}{\sqrt{d_k}}$"

    text = _ONE_OVER_SQRT_DK_TEXT_RE.sub(replace_one_over_sqrt, text)
    text = _ONE_OVER_LATEX_SQRT_DK_RE.sub(replace_one_over_sqrt, text)
    text = re.sub(
        r"\b1\s+of\s+" + _SQRT_DK_FRAGMENT_RE.pattern,
        replace_one_over_sqrt,
        text,
    )
    text = re.sub(
        r"\b1\s*/\s*" + _SQRT_DK_FRAGMENT_RE.pattern,
        replace_one_over_sqrt,
        text,
    )
    text = _SQRT_DK_FRAGMENT_RE.sub(lambda _match: r"$\sqrt{d_k}$", text)
    text = _SQRT_DK_UNICODE_RE.sub(lambda _match: r"$\sqrt{d_k}$", text)
    text = _SQRT_DK_TEXT_RE.sub(lambda _match: r"$\sqrt{d_k}$", text)
    text = re.sub(r"\\sqrt\s*\{\s*d\s*\}_\{?\s*k\s*\}?", lambda _match: r"\sqrt{d_k}", text)
    # \sqrt{}_{dk} or \sqrt{}_dk (empty braces, subscript outside) → \sqrt{d_k}.
    # Keep already-delimited empty-sqrt spans unrenderable so the UI can reject
    # them instead of silently showing a guessed formula.
    for pattern in (
        r"\\sqrt\s*\{\s*\}\s*_\s*\{\s*d\s*k\s*\}",
        r"\\sqrt\s*\{\s*\}\s*_\s*\{\s*d\s*\}\s*_\s*\{\s*k\s*\}",
        r"\\sqrt\s*\{\s*\}\s*_\s*d\s*k\b",
    ):
        text = _wrap_matches_outside_math(
            text,
            re.compile(pattern, re.I),
            lambda _match: r"\sqrt{d_k}",
        )
    return text


def _remove_malformed_orphan_sqrt_scripts(text: str) -> str:
    original = text
    text = _wrap_matches_outside_math(text, _MALFORMED_ORPHAN_SQRT_DK_RE, lambda _match: "")
    text = _wrap_matches_outside_math(text, _REPAIRED_ORPHAN_SQRT_DK_RE, lambda _match: "")
    if text == original:
        return text
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\b(dot|scale)\s+\.\s+", r"\1 ", text, flags=re.I)
    return text.strip()


def _wrap_bare_sqrt_commands(text: str) -> str:
    return _wrap_matches_outside_math(text, _BARE_SQRT_RE, lambda match: f"${match.group(1).strip()}$")


def _strip_prose_word_ocr_superscripts(text: str) -> str:
    """Remove OCR-noise superscripts from long prose words outside math spans.

    Turns 'gradients^{4}' → 'gradients'.  Leaves short variable names like
    x^{2} alone (they are caught by _wrap_undelimited_script_runs later).
    """
    return _wrap_matches_outside_math(
        text,
        _PROSE_WORD_OCR_SUPERSCRIPT_RE,
        lambda match: match.group(1),
    )


def _strip_variable_bare_brackets(text: str) -> str:
    """Remove bare open-bracket-digit OCR artifacts appended to variable names.

    Turns 'd_k[3' → 'd_k'.  Does not affect proper array indexing like 'a[3]'
    (those have a closing bracket and are not matched).
    """
    return _wrap_matches_outside_math(
        text,
        _VARIABLE_BARE_BRACKET_RE,
        lambda match: match.group(1),
    )


def _wrap_plain_sqrt_functions(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        value = match.group(1).strip()
        if not value:
            return match.group(0)
        return rf"$\sqrt{{{value}}}$"

    return _wrap_matches_outside_math(text, _PLAIN_SQRT_PAREN_RE, repl)


def _wrap_undelimited_script_runs(text: str) -> str:
    math_ranges = _math_ranges(text)
    parts: list[str] = []
    cursor = 0
    for match in _SCRIPTED_RUN_RE.finditer(text):
        if any(start <= match.start() < end for start, end in math_ranges):
            continue
        expression = match.group(1)
        if "@" in expression or _looks_like_false_script_expression(expression):
            continue
        parts.append(text[cursor : match.start()])
        parts.append(f"${expression}$")
        cursor = match.end()
    parts.append(text[cursor:])
    return "".join(parts)


def _wrap_matches_outside_math(text: str, pattern: re.Pattern[str], replacement) -> str:
    math_ranges = _math_ranges(text)
    parts: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        if any(start <= match.start() < end for start, end in math_ranges):
            continue
        parts.append(text[cursor : match.start()])
        parts.append(replacement(match))
        cursor = match.end()
    parts.append(text[cursor:])
    return "".join(parts)


def _looks_like_false_script_expression(expression: str) -> bool:
    return not bool(re.search(r"[_^](?:\{[^{}$\n]{1,40}\}|[A-Za-z0-9]{1,20})", expression))


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


# ---------------------------------------------------------------------------
# Unicode → LaTeX normalisation et qualité des formules.
# (Anciennement document/postprocess/{math_normalizer,latex_quality}.py ;
#  rapatriés ici lors du passage au lecteur page-par-page, sans dépendance
#  au moteur d'extraction supprimé.)
# ---------------------------------------------------------------------------

_UNICODE_TO_LATEX: dict[str, str] = {
    # Flèches
    "←": r"\leftarrow", "↑": r"\uparrow", "→": r"\rightarrow", "↓": r"\downarrow",
    "↔": r"\leftrightarrow", "↦": r"\mapsto", "⇒": r"\Rightarrow", "⇔": r"\Leftrightarrow",
    "⟹": r"\Longrightarrow", "⟺": r"\Longleftrightarrow",
    # Relations et ensembles
    "≠": r"\neq", "≈": r"\approx", "≅": r"\cong", "∼": r"\sim", "≃": r"\simeq",
    "≡": r"\equiv", "≤": r"\leq", "≥": r"\geq", "≦": r"\leq", "≧": r"\geq",
    "≪": r"\ll", "≫": r"\gg", "∝": r"\propto", "∥": r"\parallel", "⊥": r"\perp",
    "∈": r"\in", "∉": r"\notin", "∋": r"\ni", "⊂": r"\subset", "⊆": r"\subseteq",
    "⊄": r"\nsubset", "⊃": r"\supset", "⊇": r"\supseteq", "⊈": r"\nsubseteq",
    "⊉": r"\nsupseteq", "∪": r"\cup", "∩": r"\cap", "∅": r"\emptyset", "∖": r"\setminus",
    "∀": r"\forall", "∃": r"\exists", "∄": r"\nexists", "∴": r"\therefore", "∵": r"\because",
    "ℕ": r"\mathbb{N}", "ℤ": r"\mathbb{Z}", "ℚ": r"\mathbb{Q}", "ℝ": r"\mathbb{R}",
    "ℂ": r"\mathbb{C}", "ℙ": r"\mathbb{P}",
    # Opérateurs
    "±": r"\pm", "∓": r"\mp", "×": r"\times", "⋅": r"\cdot", "·": r"\cdot", "÷": r"\div",
    "∞": r"\infty", "∑": r"\sum", "∏": r"\prod", "∫": r"\int", "∬": r"\iint",
    "∭": r"\iiint", "∮": r"\oint", "√": r"\sqrt", "∛": r"\sqrt[3]", "∜": r"\sqrt[4]",
    "∂": r"\partial", "∇": r"\nabla", "∆": r"\Delta", "∧": r"\wedge", "∨": r"\vee",
    "¬": r"\neg", "⌊": r"\lfloor", "⌋": r"\rfloor", "⌈": r"\lceil", "⌉": r"\rceil",
    "°": r"^\circ", "′": r"'", "″": r"''", "−": "-",
    # Lettres grecques minuscules
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\epsilon",
    "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta", "ι": r"\iota", "κ": r"\kappa",
    "λ": r"\lambda", "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi", "ο": "o", "π": r"\pi",
    "ρ": r"\rho", "ς": r"\varsigma", "σ": r"\sigma", "τ": r"\tau", "υ": r"\upsilon",
    "φ": r"\phi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega", "ϕ": r"\varphi",
    "ϵ": r"\varepsilon", "ϑ": r"\vartheta",
    # Lettres grecques majuscules
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda", "Ξ": r"\Xi",
    "Π": r"\Pi", "Σ": r"\Sigma", "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega", "ℓ": r"\ell",
    # Suppléments
    "‖": r"\|", "∣": r"|", "⌀": r"\emptyset", "⟨": r"\langle", "⟩": r"\rangle",
    "⊕": r"\oplus", "⊗": r"\otimes", "⊙": r"\odot", "⌃": r"\wedge", "∐": r"\coprod",
    "⊔": r"\sqcup", "⊓": r"\sqcap", "≺": r"\prec", "≻": r"\succ", "⋯": r"\cdots", "…": r"\ldots",
    # Indices Unicode
    "₀": "_0", "₁": "_1", "₂": "_2", "₃": "_3", "₄": "_4", "₅": "_5", "₆": "_6",
    "₇": "_7", "₈": "_8", "₉": "_9", "₊": "_+", "₋": "_-", "₌": "_=", "₍": "_(", "₎": "_)",
    "ₐ": "_a", "ₑ": "_e", "ₕ": "_h", "ᵢ": "_i", "ⱼ": "_j", "ₖ": "_k", "ₗ": "_l",
    "ₘ": "_m", "ₙ": "_n", "ₒ": "_o", "ₚ": "_p", "ₛ": "_s", "ₜ": "_t", "ₓ": "_x",
    # Exposants Unicode
    "⁰": "^0", "¹": "^1", "²": "^2", "³": "^3", "⁴": "^4", "⁵": "^5", "⁶": "^6",
    "⁷": "^7", "⁸": "^8", "⁹": "^9", "⁺": "^+", "⁻": "^-", "⁼": "^=", "⁽": "^(",
    "⁾": "^)", "ⁱ": "^i", "ⁿ": "^n",
}

_MULTICHAR_UNICODE_TO_LATEX: dict[str, str] = {
    "̸=": r"\neq", "≠": r"\neq", "≮": r"\not<", "≯": r"\not>",
    "̸∈": r"\notin", "∉": r"\notin",
}
_MULTICHAR_REGEX_TO_LATEX: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"̸\s*="), r"\neq"),
    (re.compile(r"=\s*̸"), r"\neq"),
    (re.compile(r"̸\s*∈"), r"\notin"),
    (re.compile(r"∈\s*̸"), r"\notin"),
    (re.compile(r"<\s*̸"), r"\not<"),
    (re.compile(r">\s*̸"), r"\not>"),
)


def _is_latex_command(value: str) -> bool:
    return value.startswith("\\") and len(value) > 1 and value[1].isalpha()


def normalize_unicode_math(text: str) -> str:
    """Convertit les symboles mathématiques Unicode en commandes LaTeX."""
    text = unicodedata.normalize("NFC", text or "")
    for pattern, replacement in _MULTICHAR_REGEX_TO_LATEX:
        text = pattern.sub(lambda _match, value=replacement: f" {value} ", text)
    for pattern, replacement in _MULTICHAR_UNICODE_TO_LATEX.items():
        text = text.replace(pattern, f" {replacement} " if replacement.startswith("\\") else replacement)

    parts: list[str] = []
    for char in text:
        replacement = _UNICODE_TO_LATEX.get(char)
        if replacement is None:
            parts.append(char)
            continue
        if _is_latex_command(replacement):
            parts.append(f" {replacement} ")
        else:
            parts.append(replacement)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


_SPLIT_COMMAND_RE = re.compile(r"\\(?:\s+[A-Za-z]){2,}")
_SPACED_TEXT_CMD_RE = re.compile(r"\\t\s+e\s+x\s+t|\\tex\s+t|\\t\s+h\s+(?:e|ta)", re.I)
_ORPHAN_SCRIPT_RE = re.compile(r"^\s*(?:\${1,2})?\s*[_^]\{")
_EMPTY_SCRIPT_RUN_RE = re.compile(r"(?:\^\{\s*\}\s*\^|_\{\s*\}\s*_|_\{\s*['`]?_\{\s*\}\})")
_BROKEN_COMMAND_WITH_WORD_RE = re.compile(r"\\\s+[A-Za-z]\s+[A-Za-z](?:\s+[A-Za-z])?")
_SINGLE_EMPTY_SCRIPT_RE = re.compile(r"[A-Za-z0-9]\s*[_^]\{\s*\}")
_WORD_FRAGMENT_SUBSCRIPT_RE = re.compile(r"[_^]\{[A-Za-z]{5,}\}")
_NAKED_DOLLAR_MID_FORMULA_RE = re.compile(r"[A-Za-z0-9]\$[A-Za-z]")


def strip_formula_delimiters(text: str | None) -> str:
    value = str(text or "").strip()
    if value.startswith("$$") and value.endswith("$$") and len(value) >= 4:
        return value[2:-2].strip()
    if value.startswith("$") and value.endswith("$") and len(value) >= 2:
        return value[1:-1].strip()
    return value


def latex_looks_corrupt(text: str | None) -> bool:
    """Detect LaTeX that is very likely OCR/PDF span noise, not a usable formula."""
    value = strip_formula_delimiters(text)
    if not value:
        return False
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return False

    if _SPLIT_COMMAND_RE.search(value) or _SPACED_TEXT_CMD_RE.search(value):
        return True
    if _ORPHAN_SCRIPT_RE.search(value) and re.search(r"\\\s+[A-Za-z]|_\{\s*['`]?_\{", value):
        return True
    if _EMPTY_SCRIPT_RUN_RE.search(value):
        return True
    if _BROKEN_COMMAND_WITH_WORD_RE.search(value) and re.search(r"[_^{}=]", value):
        return True

    opened = value.count("{")
    closed = value.count("}")
    if abs(opened - closed) >= 2:
        return True

    commands = re.findall(r"\\([A-Za-z]+)", value)
    if any(len(command) == 1 for command in commands) and _BROKEN_COMMAND_WITH_WORD_RE.search(value):
        return True

    if _SINGLE_EMPTY_SCRIPT_RE.search(value):
        return True
    if _NAKED_DOLLAR_MID_FORMULA_RE.search(value):
        return True
    if _WORD_FRAGMENT_SUBSCRIPT_RE.search(value) and (
        _SINGLE_EMPTY_SCRIPT_RE.search(value)
        or _NAKED_DOLLAR_MID_FORMULA_RE.search(value)
        or abs(value.count("{") - value.count("}")) >= 1
    ):
        return True

    return False


def safe_formula_context_text(text: str | None) -> str:
    value = strip_formula_delimiters(text)
    if latex_looks_corrupt(value):
        return ""
    return value
