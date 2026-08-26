import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import { api } from "../../api/client";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import { WhyButton } from "../science/WhyButton";
import { formatDuration } from "../session/duration";
import { SasCard, SasOverlay } from "../session/SasOverlay";

// Bilan de fin de session de quiz : métriques + analyse LLM + questions de
// métacognition. Même rituel que le sas de sortie d'une lecture ou d'une séance
// de langue, et surtout la même finalisation côté serveur (`/api/quiz/finalize`
// → `nudge_metacog_profile`) : un quiz mesure un apprentissage, il doit peser
// sur le profil long terme au lieu de se terminer sur un simple score.
export function QuizExitSas({
  correct,
  total,
  durationS,
  analysis,
  analysisLoading,
  subject,
  topic,
  onClose,
}: {
  correct: number;
  total: number;
  durationS: number;
  /** Analyse LLM déjà chargée par l'écran de bilan — pas de second appel. */
  analysis?: string;
  analysisLoading?: boolean;
  subject?: string;
  topic?: string;
  onClose: () => void;
}) {
  const t = useT();
  const reduce = useReducedMotion();
  const questions = [t("quiz.reflect_1"), t("quiz.reflect_2"), t("quiz.reflect_3")];
  const [responses, setResponses] = useState<string[]>(questions.map(() => ""));
  const [saving, setSaving] = useState(false);

  const successRate = total > 0 ? Math.round((100 * correct) / total) : 0;

  async function finish() {
    setSaving(true);
    try {
      await api.quizFinalize({
        responses,
        score: successRate,
        questions_answered: total,
        correct,
        duration_s: durationS,
        subject: subject || null,
        topic: topic || null,
      });
    } catch {
      /* on ferme quand même : le bilan ne doit jamais bloquer la sortie */
    }
    onClose();
  }

  return (
    <SasOverlay variant="scrim">
      <SasCard className="max-h-[88vh] overflow-y-auto">
        <div className="flex items-start justify-between gap-3.5">
          <div>
            <h2 className="m-0 mb-1 font-serif text-[26px] font-bold">{t("exit.title")}</h2>
            <p className="m-0 text-muted-foreground">{t("quiz.exit_subtitle")}</p>
          </div>
          <WhyButton whyKey="exit" />
        </div>

        <div className="my-4.5 grid grid-cols-3 gap-3">
          {[
            { label: t("exit.duration"), value: formatDuration(durationS) },
            { label: t("exit.questions"), value: `${correct} / ${total}` },
            { label: t("exit.success"), value: `${successRate}%` },
          ].map((m, i) => (
            <Metric key={m.label} label={m.label} value={m.value} index={i} reduce={reduce} />
          ))}
        </div>

        {(analysisLoading || analysis) && (
          <div className="mb-4 rounded-md bg-brand-soft px-4 py-3.5 text-accent-foreground">
            <div className="mb-1.5 text-[11px] font-bold tracking-wide">
              {t("exit.analysis_title")}
            </div>
            <div className="text-sm leading-relaxed text-foreground">
              {analysisLoading ? (
                <div className="flex flex-col gap-2" role="status" aria-busy="true">
                  <span className="sr-only">{t("exit.analysis_loading")}</span>
                  <Skeleton className="h-3.5 w-full" />
                  <Skeleton className="h-3.5 w-[85%]" />
                  <Skeleton className="h-3.5 w-[60%]" />
                </div>
              ) : (
                analysis
              )}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-3.5">
          {questions.map((q, i) => (
            <div key={q}>
              <label className="text-[13px] font-semibold" htmlFor={`quiz-reflection-${i}`}>
                {q}
              </label>
              <AutoGrowTextarea
                id={`quiz-reflection-${i}`}
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
