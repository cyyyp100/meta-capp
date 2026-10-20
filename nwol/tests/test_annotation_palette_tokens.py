"""La palette de la prise de notes est un vocabulaire FERMÉ, tenu à trois endroits.

`config/settings.ANNOTATION_COLORS` (ce que le serveur accepte), le jeton
`--note-<clé>` de `theme/tokens.css` (ce que la page dessine) et le nom
accessible `annotations.color.<clé>` des deux dictionnaires du frontend (ce
qu'un lecteur d'écran annonce), plus la liste de `annotations/palette.ts`. Une
couleur ajoutée d'un côté seulement serait refusée, invisible ou muette.
"""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _ts_block(source: str, name: str) -> str:
    match = re.search(rf"const {name}: Record<string, string> = \{{(.*?)\n\}};", source, re.S)
    assert match is not None, f"Bloc {name} introuvable dans index.ts"
    return match.group(1)


def test_every_color_has_a_token_a_name_and_a_place_in_the_palette():
    from config.settings import ANNOTATION_COLORS, ANNOTATION_DEFAULT_COLOR, ANNOTATION_PRESETS, ANNOTATION_STYLES

    tokens = (FRONTEND / "theme" / "tokens.css").read_text(encoding="utf-8")
    root = tokens[tokens.index("\n:root {"):tokens.index('\n[data-theme="dark"] {')]
    i18n = (FRONTEND / "i18n" / "index.ts").read_text(encoding="utf-8")
    palette = (FRONTEND / "features" / "reader" / "annotations" / "palette.ts").read_text(encoding="utf-8")
    colors_at = palette.index("export const ANNOTATION_COLORS")
    styles_at = palette.index("export const ANNOTATION_STYLES")
    frontend_colors = re.findall(r'"([a-z]+)"', palette[colors_at:styles_at])
    frontend_styles = re.findall(r'"([a-z]+)"', palette[styles_at:palette.index("export const NEUTRAL_COLOR")])

    assert tuple(frontend_colors) == ANNOTATION_COLORS
    assert tuple(frontend_styles) == ANNOTATION_STYLES
    assert ANNOTATION_DEFAULT_COLOR in ANNOTATION_COLORS
    assert {color for _, color in ANNOTATION_PRESETS} <= set(ANNOTATION_COLORS)
    for color in ANNOTATION_COLORS:
        assert re.search(rf"--note-{color}:\s*#[0-9a-f]{{6}};", root), f"--note-{color} absent de :root"
        for name in ("FR", "EN"):
            assert f'"annotations.color.{color}":' in _ts_block(i18n, name), f"annotations.color.{color} ({name})"
    for style in ANNOTATION_STYLES:
        for name in ("FR", "EN"):
            assert f'"annotations.style.{style}":' in _ts_block(i18n, name), f"annotations.style.{style} ({name})"


def test_every_preset_is_named_on_both_sides():
    from config.settings import ANNOTATION_PRESETS
    from i18n import STRINGS

    i18n = (FRONTEND / "i18n" / "index.ts").read_text(encoding="utf-8")
    for preset, _ in ANNOTATION_PRESETS:
        for lang in ("fr", "en"):
            assert f"annotations.preset.{preset}" in STRINGS[lang]
        for name in ("FR", "EN"):
            assert f'"annotations.preset.{preset}":' in _ts_block(i18n, name)
