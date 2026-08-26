// features/session/duration.ts — Durée d'une séance, en m:ss.
//
// Chaque sas de sortie (lecture, langue, quiz) en avait sa propre copie : trois
// implémentations du même formatage, pour la même tuile « Durée ».

/** `125` → `"2:05"`. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}
