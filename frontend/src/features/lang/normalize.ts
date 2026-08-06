// features/lang/normalize.ts — Normalisation des réponses pour la correction
// côté client (cloze free / transform). Règle : exact normalisé d'abord (gratuit),
// le LLM n'intervient qu'en SECOND recours pour les saisies libres non exactes.

export interface NormalizeOpts {
  /** Tolérer les accents (mode débutant). Par défaut les accents comptent. */
  foldAccents?: boolean;
}

/** minuscule · espaces compactés · ponctuation de bord retirée · accents optionnels. */
export function normalizeAnswer(s: string, opts: NormalizeOpts = {}): string {
  let out = (s ?? "").trim().toLowerCase();
  out = out.replace(/\s+/g, " ");
  // Ponctuation de bord (début/fin), on garde la ponctuation interne (apostrophes…).
  out = out.replace(/^[\s.,;:!?¿¡«»"'`()[\]{}…-]+/, "").replace(/[\s.,;:!?«»"'`()[\]{}…-]+$/, "");
  if (opts.foldAccents) {
    out = out.normalize("NFD").replace(/[̀-ͯ]/g, "");
  }
  return out;
}

/** Égalité normalisée (accents conservés par défaut — ils comptent en langue). */
export function answersMatch(a: string, b: string, opts: NormalizeOpts = {}): boolean {
  return normalizeAnswer(a, opts) === normalizeAnswer(b, opts);
}
