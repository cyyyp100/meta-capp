// features/library/SearchBox.tsx — Recherche de la bibliothèque (haut à droite).
import { IconSearch } from "../../components/icons";
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
    <div style={wrapper}>
      <span style={{ display: "flex", color: "var(--muted)" }}>
        <IconSearch size={15} />
      </span>
      <input
        type="search"
        value={value}
        placeholder={t("library.search_placeholder")}
        aria-label={t("library.search_placeholder")}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onChange("");
        }}
        style={input}
      />
      {value && (
        <button
          type="button"
          title={t("library.clear_search")}
          aria-label={t("library.clear_search")}
          onClick={() => onChange("")}
          style={clearButton}
        >
          ✕
        </button>
      )}
    </div>
  );
}

const wrapper: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 7,
  width: 260,
  padding: "8px 11px",
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
};

const input: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  border: "none",
  outline: "none",
  background: "transparent",
  color: "var(--text)",
  font: "inherit",
  fontSize: 13,
};

const clearButton: React.CSSProperties = {
  border: "none",
  background: "transparent",
  color: "var(--muted)",
  cursor: "pointer",
  fontSize: 12,
  lineHeight: 1,
  padding: 2,
};
