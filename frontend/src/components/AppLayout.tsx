import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useLangStore, useT } from "../i18n";
import { IconChart, IconGlobe, IconHelpCircle, IconHome, IconLayers, IconMessage } from "./icons";

const NAV = [
  { to: "/", labelKey: "nav.home", Icon: IconHome, end: true },
  { to: "/stats", labelKey: "nav.profile", Icon: IconChart, end: false },
  { to: "/flashcards", labelKey: "nav.flashcards", Icon: IconLayers, end: false },
  { to: "/quiz", labelKey: "nav.quiz", Icon: IconHelpCircle, end: false },
  { to: "/lang", labelKey: "nav.lang", Icon: IconGlobe, end: false },
  { to: "/brainstorming", labelKey: "nav.brainstorming", Icon: IconMessage, end: false },
];

function initialTheme(): "light" | "dark" {
  const saved = localStorage.getItem("metacapp-theme");
  if (saved === "light" || saved === "dark") return saved;
  // Démarrage en thème clair par défaut (on n'hérite plus du thème système sombre).
  return "light";
}

export function AppLayout() {
  const [theme, setTheme] = useState<"light" | "dark">(initialTheme);
  const t = useT();
  const { lang, setLang } = useLangStore();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("metacapp-theme", theme);
  }, [theme]);

  return (
    <div style={{ display: "flex", height: "100%" }}>
      <aside
        style={{
          width: 232,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          background: "var(--surface)",
          borderRight: "1px solid var(--border)",
          padding: "var(--space-lg) var(--space-md)",
        }}
      >
        <div style={{ fontFamily: "var(--font-title)", fontSize: 22, fontWeight: 700, padding: "0 10px 18px" }}>
          Meta-Capp
        </div>
        <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              style={({ isActive }) => ({
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 12px",
                borderRadius: "var(--radius-sm)",
                textDecoration: "none",
                fontWeight: 600,
                fontSize: 14,
                color: isActive ? "var(--accent-hover)" : "var(--text-soft)",
                background: isActive ? "var(--accent-soft)" : "transparent",
              })}
            >
              <item.Icon />
              {t(item.labelKey)}
            </NavLink>
          ))}
        </nav>
        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 6 }}>
            {(["fr", "en"] as const).map((l) => (
              <button
                key={l}
                onClick={() => setLang(l)}
                style={{
                  flex: 1,
                  border: "1px solid var(--border)",
                  background: lang === l ? "var(--accent-soft)" : "var(--surface-soft)",
                  color: lang === l ? "var(--accent-hover)" : "var(--muted)",
                  borderRadius: "var(--radius-sm)",
                  padding: "6px 0",
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                {l.toUpperCase()}
              </button>
            ))}
          </div>
          <button
            onClick={() => setTheme((cur) => (cur === "light" ? "dark" : "light"))}
            style={{
              width: "100%",
              border: "1px solid var(--border)",
              background: "var(--surface-soft)",
              color: "var(--text)",
              borderRadius: "var(--radius-sm)",
              padding: "8px 12px",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            {theme === "light" ? t("common.dark") : t("common.light")}
          </button>
        </div>
      </aside>
      <main style={{ flex: 1, overflow: "auto" }}>
        <Outlet />
      </main>
    </div>
  );
}
