import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, pageImageUrl } from "../api/client";
import { pickFilePath } from "../api/platform";
import type { DocumentSummary } from "../api/types";
import { useT } from "../i18n";

export function Home() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const t = useT();
  const [importing, setImporting] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["library", "recent"],
    queryFn: () => api.recentDocuments(12),
  });

  const { data: streak } = useQuery({ queryKey: ["streak"], queryFn: api.streak });

  async function handleImport() {
    if (importing) return;
    const path = await pickFilePath();
    if (!path) return;
    setImporting(true);
    try {
      const doc = await api.importPdf(path);
      await queryClient.invalidateQueries({ queryKey: ["library", "recent"] });
      navigate(`/reader/${doc.id}`);
    } catch (e) {
      alert("Import impossible : " + String((e as Error).message));
    } finally {
      setImporting(false);
    }
  }

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "var(--space-xl)" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 style={{ fontFamily: "var(--font-title)", fontSize: 32, margin: "0 0 4px" }}>{t("home.title")}</h1>
            {streak && streak.streak > 0 && (
              <span
                title="Jours consécutifs"
                style={{
                  background: "var(--warning-soft)",
                  color: "var(--warning)",
                  fontWeight: 700,
                  fontSize: 13,
                  padding: "4px 10px",
                  borderRadius: 999,
                }}
              >
                🔥 {streak.streak}
              </span>
            )}
          </div>
          <p style={{ color: "var(--muted)", marginTop: 0 }}>{t("home.subtitle")}</p>
        </div>
        <button
          onClick={handleImport}
          disabled={importing}
          style={{
            border: "none",
            background: "var(--accent)",
            color: "#fff",
            borderRadius: "var(--radius-sm)",
            padding: "10px 18px",
            fontWeight: 600,
            cursor: importing ? "default" : "pointer",
            whiteSpace: "nowrap",
            boxShadow: "var(--shadow-sm)",
          }}
        >
          {importing ? t("home.importing") : t("home.import")}
        </button>
      </div>

      {isLoading && <p style={{ color: "var(--muted)" }}>{t("common.loading")}</p>}
      {isError && <p style={{ color: "var(--danger)" }}>{t("home.error")}</p>}

      {data && data.length === 0 && (
        <div
          style={{
            marginTop: 40,
            padding: 48,
            textAlign: "center",
            border: "1px dashed var(--border-strong)",
            borderRadius: "var(--radius-lg)",
            color: "var(--muted)",
          }}
        >
          <div style={{ fontSize: 40, marginBottom: 12 }}>📄</div>
          {t("home.empty")}
        </div>
      )}

      {data && data.length > 0 && (
        <div
          style={{
            marginTop: "var(--space-lg)",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: "var(--space-lg)",
          }}
        >
          {data.map((doc) => (
            <DocumentCard key={doc.id} doc={doc} />
          ))}
        </div>
      )}

    </div>
  );
}

function DocumentCard({ doc }: { doc: DocumentSummary }) {
  const navigate = useNavigate();
  const t = useT();
  const progress = doc.page_count > 0 ? Math.round((doc.last_page / doc.page_count) * 100) : 0;
  return (
    <div
      onClick={() => navigate(`/reader/${doc.id}`)}
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-sm)",
        overflow: "hidden",
        cursor: "pointer",
        transition: "box-shadow var(--anim-normal) var(--ease), transform var(--anim-normal) var(--ease)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = "var(--shadow-md)";
        e.currentTarget.style.transform = "translateY(-2px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = "var(--shadow-sm)";
        e.currentTarget.style.transform = "none";
      }}
    >
      <div style={{ aspectRatio: "3 / 4", background: "var(--bg-alt)", overflow: "hidden", position: "relative" }}>
        {doc.extraction_engine === "code" ? (
          // Fichier de code : pas d'image de page → vignette dédiée.
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              background: "var(--surface-soft)",
              color: "var(--muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            <span style={{ fontSize: 34 }}>{"</>"}</span>
            <span style={{ fontSize: 11, padding: "0 10px", textAlign: "center", wordBreak: "break-all" }}>
              {doc.title}
            </span>
          </div>
        ) : (
          <img
            src={pageImageUrl(doc.id, 1, 0.5)}
            alt={doc.title}
            loading="lazy"
            style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          />
        )}
      </div>
      <div style={{ padding: "var(--space-md)" }}>
        <div
          style={{
            fontWeight: 600,
            fontSize: 13,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
          title={doc.title}
        >
          {doc.title}
        </div>
        <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 4 }}>
          {t("home.pages", { n: doc.page_count })}{doc.subject ? ` · ${doc.subject}` : ""}
        </div>
        <div style={{ height: 6, borderRadius: 999, background: "var(--border)", marginTop: 10, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${progress}%`, background: "var(--accent)", borderRadius: 999 }} />
        </div>
      </div>
    </div>
  );
}
