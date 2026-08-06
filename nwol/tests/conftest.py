import sys
from pathlib import Path

# Le code applicatif utilise des imports absolus (db, services, config, ui...).
# On ajoute le dossier `nwol/` au path comme le fait main.py.
NWOL_DIR = Path(__file__).resolve().parents[1]
if str(NWOL_DIR) not in sys.path:
    sys.path.insert(0, str(NWOL_DIR))
