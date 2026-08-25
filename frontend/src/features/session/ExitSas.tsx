import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import { api } from "../../api/client";
import type { SessionMetrics } from "../../api/types";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import { WhyButton } from "../science/WhyButton";
import { SasCard, SasOverlay } from "./SasOverlay";

// Bilan de fin de session : analyse LLM + métriques + questions de réflexion métacognitive.
export function ExitSas({ metrics, onClose }: { metrics: SessionMetrics; onClose: () => void }) {
  const t = useT();
  const reduce = useReducedMotion();
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
    <SasOverlay variant="scrim">
      <SasCard className="max-h-[88vh] overflow-y-auto">
        <div className="flex items-start justify-between gap-3.5">
          <div>
            <h2 className="m-0 mb-1 font-serif text-[26px] font-bold">{t("exit.title")}</h2>
            <p className="m-0 text-muted-foreground">{t("exit.subtitle")}</p>
          </div>
          <WhyButton whyKey="exit" />
        </div>

        <div className="my-4.5 grid grid-cols-4 gap-3">
          {[
            { label: t("exit.duration"), value: formatDuration(metrics.duration_s) },
            { label: t("exit.pages"), value: String(metrics.pages_read) },
            { label: t("exit.questions"), value: String(metrics.questions_answered) },
            { label: t("exit.success"), value: `${metrics.success_rate}%` },
          ].map((m, i) => (
            <Metric key={m.label} label={m.label} value={m.value} index={i} reduce={reduce} />
          ))}
        </div>

        {(analysisLoading || analysis?.analysis) && (
          <div className="mb-4 rounded-md bg-brand-soft px-4 py-3.5 text-accent-foreground">
            <div className="mb-1.5 text-[11px] font-bold tracking-wide">
              {t("exit.analysis_title")}
            </div>
            <div className="text-sm leading-relaxed text-foreground">
              {analysisLoading ? (
                // C'était un texte gris en italique : rien ne bougeait, on ne
                // savait pas si l'analyse arrivait ou si elle avait échoué.
                <div className="flex flex-col gap-2" role="status" aria-busy="true">
                  <span className="sr-only">{t("exit.analysis_loading")}</span>
                  <Skeleton className="h-3.5 w-full" />
                  <Skeleton className="h-3.5 w-[85%]" />
                  <Skeleton className="h-3.5 w-[60%]" />
                </div>
              ) : (
                analysis?.analysis
              )}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-3.5">
          {metrics.reflection_questions.map((q, i) => (
            <div key={i}>
              <label className="text-[13px] font-semibold" htmlFor={`reflection-${i}`}>
                {q}
              </label>
              <AutoGrowTextarea
                id={`reflection-${i}`}
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

        <div className="mt-4.5 flex justify-end gap-2.5">
          <Button variant="secondary" onClick={onClose}>
            {t("exit.skip")}
          </Button>
          {/* Le bouton affichait « … » pendant l'enregistrement : un indicateur
              muet, indistinguable d'un libellé cassé. */}
          <Button onClick={finish} pending={saving}>
            {t("exit.finish")}
          </Button>
        </div>
      </SasCard>
    </SasOverlay>
  );
}

function Metric({
  label,
  value,
  index,
  reduce,
}: {
  label: string;
  value: string;
  index: number;
  reduce: boolean | null;
}) {
  return (
    <motion.div
      className="rounded-md bg-surface-soft px-2.5 py-3.5 text-center"
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.08 + index * 0.06, ease: [0.33, 1, 0.68, 1] }}
    >
      <div className="text-[22px] font-bold tabular-nums">{value}</div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{label}</div>
    </motion.div>
  );
}

function formatDuration(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}
