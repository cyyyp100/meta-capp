# core/latex.py — Rendu formules LaTeX → image Tkinter via matplotlib mathtext
from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("LaTeX")

_MPL_LOCK = threading.RLock()
_MATPLOTLIB_UNAVAILABLE = False

# Commandes non supportées par matplotlib mathtext → substituts compatibles
_COMPAT_SUBS: list[tuple[re.Pattern[str], str]] = [
    # \vec{x} → \mathbf{x}  (mathtext n'a pas \vec)
    (re.compile(r"\\vec\{([^{}]+)\}"), r"\\mathbf{\1}"),
    # \overrightarrow{AB} → \stackrel{\rightarrow}{AB}
    (re.compile(r"\\overrightarrow\{([^{}]+)\}"), r"\\stackrel{\\rightarrow}{\1}"),
    # \overleftarrow{AB} → \stackrel{\leftarrow}{AB}
    (re.compile(r"\\overleftarrow\{([^{}]+)\}"), r"\\stackrel{\\leftarrow}{\1}"),
    # \operatorname{f} → \mathrm{f}
    (re.compile(r"\\operatorname\{([^{}]+)\}"), r"\\mathrm{\1}"),
    # \widehat{x} → \hat{x}
    (re.compile(r"\\widehat\{([^{}]+)\}"), r"\\hat{\1}"),
    # \widetilde{x} → \tilde{x}
    (re.compile(r"\\widetilde\{([^{}]+)\}"), r"\\tilde{\1}"),
    # \not= → \neq
    (re.compile(r"\\not\s*="), r"\\neq"),
    # \not< → \not<  (garder tel quel, matplotlib le gère)
    # \ell → l  (si non supporté)
    # \, \; \: → espace fine (mathtext les ignore proprement)
    (re.compile(r"\\[,;:]"), " "),
    # \! → rien (espace négative, ignorée)
    (re.compile(r"\\!"), ""),
    # \quad \qquad → espace
    (re.compile(r"\\q?quad"), " \\; "),
    # \text{...} → \mathrm{...}  (plus robuste dans mathtext)
    (re.compile(r"\\text\{([^{}]*)\}"), r"\\mathrm{\1}"),
    # Environnements non supportés → supprimés (begin/end)
    (re.compile(r"\\begin\{[^}]+\}|\\end\{[^}]+\}"), ""),
    # \hline, \\ → ignorés (dans les matrices)
    (re.compile(r"\\hline|\\\\"), " "),
    # & (séparateur colonne) → espace
    (re.compile(r"(?<!\\)&"), " "),
    # Doubles backslashes restants
    (re.compile(r"\\\\"), " "),
]

# Détection d'un environnement matriciel
_MATRIX_ENV_RE = re.compile(r"\\begin\{(?:p?matrix|array|cases|bmatrix|vmatrix|Vmatrix)\}")
_TRUNCATED_COMMAND_RE = re.compile(r"\\(?:tex|text)\s*$")
_COMMAND_REQUIRING_ARGUMENT_RE = re.compile(
    r"\\(?:frac|dfrac|tfrac|sqrt|mathrm|mathbf|mathbb|mathcal|mathsf|mathtt|operatorname|"
    r"hat|tilde|bar|overline|underline|vec|overrightarrow|overleftarrow|stackrel)\s*$"
)
_EMPTY_SQRT_RE = re.compile(r"\\sqrt\s*\{\s*\}")

_PLAIN_SUBS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\\alpha\b"), "α"),
    (re.compile(r"\\beta\b"), "β"),
    (re.compile(r"\\gamma\b"), "γ"),
    (re.compile(r"\\delta\b"), "δ"),
    (re.compile(r"\\epsilon\b|\\varepsilon\b"), "ε"),
    (re.compile(r"\\theta\b|\\vartheta\b"), "θ"),
    (re.compile(r"\\lambda\b"), "λ"),
    (re.compile(r"\\mu\b"), "μ"),
    (re.compile(r"\\tau\b"), "τ"),
    (re.compile(r"\\pi\b"), "π"),
    (re.compile(r"\\sigma\b"), "σ"),
    (re.compile(r"\\phi\b|\\varphi\b"), "φ"),
    (re.compile(r"\\omega\b"), "ω"),
    (re.compile(r"\\ell\b"), "ℓ"),
    (re.compile(r"\\infty\b"), "∞"),
    (re.compile(r"\\leq?\b"), "≤"),
    (re.compile(r"\\geq?\b"), "≥"),
    (re.compile(r"\\neq\b"), "≠"),
    (re.compile(r"\\approx\b"), "≈"),
    (re.compile(r"\\sim\b"), "∼"),
    (re.compile(r"\\to\b|\\rightarrow\b"), "→"),
    (re.compile(r"\\leftarrow\b"), "←"),
    (re.compile(r"\\cdot\b|\\times\b"), "·"),
    (re.compile(r"\\pm\b"), "±"),
    (re.compile(r"\\dots\b|\\ldots\b|\\cdots\b"), "…"),
]


