#!/usr/bin/env python3
# scripts/third_party_notices.py — Mentions des licences tierces d'un binaire.
#
# Toutes les licences des composants embarqués (MIT, BSD, Apache, ISC, OFL,
# MPL, PSF…) exigent que leur texte et leurs mentions de copyright
# accompagnent la redistribution. Le binaire PyInstaller embarque
# l'interpréteur Python, les dépendances de requirements.txt (PDFium compris,
# avec FreeType, libjpeg-turbo, OpenJPEG… et leurs propres mentions) et le
# bundle du frontend. Ce script réunit leurs textes dans
# THIRD_PARTY_NOTICES.txt, que la spec embarque et que la release joint.
#
#   python scripts/third_party_notices.py           # écrit THIRD_PARTY_NOTICES.txt
#   python scripts/third_party_notices.py --check   # et échoue sur une licence non admise
#
# Il lit ce qui est INSTALLÉ (après `pip install -r requirements.txt` et
# `npm ci`), c'est-à-dire ce qui sera embarqué. `--check` est le garde-fou de
# licence : une dépendance copyleft ou sans licence déclarée fait échouer la CI
# avant d'atteindre un binaire (cf. la règle pypdfium2 plutôt que PyMuPDF).
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import re
import sys
from pathlib import Path

try:
    from packaging.requirements import Requirement
except ImportError:  # pragma: no cover - packaging vient avec PyInstaller et pip
    from pip._vendor.packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "THIRD_PARTY_NOTICES.txt"
# Dépendances de test déclarées dans requirements.txt : jamais embarquées.
TEST_ONLY = {"pytest", "reportlab"}
LICENSE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|COPYRIGHT)", re.I)
# Refusé d'office : copyleft fort, licences non libres, licence absente. Tout
# le reste est permissif (MIT, BSD, Apache, ISC, PSF, OFL, MPL au fichier…).
FORBIDDEN = re.compile(r"\bA?GPL|General Public License|SSPL|BUSL|Commons Clause|Non-?Commercial|-NC-", re.I)
# Données embarquées par une dépendance dont la licence ne couvre que le code :
# leur attribution est due quand même.
DATA_ATTRIBUTIONS = (
    "pypinyin : ses dictionnaires (pinyin_dict.json, phrases_dict.json) dérivent\n"
    "de CC-CEDICT (MDBG, CC BY-SA 4.0, https://cc-cedict.org/), de la base Unihan\n"
    "(Unicode, Inc., licence Unicode) et de zdic.net, via pinyin-data et\n"
    "phrase-pinyin-data (mozillazg, MIT).\n"
)
# Licences « faibles » admises, mais qui doivent être nommées dans le texte.
WEAK_COPYLEFT = re.compile(r"\bMPL\b|Mozilla Public License", re.I)


def _python_roots() -> list[str]:
    names = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        if requirement.name.lower() not in TEST_ONLY:
            names.append(requirement.name)
    return names


def _python_closure() -> list[metadata.Distribution]:
    seen: dict[str, metadata.Distribution] = {}
    stack = _python_roots()
    while stack:
        name = stack.pop()
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # dépendance d'une autre plateforme
        seen[key] = dist
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                stack.append(requirement.name)
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def _python_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers)
    declared = (meta.get("License") or "").strip().splitlines()
    return declared[0] if declared else "?"


