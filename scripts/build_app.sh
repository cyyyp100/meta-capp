#!/usr/bin/env bash
# scripts/build_app.sh — Reconstruit Meta-Capp.app et l'installe.
#
# À relancer après chaque changement de code (Python ou frontend) : le bundle
# est un instantané figé, il ne suit pas le dépôt.
#
#   ./scripts/build_app.sh              # build + installe dans /Applications
#   ./scripts/build_app.sh --desktop    # build + pose l'app sur le Bureau
#   ./scripts/build_app.sh --no-install # build seul (résultat dans dist_app/)
#
# À lancer depuis l'env conda `nwol` (`conda activate nwol`) : c'est lui qui
# porte pyinstaller et les dépendances gelées. Mode d'emploi détaillé :
# architecture/15-installer-sur-le-bureau.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

case "${1:-}" in
  "")            DEST="/Applications" ;;
  --desktop)     DEST="$HOME/Desktop" ;;
  --no-install)  DEST="" ;;
  *) echo "usage: $0 [--desktop|--no-install]" >&2; exit 2 ;;
esac

echo "==> Build du frontend"
(cd frontend && npm run build)

echo "==> Gel PyInstaller"
pyinstaller desktop/metacapp.spec --noconfirm --distpath dist_app --workpath build_app

echo "==> Smoke test du binaire (serveur seul + /api/health)"
# Un bundle qui compile mais ne démarre pas (import manquant, lib native
# absente) se voit ici, pas au premier double-clic.
"dist_app/Meta-Capp.app/Contents/MacOS/Meta-Capp" --server-only &
SMOKE_PID=$!
SMOKE_OK=0
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8756/api/health > /dev/null 2>&1; then SMOKE_OK=1; break; fi
  sleep 2
done
kill "$SMOKE_PID" 2>/dev/null || true
if [[ "$SMOKE_OK" != 1 ]]; then
  echo "!! Smoke test ÉCHOUÉ : /api/health injoignable — bundle non installé" >&2
  exit 1
fi

if [[ -z "$DEST" ]]; then
  echo "==> Terminé : dist_app/Meta-Capp.app"
  exit 0
fi

echo "==> Installation dans $DEST"
# L'app doit être fermée : macOS refuse d'écraser un bundle en cours d'exécution.
pkill -f "$DEST/Meta-Capp.app/Contents/MacOS/Meta-Capp" 2>/dev/null || true
rm -rf "$DEST/Meta-Capp.app"
cp -R dist_app/Meta-Capp.app "$DEST/"
# Le bundle n'est pas signé : sans ça, Gatekeeper le bloque au premier lancement.
xattr -d -r com.apple.quarantine "$DEST/Meta-Capp.app" 2>/dev/null || true

echo "==> Terminé : $DEST/Meta-Capp.app"