def _prepare_latex(latex: str) -> str:
    """Prépare le LaTeX brut pour matplotlib mathtext."""
    s = latex.strip()
    # Retirer délimiteurs $...$ ou $$...$$
    if s.startswith("$$") and s.endswith("$$"):
        s = s[2:-2].strip()
    elif s.startswith("$") and s.endswith("$"):
        s = s[1:-1].strip()
    s = s.replace("\\\\", "\\")

    for pattern, replacement in _COMPAT_SUBS:
        s = pattern.sub(replacement, s)

    # Rééquilibrer les accolades si nécessaire
    opened = s.count("{")
    closed = s.count("}")
    if opened > closed:
        s += "}" * (opened - closed)
    elif closed > opened:
        s = "{" * (closed - opened) + s

    return s.strip()


def latex_to_plain_text(latex: str) -> str:
    """Best-effort text fallback for formulas when image rendering is unavailable."""
    s = (latex or "").strip()
    if s.startswith("$$") and s.endswith("$$"):
        s = s[2:-2].strip()
    elif s.startswith("$") and s.endswith("$"):
        s = s[1:-1].strip()
    s = s.replace("\\\\", "\\")

    s = re.sub(r"\\(?:left|right)\b", "", s)
    s = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)", s)
    # \sqrt{} with empty braces + external subscript → √(subscript)
    s = re.sub(r"\\sqrt\s*\{\s*\}\s*_\s*\{([^{}]+)\}", r"√(\1)", s)
    s = re.sub(r"\\sqrt\s*\{\s*\}\s*_([A-Za-z0-9])", r"√(\1)", s)
    s = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"√(\1)", s)
    s = re.sub(r"\\(?:mathrm|mathbf|mathit|mathsf|mathtt|mathcal|mathbb|operatorname|text)\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\hat\s*\{([^{}]+)\}", r"\1̂", s)
    s = re.sub(r"\\tilde\s*\{([^{}]+)\}", r"\1̃", s)
    s = re.sub(r"\\bar\s*\{([^{}]+)\}", r"\1̄", s)

    for pattern, replacement in _PLAIN_SUBS:
        s = pattern.sub(replacement, s)

    s = re.sub(r"([_^])\{([^{}]+)\}", _plain_script, s)
    s = re.sub(r"\\[,;:!]", " ", s)
    s = re.sub(r"\\q?quad\b", " ", s)
    s = re.sub(r"\\begin\{[^}]+\}|\\end\{[^}]+\}", "", s)
    s = re.sub(r"\\[A-Za-z]+", "", s)
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or (latex or "").replace("$", "").strip()


def _plain_script(match: re.Match[str]) -> str:
    marker = match.group(1)
    content = match.group(2).strip()
    if re.fullmatch(r"[A-Za-z0-9]+", content):
        return f"{marker}{content}"
    return f"{marker}({content})"


def _ensure_matplotlib_config_dir() -> None:
    cache_root = Path(tempfile.gettempdir()) / "nwol_matplotlib"
    try:
        config_dir = cache_root / "config"
        xdg_cache = cache_root / "cache"
        config_dir.mkdir(parents=True, exist_ok=True)
        xdg_cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(config_dir))
        os.environ.setdefault("XDG_CACHE_HOME", str(xdg_cache))
    except OSError:
        pass


_ensure_matplotlib_config_dir()


def _matplotlib_backend():
    global _MATPLOTLIB_UNAVAILABLE
    if _MATPLOTLIB_UNAVAILABLE:
        return None

    _ensure_matplotlib_config_dir()
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except Exception as exc:
        _MATPLOTLIB_UNAVAILABLE = True
        logger.warning("Rendu LaTeX image désactivé : matplotlib indisponible (%s)", exc)
        return None

    return matplotlib, Figure, FigureCanvasAgg