def _python_texts(dist: metadata.Distribution) -> list[tuple[str, str]]:
    texts = []
    for path in dist.files or []:
        posix = path.as_posix()
        # PEP 639 range tout sous `.dist-info/licenses/` — pypdfium2 y met les
        # mentions de FreeType, ICU, libjpeg-turbo… sous leur propre nom.
        if ".dist-info/" in posix and ("/licenses/" in posix or LICENSE_FILE.search(path.name)):
            try:
                texts.append((str(path), Path(path.locate()).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return texts


def _interpreter_license() -> tuple[str, str] | None:
    """La licence de CPython, qui liste aussi ce qu'il embarque (OpenSSL,
    libffi, expat, zlib, mpdecimal…) : l'interpréteur est dans le binaire."""
    base = Path(sys.base_prefix)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for candidate in (base / "lib" / version / "LICENSE.txt", base / "LICENSE.txt", base / "LICENSE"):
        if candidate.is_file():
            return str(candidate.name), candidate.read_text(encoding="utf-8", errors="replace")
    return None


def _npm_packages() -> list[dict]:
    """Paquets du bundle frontend : ceux du lockfile qui ne sont pas de développement."""
    lockfile = ROOT / "frontend" / "package-lock.json"
    packages = json.loads(lockfile.read_text(encoding="utf-8")).get("packages", {})
    found = []
    for key, meta in sorted(packages.items()):
        if not key or meta.get("dev") or meta.get("devOptional"):
            continue
        folder = ROOT / "frontend" / key
        if not folder.is_dir():
            if meta.get("optional"):
                continue  # binaire d'une autre plateforme
            raise SystemExit(f"{key} absent : lancer `npm ci` dans frontend/ avant ce script")
        texts = []
        for path in sorted(folder.iterdir()):
            if path.is_file() and LICENSE_FILE.search(path.name):
                texts.append((path.name, path.read_text(encoding="utf-8", errors="replace")))
        license_ = meta.get("license") or "?"
        found.append({
            "name": key.split("node_modules/")[-1],
            "version": meta.get("version", "?"),
            "license": license_ if isinstance(license_, str) else json.dumps(license_),
            "texts": texts,
        })
    return found


def _section(title: str, version: str, license_: str, texts: list[tuple[str, str]]) -> str:
    lines = ["=" * 78, f"{title} {version}", f"Licence : {license_}", "=" * 78]
    if not texts:
        lines.append("(Aucun fichier de licence fourni par le paquet : licence déclarée ci-dessus.)")
    for name, text in texts:
        lines += [f"--- {name}", text.rstrip(), ""]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="échoue sur une licence non admise")
    args = parser.parse_args()

    sections = [
        "Meta-Capp — mentions des composants tiers\n"
        "Meta-Capp est distribué sous licence MIT (LICENSE). Les composants ci-dessous\n"
        "sont embarqués dans le binaire et restent sous leur propre licence.\n"
        "Le code source des composants sous MPL-2.0 (certifi) est publié par leurs\n"
        "auteurs sur PyPI, à la version indiquée.\n\n" + DATA_ATTRIBUTIONS
    ]
    problems: list[str] = []
    weak: list[str] = []

    def review(origin: str, name: str, version: str, license_: str) -> None:
        if license_ == "?" or FORBIDDEN.search(license_):
            problems.append(f"{origin} {name} {version} : licence « {license_} »")
        elif WEAK_COPYLEFT.search(license_):
            weak.append(name)

    interpreter = _interpreter_license()
    if interpreter is None:
        problems.append("Python : fichier LICENSE de l'interpréteur introuvable")
    else:
        sections.append(_section("Python (CPython)", sys.version.split()[0], "PSF-2.0", [interpreter]))

    for dist in _python_closure():
        name, license_ = dist.metadata["Name"], _python_license(dist)
        review("PyPI", name, dist.version, license_)
        sections.append(_section(f"{name} (PyPI)", dist.version, license_, _python_texts(dist)))

    for package in _npm_packages():
        review("npm", package["name"], package["version"], package["license"])
        sections.append(_section(f"{package['name']} (npm)", package["version"], package["license"], package["texts"]))

    OUTPUT.write_text("\n".join(sections), encoding="utf-8")
    print(f"{OUTPUT.name} : {len(sections) - 1} composants", file=sys.stderr)
    if weak:
        print("Copyleft faible (texte inclus, source publique) : " + ", ".join(weak), file=sys.stderr)
    for problem in problems:
        print(f"LICENCE À EXAMINER — {problem}", file=sys.stderr)
    return 1 if args.check and problems else 0


if __name__ == "__main__":
    sys.exit(main())
