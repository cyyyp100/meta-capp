// features/library/SearchBox.tsx — Recherche de la bibliothèque (haut à droite).
import { Search, X } from "lucide-react";

import { useT } from "../../i18n";

export function SearchBox({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useT();
  return (
    // Le champ n'a pas de focus propre (l'`outline` est retiré pour que la
    // bordure du conteneur ne soit pas doublée) : `focus-within` reporte donc
    // l'anneau sur le conteneur. Sans cela, tabuler dans la recherche
    // n'affichait strictement rien.
    <div
      className="flex w-65 items-center gap-1.5 rounded-sm border border-border bg-surface px-2.5 py-2
                 transition-[border-color,box-shadow] duration-fast ease-brand
                 focus-within:border-brand focus-within:ring-[3px] focus-within:ring-ring/50
                 hover:border-border-strong"
    >
      <Search className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <input
        type="search"
        value={value}
        placeholder={t("library.search_placeholder")}
        aria-label={t("library.search_placeholder")}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onChange("");
        }}
        className="min-w-0 flex-1 border-none bg-transparent font-[inherit] text-[13px] text-foreground outline-none placeholder:text-muted-light"
      />
      {value && (
        <button
          type="button"
          title={t("library.clear_search")}
          aria-label={t("library.clear_search")}
          onClick={() => onChange("")}
          className="flex shrink-0 rounded-full p-0.5 text-muted-foreground
                     transition-colors duration-fast ease-brand
                     hover:bg-accent hover:text-accent-foreground
                     focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}
