// platform.ts — Seule abstraction qui touche l'OS (sélecteur de fichier).
// En coque pywebview : bridge natif window.pywebview.api.pick_pdf() -> chemin
// (accepte PDF ET fichiers de code) ; le backend lit le fichier sur place.
// Dans un navigateur (mode sans fenêtre native : Linux sans GTK ni Qt, Windows
// sans WebView2, `--browser`, ou `npm run dev`) : aucun chemin n'est jamais
// disponible -> <input type="file">, et le CONTENU est envoyé au backend, qui
// le copie dans son dossier de données (`POST /api/library/upload`).

export function isDesktopShell(): boolean {
  return Boolean((window as any).pywebview || (window as any).__TAURI__);
}

/** Ce que l'utilisateur a choisi : un chemin (coque native) ou un fichier (navigateur). */
export type PickedDocument = { path: string } | { file: File };

export async function pickDocument(): Promise<PickedDocument | null> {
  const api = (window as any).pywebview?.api;
  if (api?.pick_pdf) {
    const path = await api.pick_pdf();
    return path ? { path } : null;
  }
  const file = await pickBrowserFile();
  return file ? { file } : null;
}

// Pas de filtre `accept` : la liste des extensions de code vit côté serveur
// (services/code_reader), qui refuse de toute façon ce qu'il ne sait pas lire.
function pickBrowserFile(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.style.display = "none";
    const done = (file: File | null) => {
      input.remove();
      resolve(file);
    };
    input.addEventListener("change", () => done(input.files?.[0] ?? null), { once: true });
    // `cancel` : Chrome 113+, Firefox 91+, Safari 16.4+. Sans lui, une
    // annulation laisse simplement la promesse en suspens — rien n'est bloqué,
    // l'appelant ne passe en « import en cours » qu'après un choix.
    input.addEventListener("cancel", () => done(null), { once: true });
    document.body.appendChild(input);
    input.click();
  });
}
