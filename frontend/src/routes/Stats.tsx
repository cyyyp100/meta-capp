import { useQuery } from "@tanstack/react-query";
import { ArrowRight, LineChart } from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { SubjectEntry } from "../api/types";
import { Card } from "../components/Card";
import { EvolutionPanel } from "../features/stats/EvolutionPanel";
import { RadarPanel } from "../features/stats/RadarPanel";
import { scoreColor, scoreInk, subjectName } from "../features/stats/labels";
import { useT } from "../i18n";

export function Stats() {
  const t = useT();
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["stats", "overview"],
    queryFn: api.statsOverview,
  });

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

  // La pastille de tendance porte SA propre paire encre/lavis. Elle mélangeait
  // une encre sémantique et un lavis d'accent : dans le cas « stable », ça
  // donnait de l'orange de marque sur un lavis orange — 2,7:1, illisible. Une
  // pastille se lit à deux, pas à un.
  const trend =
    data.trend.delta > 2
      ? { ink: "var(--success)", wash: "var(--success-soft)" }
      : data.trend.delta < -2
        ? { ink: "var(--warning)", wash: "var(--warning-soft)" }
        : { ink: "var(--accent-ink)", wash: "var(--accent-soft)" };

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "var(--space-xl)" }}>
      {/* En-tête */}
      <Card style={{ marginBottom: "var(--space-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h1 style={{ fontFamily: "var(--font-title)", fontSize: "var(--text-h1)", margin: 0 }}>{t("stats.title")}</h1>
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
                background: trend.wash,
                color: trend.ink,
                fontWeight: 700,
                fontSize: 12,
              }}
            >
              {t(`trend.${data.trend.category}`)}
            </span>
            {/* Le lien vers les sources vivait dans « Évolution », où il ne
                concernait qu'un graphe. Il fonde TOUT le profil : sa place est
                sous le score global, dès le premier bloc. */}
            <div>
              <Link to="/stats/science" style={scienceLink}>
                {t("science.sources")}
              </Link>
            </div>
          </div>
        </div>
      </Card>

      {/* Analyse générale de l'apprenant (rédigée par Clikoda en fin de session). */}
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
          <div data-tour="profil">
            <RadarPanel criteria={data.criteria} />
          </div>
        </Card>
        <Card>
          <SectionTitle>{t("stats.criteria")}</SectionTitle>
          <div style={{ display: "grid", gap: 10 }}>
            {data.criteria.map((c) => (
              <div key={c.key}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                  <span style={{ fontWeight: 600 }}>{t(`crit.${c.key}`)}</span>
                  <span style={{ color: scoreInk(c.value), fontWeight: 700 }}>
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
        <SectionTitle>{t("stats.evolution")}</SectionTitle>
        <EvolutionPanel criteria={data.criteria} />
      </Card>

      {/* La porte vers l'historique, juste sous l'évolution : le radar dit OÙ on
          en est, la courbe COMMENT ça bouge, la progression D'OÙ ça vient. Elle
          fermait la page ; elle appartient à ce fil-là. */}
      <Link to="/stats/progress" style={progressLink}>
        <span style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
          <LineChart className="size-5 shrink-0" style={{ color: "var(--accent-ink)" }} aria-hidden />
          <span style={{ minWidth: 0 }}>
            <span style={{ display: "block", fontWeight: 700, fontSize: 15, color: "var(--text)" }}>
              {t("progress.title")}
            </span>
            <span style={{ display: "block", fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
              {t("progress.subtitle")}
            </span>
          </span>
        </span>
        <ArrowRight className="size-4.5 shrink-0" style={{ color: "var(--muted)" }} aria-hidden />
      </Link>

      {/* Matières — celles de l'apprenant (nwol/services/subjects.py), les mêmes
          que le sélecteur du quiz : une par document importé, une par langue
          pratiquée. */}
      <Card>
        <SectionTitle>{t("stats.by_subject")}</SectionTitle>
        {data.subjects.length === 0 ? (
          <div style={{ color: "var(--muted)", fontStyle: "italic" }}>{t("stats.no_subjects")}</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md)" }}>
            {data.subjects.map((s) => (
              <SubjectCard key={s.subject} subject={s} />
            ))}
          </div>
        )}
      </Card>

      {/* Le bloc « Mes données » (export, restauration, purge) vivait ici, au
          bas du profil : un écran de lecture qui se terminait par des actions
          destructrices. Il a sa place dans Réglages ▸ Données, où il est
          désormais seul à vivre. */}
    </div>
  );
}

/**
 * Une matière du profil. Une langue porte son drapeau, son niveau CECR et ses
 * séances ; tant qu'aucun quiz ne l'a mesurée, elle n'a pas de maîtrise — sa
 * carte le dit au lieu d'afficher un 50 de façade.
 */
function SubjectCard({ subject: s }: { subject: SubjectEntry }) {
  const t = useT();
  const language = s.kind === "language";
  const level = s.level;
  const cefr = language && s.cefr ? s.cefr : null;
  return (
    <Card soft>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <span style={{ fontWeight: 700, display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          {s.flag ? <span aria-hidden>{s.flag}</span> : null}
          {subjectName(t, s.subject)}
          {cefr && level !== null ? (
            <span title={t("lang.level")} style={cefrChip}>
              {cefr}
            </span>
          ) : null}
        </span>
        {level !== null ? (
          <span style={{ color: scoreInk(level), fontSize: 18, fontWeight: 700 }}>{Math.round(level)}</span>
        ) : cefr ? (
          <span title={t("lang.level")} style={{ color: "var(--accent-ink)", fontSize: 18, fontWeight: 700 }}>
            {cefr}
          </span>
        ) : null}
      </div>
      <div style={{ margin: "8px 0" }}>
        {level !== null ? (
          <Bar value={level} />
        ) : (
          <div style={{ fontSize: 12, lineHeight: "10px", color: "var(--muted)", fontStyle: "italic" }}>
            {t("stats.no_quiz_yet")}
          </div>
        )}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--muted)" }}>
        <span>
          {language ? t("stats.lang_sessions", { n: s.sessions ?? 0 }) : t("stats.updates", { n: s.updates })}
          {language && level !== null ? ` · ${t("stats.updates", { n: s.updates })}` : null}
        </span>
        {level !== null && s.recommendation ? (
          <span style={{ color: scoreInk(level), fontWeight: 700 }}>{t(`rec.${s.recommendation}`)}</span>
        ) : null}
      </div>
    </Card>
  );
}

/** Niveau CECR d'une langue, à côté de son nom quand la maîtrise occupe la place du chiffre. */
const cefrChip: React.CSSProperties = {
  padding: "1px 8px",
  borderRadius: 999,
  background: "var(--accent-soft)",
  color: "var(--accent-ink)",
  fontSize: 11,
  fontWeight: 700,
};

/** Le lien vers les sources scientifiques, sous le score global. */
const scienceLink: React.CSSProperties = {
  display: "inline-block",
  marginTop: 10,
  color: "var(--accent-ink)",
  cursor: "pointer",
  fontSize: 13,
  fontWeight: 700,
  textDecoration: "underline",
};

/** Le lien vers la progression : une carte pleine largeur, pas un lien de texte.
 *  C'est la seule porte vers l'historique depuis que « Progression » a quitté la
 *  barre latérale — elle doit se voir. */
const progressLink: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 16,
  marginBottom: "var(--space-lg)",
  padding: "var(--space-lg)",
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-sm)",
  textDecoration: "none",
  color: "inherit",
};

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
