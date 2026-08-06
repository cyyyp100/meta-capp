# Parité des dictionnaires i18n FR/EN (F11) — backend ET frontend.
import re
from pathlib import Path

FRONTEND_I18N = Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "index.ts"


def test_backend_i18n_parity():
    from i18n import STRINGS

    fr, en = set(STRINGS["fr"]), set(STRINGS["en"])
    assert fr - en == set(), f"Clés FR sans traduction EN : {sorted(fr - en)}"
    assert en - fr == set(), f"Clés EN sans source FR : {sorted(en - fr)}"


def _ts_block_keys(source: str, name: str) -> set[str]:
    match = re.search(rf"const {name}: Record<string, string> = \{{(.*?)\n\}};", source, re.S)
    assert match is not None, f"Bloc {name} introuvable dans index.ts"
    return set(re.findall(r'^\s*"([^"]+)":', match.group(1), re.M))


def test_frontend_i18n_parity():
    source = FRONTEND_I18N.read_text(encoding="utf-8")
    fr = _ts_block_keys(source, "FR")
    en = _ts_block_keys(source, "EN")
    assert fr, "Dictionnaire FR frontend vide (regex à mettre à jour ?)"
    assert fr - en == set(), f"Clés FR sans traduction EN : {sorted(fr - en)}"
    assert en - fr == set(), f"Clés EN sans source FR : {sorted(en - fr)}"
