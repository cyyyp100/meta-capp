import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import { scoreColor, scoreInk } from "../stats/labels";
import { WhyButton } from "../science/WhyButton";
import { SKILL_ORDER } from "./skills";
import { formatDuration } from "../session/duration";
import { SasCard, SasOverlay } from "../session/SasOverlay";

// Bilan de fin de séance de langue : métriques + décomposition par compétence +
// analyse LLM + questions de métacognition. Même rituel que le SAS de sortie d'un
// PDF ; la finalisation nourrit aussi le profil métacognitif global.
export function LangExitSas({
  lessonId,
  durationS,
  exerciseCount,
  score,
  onClose,
}: {
  lessonId: number;
  durationS: number;
  exerciseCount: number;
  score: number; // 0–1
  onClose: () => void;
}) {
  const t = useT();
  const questions = [t("lang.reflect_1"), t("lang.reflect_2"), t("lang.reflect_3")];
  const [responses, setResponses] = useState<string[]>(questions.map(() => ""));
  const [saving, setSaving] = useState(false);

  // Bilan LLM + scores par compétence (cumul), best-effort.
  const { data: analysis, isLoading: analysisLoading } = useQuery({
    queryKey: ["lang-analysis", lessonId],
    queryFn: () => api.langLessonAnalysis(lessonId),
    staleTime: Infinity,
  });

  const skills = analysis?.skills ?? {};
  const skillRows = SKILL_ORDER.filter((k) => skills[k]);

  async function finish() {
    setSaving(true);
    try {
      await api.langLessonFinalize(lessonId, responses, questions);
    } catch {
      /* on ferme quand même */
    }
    onClose();
  }

  return (
    <SasOverlay variant="scrim">
      <SasCard className="max-h-[88vh] overflow-y-auto">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 14 }}>
          <div>
            <h2 style={{ fontFamily: "var(--font-title)", fontSize: "var(--text-h2)", margin: "0 0 4px" }}>{t("exit.title")}</h2>
            <p style={{ color: "var(--muted)", margin: 0 }}>{t("lang.exit_subtitle")}</p>
          </div>
          <WhyButton whyKey="exit" />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, margin: "18px 0" }}>
          <Metric label={t("exit.duration")} value={formatDuration(durationS)} />
          <Metric label={t("lang.exit_exercises")} value={String(exerciseCount)} />
          <Metric label={t("exit.success")} value={`${Math.round(score * 100)}%`} />
        </div>

        {skillRows.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, marginBottom: 8, color: "var(--muted)" }}>
              {t("lang.skills_title")}
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {skillRows.map((k) => (
                <SkillBar key={k} label={t(`skill.${k}`)} value={skills[k].score} />
              ))}
            </div>
          </div>
        )}

        {(analysisLoading || analysis?.analysis) && (
          <div style={{ background: "var(--accent-soft)", color: "var(--accent-ink)", borderRadius: "var(--radius-md)", padding: "14px 16px", marginBottom: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, marginBottom: 6 }}>{t("exit.analysis_title")}</div>
            <div style={{ fontSize: 14, lineHeight: 1.55, color: "var(--text)" }}>
              {analysisLoading ? <span style={{ fontStyle: "italic", color: "var(--muted)" }}>{t("exit.analysis_loading")}</span> : analysis?.analysis}
            </div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {questions.map((q, i) => (
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
          <button onClick={finish} disabled={saving} style={{ ...btn, background: "var(--accent)", color: "var(--on-accent)", border: "none" }}>
            {saving ? "…" : t("exit.finish")}
          </button>
        </div>
      </SasCard>
    </SasOverlay>
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

function SkillBar({ label, value }: { label: string; value: number }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
        <span>{label}</span>
        <span style={{ color: scoreInk(v), fontWeight: 700 }}>{Math.round(v)}</span>
      </div>
      <div style={{ height: 7, borderRadius: 999, background: "var(--border)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${v}%`, background: scoreColor(v), borderRadius: 999 }} />
      </div>
    </div>
  );
}

const btn: React.CSSProperties = { borderRadius: "var(--radius-sm)", padding: "10px 20px", fontWeight: 600, cursor: "pointer" };
