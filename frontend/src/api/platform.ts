// platform.ts — Seule abstraction qui touche l'OS (sélecteur de fichier).
// En coque pywebview : bridge natif window.pywebview.api.pick_pdf() -> chemin
// (accepte PDF ET fichiers de code). En dev (navigateur) : pas de chemin
// disponible -> on retombe sur un prompt.

export function isDesktopShell(): boolean {
  return Boolean((window as any).pywebview || (window as any).__TAURI__);
}

// Renvoie le CHEMIN absolu d'un fichier (PDF ou code) — le backend lit et
// valide le fichier côté serveur.
export async function pickFilePath(): Promise<string | null> {
  const api = (window as any).pywebview?.api;
  if (api?.pick_pdf) {
    const path = await api.pick_pdf();
    return path ?? null;
  }
  // Dev navigateur : on ne peut pas obtenir un chemin serveur depuis <input file>.
  // Pour itérer, on demande le chemin manuellement.
  const typed = window.prompt("Chemin absolu du fichier (PDF ou code) à importer :");
  return typed && typed.trim() ? typed.trim() : null;
}
