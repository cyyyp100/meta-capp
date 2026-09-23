# metacapp.spec — Recette PyInstaller pour produire un exécutable desktop.
#
# Build :  conda activate nwol && cd frontend && npm run build && cd ..
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
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH = dossier de la spec (.../desktop) -> ROOT = racine du dépôt.
ROOT = os.path.dirname(os.path.abspath(SPECPATH))

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

# Données applicatives embarquées (chemins absolus).
datas += [
    (os.path.join(ROOT, "frontend", "dist"), "frontend/dist"),
    # nwol/resources/ EST versionné (le PDF de démonstration de la visite
    # guidée) : contrairement à nwol/assets/ juste en dessous, il est présent
    # dans tout checkout, donc embarqué sans condition. Le service le lit sous
    # sys._MEIPASS (services/onboarding.py:RESOURCES_DIR).
    (os.path.join(ROOT, "nwol", "resources"), "resources"),
]
# nwol/assets/ n'est PAS versionné (caches runtime, gitignoré) : absent des
# checkouts CI. L'app gelée lit ses assets depuis le dossier données OS
# (settings.ASSETS_DIR = _DATA_DIR/"assets"), jamais depuis le bundle — on ne
# l'embarque donc que s'il existe localement, sinon le build casse en CI.
_assets_dir = os.path.join(ROOT, "nwol", "assets")
if os.path.isdir(_assets_dir):
    datas.append((_assets_dir, "assets"))

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

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Meta-Capp", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Meta-Capp")
app = BUNDLE(coll, name="Meta-Capp.app", bundle_identifier="com.metacapp.app")
