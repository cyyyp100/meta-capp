import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { Card } from "../components/Card";
import { DataSection } from "../components/DataSection";
import { EvolutionPanel } from "../features/stats/EvolutionPanel";
import { RadarPanel } from "../features/stats/RadarPanel";
import { scoreColor, subjectLabel } from "../features/stats/labels";
import { useT } from "../i18n";

export function Stats() {
  const t = useT();
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["stats", "overview"],
    queryFn: api.statsOverview,
  });
  const { data: langStats } = useQuery({ queryKey: ["lang", "stats"], queryFn: api.langStats });

  const del = (d: number) => (d > 2 ? `+${Math.round(d)}` : d < -2 ? `${Math.round(d)}` : t("trend.stable"));

  if (isLoading) {
    return <Centered>{t("stats.loading")}</Centered>;
  }
  if (isError || !data) {
    return (
      <Centered>
        <span style={{ color: "var(--danger)" }}>
          {t("stats.error", { msg: String((error as Error)?.message ?? "?") })}
        </span>
      </Centered>
    );
  }

  const trendColor =
    data.trend.delta > 2 ? "var(--success)" : data.trend.delta < -2 ? "var(--warning)" : "var(--accent)";

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "var(--space-xl)" }}>
      {/* En-tête */}
      <Card style={{ marginBottom: "var(--space-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h1 style={{ fontFamily: "var(--font-title)", fontSize: 30, margin: 0 }}>{t("stats.title")}</h1>
            <div style={{ fontWeight: 600, marginTop: 8 }}>{data.user.name}</div>
            <div style={{ color: "var(--muted)", fontSize: 13 }}>
              {t("stats.sessions", { n: data.sessions_count, date: formatDate(data.updated_at) })}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ color: "var(--muted)", fontSize: 11, fontWeight: 700, letterSpacing: 0.4 }}>
              {t("stats.global")}
            </div>
            <div style={{ fontSize: 44, fontWeight: 700, lineHeight: 1 }}>{Math.round(data.global_score)}</div>
            <span
              style={{
                display: "inline-block",
                marginTop: 6,
                padding: "4px 12px",
                borderRadius: 999,
                background: "var(--accent-soft)",
                color: trendColor,
                fontWeight: 700,
                fontSize: 12,
              }}
            >
              {t(`trend.${data.trend.category}`)}
            </span>
          </div>
        </div>
      </Card>

      {/* Analyse générale de l'apprenant (rédigée par Gemma en fin de session). */}
      {data.general_analysis ? (
        <Card style={{ marginBottom: "var(--space-lg)" }}>
          <SectionTitle>{t("stats.analysis_title")}</SectionTitle>
          <p style={{ fontSize: 15, lineHeight: 1.6, color: "var(--text)", margin: 0 }}>{data.general_analysis}</p>
        </Card>
      ) : null}

      {/* Radar + cartes critères */}
      <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: "var(--space-lg)", marginBottom: "var(--space-lg)" }}>
        <Card>
          <SectionTitle>{t("stats.overview")}</SectionTitle>
          <RadarPanel criteria={data.criteria} />
        </Card>
        <Card>
          <SectionTitle>{t("stats.criteria")}</SectionTitle>
          <div style={{ display: "grid", gap: 10 }}>
            {data.criteria.map((c) => (
              <div key={c.key}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                  <span style={{ fontWeight: 600 }}>{t(`crit.${c.key}`)}</span>
                  <span style={{ color: scoreColor(c.value), fontWeight: 700 }}>
                    {Math.round(c.value)}{" "}
                    <span style={{ color: "var(--muted)", fontWeight: 500 }}>· {del(c.delta)}</span>
                  </span>
                </div>
                <Bar value={c.value} />
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Évolution */}
      <Card style={{ marginBottom: "var(--space-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <SectionTitle>{t("stats.evolution")}</SectionTitle>
          <Link
            to="/stats/science"
            style={{ color: "var(--accent-hover)", cursor: "pointer", fontSize: 13, fontWeight: 700, textDecoration: "underline" }}
          >
            {t("science.sources")}
          </Link>
        </div>
        <EvolutionPanel criteria={data.criteria} />
      </Card>

      {/* Matières */}
      <Card>
        <SectionTitle>{t("stats.by_subject")}</SectionTitle>
        {data.subjects.length === 0 ? (
          <div style={{ color: "var(--muted)", fontStyle: "italic" }}>{t("stats.no_subjects")}</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md)" }}>
            {data.subjects.map((s) => (
              <Card key={s.subject} soft>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontWeight: 700 }}>{subjectLabel(s.subject)}</span>
                  <span style={{ color: scoreColor(s.level), fontSize: 18, fontWeight: 700 }}>
                    {Math.round(s.level)}
                  </span>
                </div>
                <div style={{ margin: "8px 0" }}>
                  <Bar value={s.level} />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--muted)" }}>
                  <span>{t("stats.updates", { n: s.updates })}</span>
                  <span style={{ color: scoreColor(s.level), fontWeight: 700 }}>
                    {t(`rec.${s.recommendation}`)}
                  </span>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Card>

      {/* Langue — score global 0–100 + niveau CEFR par langue étudiée. */}
      <Card style={{ marginTop: "var(--space-lg)" }}>
        <SectionTitle>{t("stats.by_language")}</SectionTitle>
        {!langStats || langStats.length === 0 ? (
          <div style={{ color: "var(--muted)", fontStyle: "italic" }}>{t("stats.no_languages")}</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md)" }}>
            {langStats.map((l) => (
              <Card key={l.language} soft>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontWeight: 700 }}>
                    <span style={{ marginRight: 8 }}>{l.flag}</span>
                    {l.label}
                  </span>
                  <span style={{ color: scoreColor(l.global_score), fontSize: 18, fontWeight: 700 }}>
                    {Math.round(l.global_score)}
                  </span>
                </div>
                <div style={{ margin: "8px 0" }}>
                  <Bar value={l.global_score} />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--muted)" }}>
                  <span>{t("lang.lessons")} · {l.total_lessons}</span>
                  <span style={{ fontWeight: 700, color: "var(--accent-hover)" }}>{l.level}</span>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Card>

      {/* Sauvegarde / restauration des données locales (export DB, logs). */}
      <DataSection />

    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 style={{ fontSize: 14, fontWeight: 700, margin: "0 0 14px" }}>{children}</h2>;
}

function Bar({ value }: { value: number }) {
  return (
    <div style={{ height: 10, borderRadius: 999, background: "var(--border)", overflow: "hidden" }}>
      <div
        style={{
          height: "100%",
          width: `${Math.max(0, Math.min(100, value))}%`,
          background: scoreColor(value),
          borderRadius: 999,
          transition: "width var(--anim-slow) var(--ease)",
        }}
      />
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", placeItems: "center", height: "100%", color: "var(--muted)" }}>{children}</div>
  );
}

function formatDate(value: string): string {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 16);
}
