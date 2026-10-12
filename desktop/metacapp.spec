# metacapp.spec — Recette PyInstaller pour produire un exécutable desktop.
#
# Build :  conda activate metacapp && cd frontend && npm run build && cd ..
#          pyinstaller desktop/metacapp.spec --noconfirm
#
# Recette de départ : les dépendances binaires délicates (pypdfium2, pywebview,
# uvicorn) sont collectées via collect_all ; itérer si un import manque au
# premier lancement du binaire.
#
# ⚠ `pypdfium2_raw` est OBLIGATOIRE dans la liste. C'est un module livré DANS la
# wheel `pypdfium2`, mais c'est lui qui porte la bibliothèque native
# `libpdfium.{dylib,so,dll}` — et `collect_all("pypdfium2")` ne va pas la
# chercher (0 binaire collecté). Le nommer séparément est le seul moyen ; sans
# lui le binaire s'ouvre puis échoue à l'ouverture du premier PDF.
#
# Signature macOS : `METACAPP_CODESIGN_IDENTITY` (« Developer ID Application:
# … ») fait signer par PyInstaller CHAQUE binaire collecté, puis le bundle, avec
# runtime durci et horodatage — les deux conditions de la notarisation. Sans
# elle, signature ad hoc (l'app ne vaut que pour la machine qui la construit).
import os
import re
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH = dossier de la spec (.../desktop) -> ROOT = racine du dépôt.
ROOT = os.path.dirname(os.path.abspath(SPECPATH))

# La version annoncée par le binaire est celle du serveur (`server/config.py`),
# que la release vérifie contre le tag : une seule source.
with open(os.path.join(ROOT, "nwol", "server", "config.py"), encoding="utf-8") as _config:
    APP_VERSION = re.search(r'^APP_VERSION = "([^"]+)"', _config.read(), re.M).group(1)
COPYRIGHT = "© 2026 Cyprien Vial — MIT License"

CODESIGN_IDENTITY = os.environ.get("METACAPP_CODESIGN_IDENTITY") or None
ENTITLEMENTS = os.path.join(ROOT, "desktop", "entitlements.plist") if CODESIGN_IDENTITY else None


def _icon(extension: str) -> str | None:
    """Icône de l'application si elle existe (`desktop/icons/meta-capp.icns|.ico`) ;
    sans elle, PyInstaller pose la sienne."""
    path = os.path.join(ROOT, "desktop", "icons", f"meta-capp.{extension}")
    return path if os.path.isfile(path) else None


datas = []
binaries = []
hiddenimports = []

# `certifi` : son cacert.pem est le magasin TLS de la vérification de mise à
# jour dans le binaire (cf. services/updates.py:_tls_context).
for pkg in ("uvicorn", "fastapi", "starlette", "pypdfium2", "pypdfium2_raw", "PIL", "webview", "certifi"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

hiddenimports += collect_submodules("uvicorn")

# Données applicatives embarquées (chemins absolus). Rien d'autre : les caches
# d'exécution (`nwol/assets/`, pages rendues des PDF de qui construit) ne sont
# jamais lus depuis le bundle — l'app gelée les tient dans le dossier données
# de l'OS (settings.ASSETS_DIR) — et n'ont rien à faire dans un binaire.
datas += [
    (os.path.join(ROOT, "frontend", "dist"), "frontend/dist"),
    # nwol/resources/ EST versionné (le PDF de démonstration de la visite
    # guidée) : il est présent dans tout checkout, donc embarqué sans condition.
    # Le service le lit sous sys._MEIPASS (services/onboarding.py:RESOURCES_DIR).
    (os.path.join(ROOT, "nwol", "resources"), "resources"),
    # Données statiques du module langues (programmes, registres d'écriture,
    # test de niveau, phrases de survie) : versionnées, relues, réinjectées en
    # base au démarrage (services/lang_static.py:LANG_DATA_DIR).
    (os.path.join(ROOT, "nwol", "data", "lang"), "data/lang"),
]
# Mentions des licences tierces (scripts/third_party_notices.py) : générées par
# la release, embarquées quand elles existent.
_notices = os.path.join(ROOT, "THIRD_PARTY_NOTICES.txt")
if os.path.isfile(_notices):
    datas.append((_notices, "."))

a = Analysis(
    [os.path.join(ROOT, "desktop", "pywebview_main.py")],
    pathex=[os.path.join(ROOT, "nwol")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # L'UI Tkinter a été retirée du produit : ni Tk, ni matplotlib (qui ne
        # servait qu'au rendu LaTeX de l'ancien lecteur).
        # ⚠ Ne PAS exclure "PIL" : pypdfium2 l'importe dans un try/except
        # (`PIL = None` si absent) et `PdfBitmap.to_pil()` — utilisé par
        # pdf_viewer/page_renderer.py pour encoder chaque page en PNG — plante
        # alors à la première page affichée. L'exclusion empêche aussi la
        # collecte de l'extension C `PIL._imaging` ; les .py seuls ne suffisent
        # pas. Le symptôme : le binaire démarre, la bibliothèque s'affiche, mais
        # chaque page du lecteur est une image cassée.
        "tkinter",
        "matplotlib",
        "webview.platforms.android",
        "webview.platforms.gtk",
        "webview.platforms.qt",
        # L'outil en ligne de commande de pypdfium2 (jamais appelé) importe
        # OpenCV, qui tire numpy, OpenBLAS et FFmpeg — x264/x265 sous GPL dans
        # l'env conda. numpy n'est qu'une option de pypdfium2 (`to_numpy`).
        "pypdfium2._cli",
        "cv2",
        "numpy",
        # Deps fantômes de l'env conda (S5) : jamais importées par l'app mais
        # aspirées par PyInstaller (torch ~2 Go). Ne pas retirer ces exclusions
        # sans refaire le smoke test du binaire.
        "torch",
        "torchvision",
        "torchaudio",
        "scipy",
        "pandas",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Ressource de version Windows : éditeur, produit et version dans les
# propriétés du fichier — ce que SmartScreen et les antivirus regardent aussi.
_windows_version = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    _numbers = tuple(int(part) for part in APP_VERSION.split(".")) + (0,)
    _windows_version = VSVersionInfo(
        ffi=FixedFileInfo(filevers=_numbers, prodvers=_numbers),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "Cyprien Vial"),
                StringStruct("FileDescription", "Meta-Capp"),
                StringStruct("FileVersion", APP_VERSION),
                StringStruct("InternalName", "Meta-Capp"),
                StringStruct("LegalCopyright", COPYRIGHT),
                StringStruct("OriginalFilename", "Meta-Capp.exe"),
                StringStruct("ProductName", "Meta-Capp"),
                StringStruct("ProductVersion", APP_VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Meta-Capp",
    console=False,
    icon=_icon("ico") if sys.platform == "win32" else None,
    version=_windows_version,
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=ENTITLEMENTS,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Meta-Capp")
app = BUNDLE(
    coll,
    name="Meta-Capp.app",
    icon=_icon("icns"),
    bundle_identifier="com.metacapp.app",
    version=APP_VERSION,
    info_plist={
        "CFBundleVersion": APP_VERSION,
        "NSHumanReadableCopyright": COPYRIGHT,
        "LSApplicationCategoryType": "public.app-category.education",
        "NSHighResolutionCapable": True,
    },
)
