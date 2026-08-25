// features/library/dnd.ts — Protocole de glisser-déposer de la bibliothèque.
//
// DEUX types MIME distincts, et c'est essentiel : pendant `dragover`, le
// navigateur interdit `dataTransfer.getData()` (mode protégé) — seule la liste
// `dataTransfer.types` est lisible. C'est donc le TYPE, et lui seul, qui permet
// à une cible de décider si elle accepte le survol. Un type unique portant un
// payload JSON rendrait cette décision impossible, et la cible ne pourrait
// afficher « interdit » qu'APRÈS le lâcher — trop tard.
//
// L'id du dossier tiré est en plus miroité dans le store (`useLibraryUi`), parce
// que le garde-fou anti-cycle a besoin de l'id, pas seulement de la nature.

export const DOC_MIME = "application/x-metacapp-document";
export const FOLDER_MIME = "application/x-metacapp-folder";

export function hasType(dt: DataTransfer, mime: string): boolean {
  return Array.from(dt.types).includes(mime);
}

export function readId(dt: DataTransfer, mime: string): number | null {
  const raw = dt.getData(mime);
  if (!raw) return null;
  const id = Number(raw);
  return Number.isFinite(id) ? id : null;
}
