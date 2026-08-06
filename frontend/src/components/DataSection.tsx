// DataSection — Sauvegarde/restauration des données utilisateur (plan P4.3) :
// export de la base, restauration depuis une sauvegarde, export des logs
// (partage volontaire pour diagnostic — rien ne part automatiquement).
import { useRef, useState } from "react";

import { api } from "../api/client";
import { useT } from "../i18n";
import { Card } from "./Card";

const buttonStyle: React.CSSProperties = {
  padding: "8px 14px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--surface)",
  cursor: "pointer",
  fontSize: 13,
};

export function DataSection() {
  const t = useT();
  const fileInput = useRef<HTMLInputElement>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function onImportFile(file: File) {
    setMessage("");
    setError("");
    if (!window.confirm(t("data.import_confirm"))) return;
    try {
      await api.importDb(await file.arrayBuffer());
      setMessage(t("data.import_done"));
    } catch {
      setError(t("data.import_error"));
    }
  }

  async function onPurge() {
    setMessage("");
    setError("");
    // Double garde : le mot exact est aussi exigé côté serveur.
    const typed = window.prompt(t("data.purge_prompt"));
    if (typed !== "EFFACER") return;
    try {
      await api.purgeData();
      setMessage(t("data.purge_done"));
    } catch {
      setError(t("data.purge_error"));
    }
  }

  return (
    <Card soft>
      <h2 style={{ fontSize: 14, fontWeight: 700, margin: "0 0 6px" }}>{t("data.title")}</h2>
      <p style={{ color: "var(--muted)", fontSize: 13, margin: "0 0 12px" }}>{t("data.subtitle")}</p>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {/* <a> plutôt que fetch : le cookie de session part avec, le navigateur télécharge. */}
        <a href="/api/data/export" download style={{ ...buttonStyle, textDecoration: "none", color: "inherit" }}>
          {t("data.export")}
        </a>
        <button style={buttonStyle} onClick={() => fileInput.current?.click()}>
          {t("data.import")}
        </button>
        <a href="/api/data/export-logs" download style={{ ...buttonStyle, textDecoration: "none", color: "inherit" }}>
          {t("data.export_logs")}
        </a>
        <button style={{ ...buttonStyle, color: "#c0392b", borderColor: "#c0392b55" }} onClick={() => void onPurge()}>
          {t("data.purge")}
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".db"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onImportFile(f);
            e.target.value = "";
          }}
        />
      </div>
      {message && <p style={{ color: "var(--accent)", fontSize: 13, margin: "10px 0 0" }}>{message}</p>}
      {error && <p style={{ color: "#c0392b", fontSize: 13, margin: "10px 0 0" }}>{error}</p>}
    </Card>
  );
}
