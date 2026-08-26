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
        color: "#fff",
        background: VERDICT_COLOR[verdict] ?? "var(--muted)",
      }}
    >
      {t(`verdict.${verdict}`)}
    </span>
  );
}
