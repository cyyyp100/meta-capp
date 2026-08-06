# metacapp.spec — Recette PyInstaller pour produire un exécutable desktop.
#
# Build :  conda activate nwol && cd frontend && npm run build && cd ..
#          pyinstaller desktop/metacapp.spec --noconfirm
#
# Recette de départ : les dépendances binaires délicates (PyMuPDF/fitz,
# pywebview, uvicorn) sont collectées via collect_all ; itérer si un import
# manque au premier lancement du binaire.
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH = dossier de la spec (.../desktop) -> ROOT = racine du dépôt.
ROOT = os.path.dirname(os.path.abspath(SPECPATH))

datas = []
binaries = []
hiddenimports = []

for pkg in ("uvicorn", "fastapi", "starlette", "fitz", "webview", "PIL"):
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
        "tkinter",
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