def _render_matplotlib_text(
    content: str,
    dpi: int,
    fontsize: int,
    *,
    color: str,
    math: bool,
    fontfamily: str | None = None,
) -> bytes | None:
    backend = _matplotlib_backend()
    if backend is None:
        return None

    matplotlib, Figure, FigureCanvasAgg = backend
    rc_params = {"mathtext.fontset": "stix", "font.family": "STIXGeneral"} if math else {}
    fig = None
    buf = io.BytesIO()

    with _MPL_LOCK:
        try:
            with matplotlib.rc_context(rc_params):
                fig = Figure(figsize=(0.01, 0.01), dpi=dpi)
                FigureCanvasAgg(fig)
                text_kwargs = {"fontsize": fontsize, "color": color}
                if fontfamily:
                    text_kwargs["fontfamily"] = fontfamily
                fig.text(0, 0, content, **text_kwargs)
                fig.savefig(
                    buf,
                    format="png",
                    dpi=dpi,
                    bbox_inches="tight",
                    transparent=True,
                    pad_inches=0.05,
                )
        finally:
            if fig is not None:
                fig.clear()

    buf.seek(0)
    return buf.read()


def _has_unsupported_env(latex: str) -> bool:
    return bool(_MATRIX_ENV_RE.search(latex))


def _is_obviously_unrenderable_latex(latex: str) -> bool:
    s = (latex or "").strip()
    if s.startswith("$$") and s.endswith("$$"):
        s = s[2:-2].strip()
    elif s.startswith("$") and s.endswith("$"):
        s = s[1:-1].strip()
    if not s:
        return True
    if _TRUNCATED_COMMAND_RE.fullmatch(s):
        return True
    if _COMMAND_REQUIRING_ARGUMENT_RE.search(s):
        return True
    # \sqrt{} with empty braces causes matplotlib ParseFatalException
    if _EMPTY_SQRT_RE.search(s):
        return True
    return False


@lru_cache(maxsize=512)
def render_formula(latex: str, display: bool = True, dpi: int = 180) -> bytes | None:
    """
    Génère une image PNG (bytes) d'une formule LaTeX via matplotlib mathtext.
    Utilise la police STIX pour supporter \\mathbb, \\mathcal, etc.
    Retourne None en cas d'échec.
    """
    if _is_obviously_unrenderable_latex(latex):
        return None

    try:
        # Environnements matriciels non supportés → fallback texte
        if _has_unsupported_env(latex):
            return _render_as_text(latex, dpi)

        prepared = _prepare_latex(latex)
        if not prepared:
            return None

        expr = f"${prepared}$"
        fontsize = 20 if display else 16

        return _render_matplotlib_text(
            expr,
            dpi,
            fontsize,
            color="#1A1A1A",
            math=True,
        )

    except Exception as exc:
        logger.warning("Rendu LaTeX échoué (%r) : %s — tentative simplifiée", latex[:60], exc)
        return _render_simplified(latex, dpi)


def _render_simplified(latex: str, dpi: int) -> bytes | None:
    """Deuxième tentative avec expression simplifiée (retire commandes inconnues)."""
    try:
        # Supprimer toutes les commandes \xxx inconnues pour ne garder que la structure
        cleaned = re.sub(r"\\[a-zA-Z]+", "", _prepare_latex(latex))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return None

        expr = f"${cleaned}$"
        return _render_matplotlib_text(
            expr,
            dpi,
            15,
            color="#1A1A1A",
            math=True,
        )
    except Exception as exc:
        logger.error("Rendu simplifié échoué : %s", exc)
        return None


def _render_as_text(latex: str, dpi: int) -> bytes | None:
    """Rendu d'une expression comme texte brut (fallback pour matrices)."""
    try:
        # Nettoyer pour affichage texte
        text = re.sub(r"\\begin\{[^}]+\}|\\end\{[^}]+\}", "", latex)
        text = re.sub(r"\\[a-zA-Z]+", "", text)
        text = re.sub(r"[{}]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None

        return _render_matplotlib_text(
            text,
            dpi,
            14,
            color="#555555",
            math=False,
            fontfamily="monospace",
        )
    except Exception as exc:
        logger.error("Rendu texte brut échoué : %s", exc)
        return None


def formula_to_tk_image(latex: str, display: bool = True, max_height: int | None = None):
    """
    Retourne un objet PhotoImage Tkinter (ou None).
    Doit être conservé en référence pour éviter la GC.
    """
    if not latex or not latex.strip():
        return None
    try:
        from PIL import Image, ImageTk
        dpi = 180 if display else 210
        png_bytes = render_formula(latex, display, dpi)
        if png_bytes is None:
            return None
        img = Image.open(io.BytesIO(png_bytes))
        if max_height and img.height > max_height:
            ratio = max_height / img.height
            img = img.resize((max(1, int(img.width * ratio)), max_height), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception as exc:
        logger.error("Conversion PIL→Tkinter échouée : %s", exc)
        return None
