// components/MathText.tsx — Un texte de carte ou de LLM, ses formules rendues.
//
// Les cartes portent du LaTeX (« Donne la définition de $u_n$ ») : le lecteur le
// rendait, mais aucun écran de carte — le sas d'entrée, la page Flashcards, le
// récap de la semaine ou la séance de langue montraient des `$` bruts.
//
// Sécurité : `renderMathToHtml` est la seule entrée de ce HTML (tout est échappé
// hors des formules, KaTeX sans `trust`) — c'est l'invariant S6, verrouillé par
// renderMath.test.ts.
import type { CSSProperties } from "react";

import { renderMathToHtml } from "../features/reader/renderMath";

export function MathText({
  text,
  dir,
  className,
  style,
}: {
  text: string;
  /** Sens d'écriture : « auto » pour une carte d'arabe ou d'hébreu. */
  dir?: "auto" | "ltr" | "rtl";
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <span
      dir={dir}
      className={className}
      style={style}
      dangerouslySetInnerHTML={{ __html: renderMathToHtml(text ?? "") }}
    />
  );
}
