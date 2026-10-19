// VerdictBadge.tsx — La pastille de verdict d'une réponse corrigée.
//
// Le lecteur et le quiz corrigent par le même chemin serveur : ils affichent
// donc le même verdict, avec les mêmes couleurs. Les deux écrans en tenaient
// chacun une copie — et la couleur du « partiel » avait déjà divergé.

import { useT } from "../../i18n";

/** Couleur de fond de la pastille, par verdict. Jamais deux fois ailleurs. */
export const VERDICT_COLOR: Record<string, string> = {
  correct: "var(--success)",
  partial: "var(--warning)",
  incorrect: "var(--danger)",
};

export function VerdictBadge({ verdict }: { verdict: string }) {
  const t = useT();
  if (!verdict) return null;
  return (
    <span
      style={{
        alignSelf: "flex-start",
        fontSize: 11,
        fontWeight: 700,
        padding: "3px 10px",
        borderRadius: 999,
        // Le fond est un remplissage de STATUT (succès / avertissement /
        // danger), pas l'accent : son encre est `--on-status`. Avec
        // `--on-accent`, le bleu nuit tombait à 2,67:1 sur le rouge.
        color: "var(--on-status)",
        background: VERDICT_COLOR[verdict] ?? "var(--muted)",
      }}
    >
      {t(`verdict.${verdict}`)}
    </span>
  );
}

/**
 * La pastille d'une question réflexive (métacognition, anticipation) : il n'y
 * a pas de mauvaise réponse, donc pas de couleur de statut — un succès vert
 * ou un partiel orange y jugeraient une réflexion qui ne se juge pas.
 */
export function ReflectionBadge() {
  const t = useT();
  return (
    <span
      style={{
        alignSelf: "flex-start",
        fontSize: 11,
        fontWeight: 700,
        padding: "3px 10px",
        borderRadius: 999,
        color: "var(--accent-ink)",
        background: "var(--accent-soft)",
        border: "1px solid var(--border)",
      }}
    >
      {t("verdict.reflection")}
    </span>
  );
}
