import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import { api } from "../../api/client";
import type { SessionMetrics } from "../../api/types";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import { WhyButton } from "../science/WhyButton";
import { formatDuration } from "./duration";
import { SasCard, SasOverlay } from "./SasOverlay";

// Bilan de fin de session : analyse LLM + métriques + questions de réflexion métacognitive.
//
// Deux questions FIXES s'affichent tout de suite : l'étudiant écrit pendant que
// Gemma travaille. La TROISIÈME est générée pour cette session et arrive avec
// l'analyse — c'est le même appel qui porte les deux. Attendre le LLM pour poser
// les trois faisait patienter devant un écran vide ; les figer toutes les trois
// jetait une question personnalisée déjà payée.
//
// Le sas s'affiche AU CLIC sur « Terminer », avant la réponse du serveur :
// `metrics` vaut `null` le temps de la clôture (`endSession`), et les chiffres
// comme les deux questions fixes arrivent avec elle. En attendant, on montre la
// structure du bilan plutôt qu'un lecteur figé — Gemma travaille en fond.
export function ExitSas({
  sessionId,
  metrics,
  onClose,
  demo = false,
}: {
  sessionId: number;
  /** `null` tant que la clôture n'a pas répondu : squelettes, boutons inactifs. */
  metrics: SessionMetrics | null;
  onClose: () => void;
  /**
   * Séance de démonstration de la visite guidée.
   *
   * C'EST ICI que se joue la promesse « la visite ne compte pas dans ton
   * profil ». Le sas de sortie est le seul endroit de toute l'application qui
   * pousse une session dans le modèle d'apprentissage (`finalizeSession` ->
   * `nudge_metacog_profile` -> `metacog/profile.py`). En démonstration, cet
   * appel n'a simplement pas lieu — pas plus que les invalidations de cache qui
   * feraient croire à l'accueil et à la frise que quelque chose a bougé.
   */
  demo?: boolean;
}) {
  const queryClient = useQueryClient();
  const t = useT();
  const reduce = useReducedMotion();
  const ending = metrics === null;
  const fixedQuestions = metrics?.reflection_questions ?? [];
  // Indexées comme les questions affichées (fixes puis générée). Les questions
  // arrivent après le montage : le tableau se remplit à l'index écrit, et les
  // trous sont lus comme des réponses vides à l'envoi.
  const [responses, setResponses] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  // Analyse LLM de la session (stats + jauges session + jauges profil) ET la
  // question de réflexion personnalisée. Best-effort. Elle ne part qu'une fois
  // la session CLOSE : la clôture purge la file LLM (cf. services.session), le
  // bilan est donc enfilé sur un worker libre — et il lit la durée qu'elle écrit.
  const { data: analysis, isLoading: rawAnalysisLoading } = useQuery({
    queryKey: ["session-analysis", sessionId],
    queryFn: () => api.sessionAnalysis(sessionId),
    staleTime: Infinity,
    // Aucune session n'existe côté serveur : la demander renverrait une erreur,
    // et la faire générer par Ollama ferait attendre devant un squelette.
    enabled: !demo && !ending,
  });
  const analysisLoading = demo ? false : ending || rawAnalysisLoading;
  const demoAnalysis = demo ? { analysis: t("demo.exit_analysis"), question: t("demo.reflect_3") } : null;
  const shownAnalysis = demoAnalysis ?? analysis;
  const generatedQuestion = shownAnalysis?.question ?? "";

  function setResponse(index: number, value: string) {
    setResponses((r) => {
      const next = [...r];
      next[index] = value;
      return next;
    });
  }

  // Les intitulés partent avec les réponses : la 3e n'existe nulle part côté
  // serveur, elle a été générée pour cette session.
  function submitFinalize() {
    // La séance de démonstration ne se finalise pas : elle n'existe pas côté
    // serveur (`session_id` vaut -1), et c'est très bien ainsi. Ni écriture de
    // profil, ni série d'étude, ni ligne dans la frise de progression.
    if (demo) return Promise.resolve(null);
    const questions = [...fixedQuestions, generatedQuestion];
    return api
      .finalizeSession(sessionId, questions.map((_, i) => responses[i] ?? ""), questions)
      .then((result) => {
        // La finalisation change trois choses que d'autres écrans affichent
        // déjà : la série d'étude, l'historique de progression et le profil.
        // Sans cette invalidation, l'accueil annonce encore la série d'hier et
        // la frise ignore la session qu'on vient de terminer.
        void queryClient.invalidateQueries({ queryKey: ["streak"] });
        void queryClient.invalidateQueries({ queryKey: ["progress"] });
        void queryClient.invalidateQueries({ queryKey: ["stats"] });
        return result;
      });
  }

  async function finish() {
    setSaving(true);
    try {
      await submitFinalize();
    } catch {
      /* on ferme quand même */
    }
    onClose();
  }

  // « Passer » finalise AUSSI, sans attendre : la session a été mesurée (jauges,
  // réponses évaluées), et jeter cette mesure parce que l'étudiant ne veut pas
  // écrire de réflexion n'avait pas de sens. Les réponses partent telles quelles
  // — vides, la métacognition n'est simplement pas notée (on ne note pas un
  // silence), et une session sans aucune mesure ne déplace rien.
  function skip() {
    submitFinalize().catch(() => {
      /* best-effort : la fermeture ne dépend pas du réseau */
    });
    onClose();
  }

  return (
    <SasOverlay variant="scrim">
      <SasCard data-tour="exit" className="max-h-[88vh] overflow-y-auto">
        <div className="flex items-start justify-between gap-3.5">
          <div>
            <h2 className="m-0 mb-1 font-serif text-h2 font-bold">{t("exit.title")}</h2>
            <p className="m-0 text-muted-foreground">{t("exit.subtitle")}</p>
          </div>
          <WhyButton whyKey="exit" />
        </div>

        <div className="my-4.5 grid grid-cols-4 gap-3">
          {[
            { label: t("exit.duration"), value: metrics && formatDuration(metrics.duration_s) },
            { label: t("exit.pages"), value: metrics && String(metrics.pages_read) },
            { label: t("exit.questions"), value: metrics && String(metrics.questions_answered) },
            { label: t("exit.success"), value: metrics && `${metrics.success_rate}%` },
          ].map((m, i) => (
            <Metric key={m.label} label={m.label} value={m.value} index={i} reduce={reduce} />
          ))}
        </div>

        {(analysisLoading || shownAnalysis?.analysis) && (
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
                shownAnalysis?.analysis
              )}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-3.5">
          {/* Les deux questions fixes voyagent avec les métriques : le temps de
              la clôture, leur place est tenue. */}
          {ending &&
            [0, 1].map((i) => (
              <div key={i} className="flex flex-col gap-2" role="status" aria-busy="true">
                <span className="sr-only">{t("exit.question_loading")}</span>
                <Skeleton className="h-3.5 w-[70%]" />
                <Skeleton className="h-[52px] w-full" />
              </div>
            ))}
          {fixedQuestions.map((q, i) => (
            <Reflection
              key={i}
              index={i}
              question={q}
              value={responses[i]}
              onChange={(value) => setResponse(i, value)}
            />
          ))}

          {/* La question personnalisée : elle arrive avec l'analyse, d'où le
              même état de chargement. Elle s'ajoute au bas de la liste plutôt
              que de décaler les deux premières, déjà en cours de rédaction. */}
          {analysisLoading ? (
            <div className="flex flex-col gap-2" role="status" aria-busy="true">
              <span className="sr-only">{t("exit.question_loading")}</span>
              <Skeleton className="h-3.5 w-[70%]" />
              <Skeleton className="h-[52px] w-full" />
            </div>
          ) : (
            generatedQuestion && (
              <motion.div
                initial={reduce ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease: [0.33, 1, 0.68, 1] }}
              >
                <Reflection
                  index={fixedQuestions.length}
                  question={generatedQuestion}
                  value={responses[fixedQuestions.length]}
                  onChange={(value) => setResponse(fixedQuestions.length, value)}
                />
              </motion.div>
            )
          )}
        </div>

        <div className="mt-4.5 flex justify-end gap-2.5">
          {/* Inactifs le temps de la clôture : finaliser AVANT qu'elle ait
              écrit la durée noterait une session de zéro seconde. */}
          <Button variant="secondary" onClick={skip} disabled={ending}>
            {t("exit.skip")}
          </Button>
          {/* Le bouton affichait « … » pendant l'enregistrement : un indicateur
              muet, indistinguable d'un libellé cassé. */}
          <Button onClick={finish} pending={saving} disabled={ending}>
            {t("exit.finish")}
          </Button>
        </div>
      </SasCard>
    </SasOverlay>
  );
}

function Reflection({
  index,
  question,
  value,
  onChange,
}: {
  index: number;
  question: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className="text-[13px] font-semibold" htmlFor={`reflection-${index}`}>
        {question}
      </label>
      <AutoGrowTextarea
        id={`reflection-${index}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
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
  );
}

function Metric({
  label,
  value,
  index,
  reduce,
}: {
  label: string;
  /** `null` : la clôture n'a pas encore répondu, la tuile tient sa place. */
  value: string | null;
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
      <div className="text-[22px] font-bold tabular-nums">
        {value ?? <Skeleton className="mx-auto h-[26px] w-12" />}
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{label}</div>
    </motion.div>
  );
}
