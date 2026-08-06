import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import type { SessionMetrics } from "../../api/types";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import { WhyButton } from "../science/WhyButton";

// Bilan de fin de session : analyse LLM + métriques + questions de réflexion métacognitive.
export function ExitSas({ metrics, onClose }: { metrics: SessionMetrics; onClose: () => void }) {
  const t = useT();
  const [responses, setResponses] = useState<string[]>(metrics.reflection_questions.map(() => ""));
  const [saving, setSaving] = useState(false);

  // Analyse LLM de la session (stats + jauges session + jauges profil), best-effort.
  const { data: analysis, isLoading: analysisLoading } = useQuery({
    queryKey: ["session-analysis", metrics.session_id],
    queryFn: () => api.sessionAnalysis(metrics.session_id),
    staleTime: Infinity,
  });

  async function finish() {
    setSaving(true);
    try {
      await api.finalizeSession(metrics.session_id, responses);
    } catch {
      /* on ferme quand même */
    }
    onClose();
  }

  return (
    <div style={overlay}>
      <div style={card}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 14 }}>
          <div>
            <h2 style={{ fontFamily: "var(--font-title)", fontSize: 26, margin: "0 0 4px" }}>{t("exit.title")}</h2>
            <p style={{ color: "var(--muted)", margin: 0 }}>{t("exit.subtitle")}</p>
          </div>
          <WhyButton whyKey="exit" />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, margin: "18px 0" }}>
          <Metric label={t("exit.duration")} value={formatDuration(metrics.duration_s)} />
          <Metric label={t("exit.pages")} value={String(metrics.pages_read)} />
          <Metric label={t("exit.questions")} value={String(metrics.questions_answered)} />
          <Metric label={t("exit.success")} value={`${metrics.success_rate}%`} />
        </div>

        {(analysisLoading || analysis?.analysis) && (
          <div style={{ background: "var(--accent-soft)", color: "var(--accent-hover)", borderRadius: "var(--radius-md)", padding: "14px 16px", marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, marginBottom: 6 }}>{t("exit.analysis_title")}</div>
            <div style={{ fontSize: 14, lineHeight: 1.55, color: "var(--text)" }}>
              {analysisLoading ? <span style={{ fontStyle: "italic", color: "var(--muted)" }}>{t("exit.analysis_loading")}</span> : analysis?.analysis}
            </div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {metrics.reflection_questions.map((q, i) => (
            <div key={i}>
              <label style={{ fontSize: 13, fontWeight: 600 }}>{q}</label>
              <AutoGrowTextarea
                value={responses[i]}
                onChange={(e) => setResponses((r) => r.map((v, j) => (j === i ? e.target.value : v)))}
                style={{
                  width: "100%",
                  marginTop: 6,
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  padding: "8px 10px",
                  background: "var(--bg)",
                  color: "var(--text)",
                  fontFamily: "var(--font-ui)",
                  fontSize: 13,
                  minHeight: 52,
                }}
              />
            </div>
          ))}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 18 }}>
          <button onClick={onClose} style={{ ...btn, background: "var(--surface-soft)", color: "var(--text-soft)", border: "1px solid var(--border)" }}>
            {t("exit.skip")}
          </button>
          <button onClick={finish} disabled={saving} style={{ ...btn, background: "var(--accent)", color: "#fff", border: "none" }}>
            {saving ? "…" : t("exit.finish")}
          </button>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: "var(--surface-soft)", borderRadius: "var(--radius-md)", padding: "14px 10px", textAlign: "center" }}>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{label}</div>
    </div>
  );
}

function formatDuration(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

const overlay: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.4)",
  display: "grid",
  placeItems: "center",
  zIndex: 100,
};
const card: React.CSSProperties = {
  width: "min(560px, 92vw)",
  maxHeight: "88vh",
  overflow: "auto",
  background: "var(--surface)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-lg)",
  padding: "var(--space-xl)",
};
const btn: React.CSSProperties = { borderRadius: "var(--radius-sm)", padding: "10px 20px", fontWeight: 600, cursor: "pointer" };
