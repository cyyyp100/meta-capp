#!/usr/bin/env bash
# scripts/build_app.sh — Reconstruit Meta-Capp.app et l'installe dans /Applications.
#
# À relancer après chaque changement de code (Python ou frontend) : le bundle
# est un instantané figé, il ne suit pas le dépôt.
#
#   ./scripts/build_app.sh              # build + installe dans /Applications
#   ./scripts/build_app.sh --no-install # build seul (résultat dans dist_app/)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Build du frontend"
(cd frontend && npm run build)

echo "==> Gel PyInstaller"
pyinstaller desktop/metacapp.spec --noconfirm --distpath dist_app --workpath build_app

if [[ "${1:-}" == "--no-install" ]]; then
  echo "==> Terminé : dist_app/Meta-Capp.app"
  exit 0
fi

echo "==> Installation dans /Applications"
# L'app doit être fermée : macOS refuse d'écraser un bundle en cours d'exécution.
pkill -f "/Applications/Meta-Capp.app/Contents/MacOS/Meta-Capp" 2>/dev/null || true
rm -rf /Applications/Meta-Capp.app
cp -R dist_app/Meta-Capp.app /Applications/
xattr -d -r com.apple.quarantine /Applications/Meta-Capp.app 2>/dev/null || true

echo "==> Terminé : /Applications/Meta-Capp.app"
