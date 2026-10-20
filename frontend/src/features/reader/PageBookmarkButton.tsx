// features/reader/PageBookmarkButton.tsx — Le marque-page d'une page du lecteur.
//
// Un seul marque-page par document, qui se déplace : le poser sur une page le
// retire de l'autre, et le document rouvrira là. En haut à droite de chaque
// page, sur une pastille : les pages restent claires dans les deux thèmes, la
// pastille suit le thème et reste lisible sur le blanc. En z 8, au-dessus du
// cache du rappel libre (z 6), dans un coin que ce cache ne couvre pas. Discret
// tant que la page n'est pas marquée ; plein, et à l'accent, quand elle l'est.
import { Bookmark } from "lucide-react";

import { useT } from "../../i18n";

interface Props {
  page: number;
  active: boolean;
  onToggle: (page: number) => void;
}

export function PageBookmarkButton({ page, active, onToggle }: Props) {
  const t = useT();
  const label = active ? t("reader.bookmark_remove") : t("reader.bookmark_set", { page });
  return (
    <button
      type="button"
      data-bookmark-button=""
      aria-pressed={active}
      aria-label={label}
      title={label}
      onClick={() => onToggle(page)}
      className={active ? undefined : "opacity-60 transition-opacity hover:opacity-100 focus-visible:opacity-100"}
      style={{
        position: "absolute",
        top: 8,
        right: 10,
        zIndex: 8,
        display: "grid",
        placeItems: "center",
        width: 30,
        height: 30,
        padding: 0,
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-sm)",
        background: "color-mix(in srgb, var(--surface) 88%, transparent)",
        boxShadow: "var(--shadow-sm)",
        color: active ? "var(--accent)" : "var(--text-soft)",
        cursor: "pointer",
      }}
    >
      <Bookmark size={16} strokeWidth={2} fill={active ? "currentColor" : "none"} aria-hidden />
    </button>
  );
}
