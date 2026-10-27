import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type {
  QuizAnswerRecord,
  QuizEvaluation,
  QuizQuestion,
  QuizSessionSettings,
  QuizSignals,
  QuizVerdict,
} from "../api/types";
import { ArrowLeft, ArrowRight, Check, Eye, Lightbulb, Minus, Plus, Search, Shuffle, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { AnswerInput } from "../features/questions/AnswerInput";
import { QuestionStem } from "../features/questions/QuestionStem";
import { QuestionTypeBadge } from "../features/questions/QuestionTypeBadge";
import { VerdictBadge } from "../features/questions/VerdictBadge";
import { answerWidget } from "../features/questions/registry";
import { renderMathToHtml } from "../features/reader/renderMath";
import { MathText } from "../components/MathText";
import { WhyButton } from "../features/science/WhyButton";
import { formatDuration } from "../features/session/duration";
import { useT } from "../i18n";
// Code de matière (tel que stocké en base) -> libellé traduit.
import { subjectName as translatedSubject } from "../features/stats/labels";

/**
 * Ce qu'une question rapporte à la session. Le verdict vient du serveur pour une
 * réponse rédigée ou une remise en ordre, de la comparaison locale pour un QCM ;
 * `score` en est le poids (1 / 0,5 / 0), un « partiel » valant un demi-point.
 *
 * Le reste nourrit la courbe de jauges de la séance, enregistrée à la fin :
 * `graded` (faux quand l'apprenant a tranché lui-même), le temps de réponse, et
 * les signaux que le LLM a lus dans une réponse rédigée.
 */
type QuizOutcome = {
  verdict: QuizVerdict;
  score: number;
  userAnswer: string;
  graded: boolean;
  responseTimeMs: number;
  signals?: QuizSignals | null;
};

/** Un demi-point doit rester lisible dans le bilan : « 3,5 » et pas « 3.5000 ». */
function formatScore(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/**
 * Deux façons de lancer une session, qui ne se mélangent pas :
 * - « subject » : une matière (ou toutes), puis une précision libre DANS celle-ci ;
 * - « multi » : le multi-apprentissage (pratique entrelacée), tiré dans toute la
 *   base en changeant de domaine — il n'a ni matière ni précision.
 * Seul le nombre de questions est commun aux deux.
 */
type QuizMode = "subject" | "multi";

/**
 * Réglages d'une session, figés au clic sur « Lancer ». La requête, la clôture et
 * le message d'absence de résultat lisent CECI et jamais le formulaire : ils
 * parlent de la session jouée, pas de ce que l'on est en train de retaper.
 * `run` distingue deux lancements aux réglages identiques (sinon React Query
 * resservirait la session précédente depuis son cache).
 */
type QuizRequest = {
  mode: QuizMode;
  subject: string;
  topic: string;
  length: number | undefined;
  run: number;
};

export function Quiz() {
  const t = useT();
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const [mode, setMode] = useState<QuizMode>("subject");
  // Matière et précision survivent à un passage en multi-apprentissage : elles y
  // sont simplement ignorées, et on les retrouve en revenant « par matière ».
  const [subject, setSubject] = useState("");
  const [topic, setTopic] = useState("");
  const [length, setLength] = useState<number | null>(null);
  const [asked, setAsked] = useState<QuizRequest | null>(null);
  const runs = useRef(0);

  const subjectsQuery = useQuery({
    queryKey: ["quiz", "subjects"],
    queryFn: () => api.quizSubjects(),
  });

  // Bornes et valeur par défaut du nombre de questions : c'est le serveur qui les
  // déclare (config/settings.py), l'UI ne fait que les appliquer.
  const optionsQuery = useQuery({
    queryKey: ["quiz", "options"],
    queryFn: () => api.quizOptions(),
    staleTime: Infinity,
  });
  const options = optionsQuery.data;
  const chosenLength = length ?? options?.default_length;

  // La génération LLM (un seul appel batch) n'est déclenchée qu'après un clic
  // explicite sur « Lancer le quiz » : on laisse le temps de régler la session.
  const { data, isFetching, isError } = useQuery({
    queryKey: ["quiz", "questions", asked],
    queryFn: () =>
      api.quizQuestions(
        asked?.length,
        asked?.subject || undefined,
        asked?.topic || undefined,
        asked?.mode === "multi",
      ),
    enabled: asked !== null,
  });

  const [index, setIndex] = useState(0);
  const [score, setScore] = useState(0);
  const [done, setDone] = useState(false);
  const [byCat, setByCat] = useState<Record<string, { correct: number; total: number }>>({});
  const [history, setHistory] = useState<QuizAnswerRecord[]>([]);
  const [durationS, setDurationS] = useState(0);
  const startedAt = useRef(0);

  // La séance est enregistrée côté serveur à la fin — ou quand on la quitte en
  // cours de route (barre latérale) : ses réponses y deviennent une courbe de
  // jauges, que la clôture remonte au profil. Les refs servent le démontage,
  // qui ne voit plus l'état React.
  const historyRef = useRef<QuizAnswerRecord[]>([]);
  const settingsRef = useRef<QuizSessionSettings>({ mode: "subject", subject: null, topic: null });
  const recording = useRef<Promise<number | null> | null>(null);
  // Une séance ne se clôt qu'une fois (le serveur le garantit aussi : une
  // seconde clôture ne fait pas glisser le profil deux fois).
  const finalizedIds = useRef(new Set<number>());
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [recorded, setRecorded] = useState(false);

  // Réponses rédigées : corrigées par Clikoda EN ARRIÈRE-PLAN, sans faire
  // attendre la question suivante (une correction prend des dizaines de
  // secondes sur un modèle local). Leur verdict n'apparaît qu'au bilan, qui
  // les attend avant d'enregistrer la séance. Clés : rang dans `historyRef`.
  const pending = useRef(new Map<number, Promise<QuizEvaluation | null>>());
  // Rangs sans verdict définitif (correction en cours, ou à trancher par
  // l'apprenant) : une séance quittée avant ne les enregistre pas.
  const unsettled = useRef(new Set<number>());
  const [corrections, setCorrections] = useState<Record<number, QuizEvaluation>>({});
  const [grading, setGrading] = useState<{ done: number; total: number } | null>(null);
  const [toSelfGrade, setToSelfGrade] = useState<number[]>([]);
  // Réponse attendue de chaque réponse rédigée, pour le bilan (même sans correction).
  const expected = useRef(new Map<number, string>());
  const selfGraded = useRef<(() => void) | null>(null);
  // Change à chaque nouvelle séance : une correction arrivée pour l'ancienne
  // ne touche pas à la nouvelle.
  const generation = useRef(0);

  // L'analyse lit les réglages FIGÉS de la session (matière, précision, mode) :
  // elle parle de ce qui a été joué, pas du profil entier. Elle attend
  // l'enregistrement de la séance (sans LLM, immédiat) pour être gardée avec elle.
  const analysisQuery = useQuery({
    queryKey: ["quiz", "analysis", asked, sessionId],
    queryFn: () => api.quizAnalysis(history, settingsRef.current, sessionId),
    enabled: done && recorded && history.length > 0,
  });

  // La clôture part APRÈS le bilan : elle réécrit l'analyse générale avec
  // Clikoda, et il n'y a qu'un worker LLM — le bilan affiché passe devant.
  useEffect(() => {
    if (analysisQuery.isSuccess || analysisQuery.isError) finalize(sessionId);
  }, [analysisQuery.isSuccess, analysisQuery.isError, sessionId]);

  // Quitter en cours de quiz (ou pendant le bilan) : la séance est enregistrée
  // et close quand même — ses réponses sont des mesures. Sans réponse, rien.
  useEffect(() => {
    return () => {
      if (historyRef.current.length === 0) return;
      void settlePending().then(() => record()).then(finalize);
    };
    // Au démontage seulement : les refs portent l'état de la séance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Libellé affiché d'une matière (code stocké en base → nom traduit). */
  function subjectName(code: string): string {
    return translatedSubject(t, code);
  }

  // Les matières de l'apprenant — celles de son profil, pas un catalogue commun.
  // Une matière sans question jouable (document importé, pas encore lu) reste
  // visible mais n'est pas proposée.
  const subjectOptions = useMemo(() => {
    const own = subjectsQuery.data ?? [];
    const total = own.reduce((s, x) => s + x.count, 0);
    return [
      { code: "", label: `${t("subj.all")} (${total})`, disabled: false },
      ...own.map((x) => ({
        code: x.subject,
        label: `${x.flag ? `${x.flag} ` : ""}${translatedSubject(t, x.subject)} (${x.count})`,
        disabled: x.count === 0,
      })),
    ];
  }, [subjectsQuery.data, t]);

  function resetState() {
    // Une séance enregistrée dont le bilan n'est pas arrivé (« Recommencer »
    // pressé pendant l'analyse) est close maintenant : ses mesures restent.
    if (recording.current) void recording.current.then(finalize);
    recording.current = null;
    historyRef.current = [];
    generation.current += 1;
    pending.current = new Map();
    unsettled.current = new Set();
    expected.current = new Map();
    selfGraded.current = null;
    setCorrections({});
    setGrading(null);
    setToSelfGrade([]);
    setSessionId(null);
    setRecorded(false);
    setIndex(0);
    setScore(0);
    setDone(false);
    setByCat({});
    setHistory([]);
    setDurationS(0);
  }

  function answered(q: QuizQuestion, outcome: QuizOutcome) {
    keep(q, outcome);
    count(q.category, outcome.verdict, outcome.score);
  }

  /** Points, bilan par matière et maîtrise : au verdict, tout de suite ou au bilan. */
  function count(category: string | null | undefined, verdict: QuizVerdict, points: number) {
    setScore((s) => s + points);
    const cat = category || "autre";
    setByCat((b) => ({ ...b, [cat]: { correct: (b[cat]?.correct ?? 0) + points, total: (b[cat]?.total ?? 0) + 1 } }));
    // Maîtrise de la matière ; le verdict garde le « partiel ».
    void api.submitQuizAnswer(category ?? "", verdict === "correct", verdict);
  }

  /** Ajoute la réponse à la séance ; renvoie son rang. */
  function keep(q: QuizQuestion, outcome: QuizOutcome): number {
    const cat = q.category || "autre";
    historyRef.current = [
      ...historyRef.current,
      {
        question_id: q.id,
        question: q.question,
        question_type: q.question_type,
        user_answer: outcome.userAnswer,
        verdict: outcome.verdict,
        score: outcome.score,
        category: cat,
        source: q.source,
        document: q.document ?? null,
        document_id: q.document_id ?? null,
        chapter_title: q.chapter_title ?? null,
        graded: outcome.graded,
        response_time_ms: outcome.responseTimeMs,
        signals: outcome.signals ?? null,
      },
    ];
    setHistory(historyRef.current);
    return historyRef.current.length - 1;
  }

  /** Réponse rédigée : la question suivante n'attend pas sa correction. Elle
   *  compte pour zéro tant que Clikoda ne l'a pas corrigée (au bilan). */
  function deferred(q: QuizQuestion, written: string, responseTimeMs: number) {
    const rank = keep(q, { verdict: "incorrect", score: 0, userAnswer: written, graded: false, responseTimeMs });
    unsettled.current.add(rank);
    expected.current.set(rank, q.answer);
    pending.current.set(
      rank,
      api
        .quizEvaluate({
          question_id: q.id,
          question: q.question,
          user_answer: written,
          question_type: q.question_type,
          answer: q.answer,
          choices: q.choices,
        })
        .then((evaluation) => (evaluation.graded && evaluation.verdict ? evaluation : null))
        .catch(() => null),
    );
  }

  /** Verdict définitif d'une réponse rédigée : dans la séance, le score et le bilan. */
  function settle(rank: number, evaluation: QuizEvaluation) {
    const entry = historyRef.current[rank];
    if (!entry || !evaluation.verdict) return;
    historyRef.current = historyRef.current.map((e, i) =>
      i === rank
        ? { ...e, verdict: evaluation.verdict as QuizVerdict, score: evaluation.score, graded: evaluation.graded, signals: evaluation.signals ?? null }
        : e,
    );
    setHistory(historyRef.current);
    unsettled.current.delete(rank);
    count(entry.category, evaluation.verdict, evaluation.score);
    setCorrections((c) => ({ ...c, [rank]: evaluation }));
  }

  /** Attend les corrections lancées. Celles que le serveur n'a pas pu rendre
   *  restent à trancher (`toSelfGrade`) ; sans `ask`, elles sont laissées de
   *  côté (séance quittée en cours de route). */
  async function settlePending(ask = false) {
    const gen = generation.current;
    const waiting = [...pending.current.entries()];
    pending.current = new Map();
    if (waiting.length === 0) return;
    let finished = 0;
    if (ask) setGrading({ done: 0, total: waiting.length });
    const failed: number[] = [];
    await Promise.all(
      waiting.map(async ([rank, promise]) => {
        const evaluation = await promise;
        if (gen !== generation.current) return;
        finished += 1;
        if (ask) setGrading({ done: finished, total: waiting.length });
        if (evaluation) settle(rank, evaluation);
        else failed.push(rank);
      }),
    );
    if (!ask || gen !== generation.current || failed.length === 0) return;
    // Clikoda n'a pas pu corriger (modèle éteint) : l'apprenant tranche, comme
    // il le faisait question par question, avant que la séance ne parte.
    failed.sort((a, b) => a - b);
    await new Promise<void>((resolve) => {
      selfGraded.current = resolve;
      setToSelfGrade(failed);
    });
  }

  function selfGradeLater(rank: number, knew: boolean) {
    const verdict: QuizVerdict = knew ? "correct" : "incorrect";
    settle(rank, localVerdict(expected.current.get(rank) ?? "", verdict));
    setToSelfGrade((left) => {
      const rest = left.filter((r) => r !== rank);
      if (rest.length === 0) selfGraded.current?.();
      return rest;
    });
  }

  /** Enregistre la séance (une fois) ; résout son id, ou null sans réponse ni serveur. */
  function record(): Promise<number | null> {
    if (!recording.current) {
      const answers = historyRef.current.filter((_, rank) => !unsettled.current.has(rank));
      const elapsed = Math.max(0, Math.round((Date.now() - startedAt.current) / 1000));
      recording.current =
        answers.length === 0
          ? Promise.resolve(null)
          : api
              .quizRecordSession({ settings: settingsRef.current, answers, duration_s: elapsed })
              .then((saved) => saved.session_id)
              .catch(() => null);
    }
    return recording.current;
  }

  // Clôture : même chemin serveur qu'une fin de lecture (`nudge_metacog_profile`),
  // le profil glissant vers la courbe de jauges de la séance. Sans questions de
  // réflexion — le bilan est une page, plus un rituel.
  function finalize(id: number | null) {
    if (id === null || finalizedIds.current.has(id)) return;
    finalizedIds.current.add(id);
    void api.quizFinalize(id).catch(() => {
      /* la clôture ne doit jamais abîmer l'affichage du bilan */
    });
  }

  function next(total: number) {
    if (index + 1 >= total) {
      const elapsed = Math.max(0, Math.round((Date.now() - startedAt.current) / 1000));
      setDurationS(elapsed);
      setDone(true);
      // Déclenché depuis le handler et non un effet : l'app est montée en StrictMode.
      // La séance part une fois les réponses rédigées corrigées : le bilan et
      // l'analyse lisent leurs verdicts.
      const gen = generation.current;
      void settlePending(true).then(() => {
        if (gen !== generation.current) return;
        const saving = record();
        void saving.then((id) => {
          // « Recommencer » pressé entre-temps : cette séance n'est plus à l'écran.
          if (recording.current !== saving) return;
          setSessionId(id);
          setRecorded(true);
        });
      });
    } else setIndex((i) => i + 1);
  }

  /**
   * Fige les réglages de la session et la lance. En multi-apprentissage, matière
   * et précision ne partent pas : `finalize()` enregistre alors la session sans
   * elles — ce qu'elle est. `n` : longueur que le champ numérique vient d'arrêter
   * (Entrée pressée avant que son état ne soit relu).
   */
  function startQuiz(n?: number) {
    const multi = mode === "multi";
    resetState();
    runs.current += 1;
    settingsRef.current = {
      mode,
      subject: multi ? null : subject || null,
      topic: multi ? null : topic.trim() || null,
    };
    setAsked({
      mode,
      subject: multi ? "" : subject,
      topic: multi ? "" : topic.trim(),
      length: n ?? chosenLength,
      run: runs.current,
    });
    startedAt.current = Date.now();
  }

  function restart() {
    resetState();
    setAsked(null);
  }

  /** « Retour » : l'écran de lancement par défaut, sans les réglages de la session
   *  jouée — « Recommencer », lui, les garde. */
  function backToStart() {
    setMode("subject");
    setSubject("");
    setTopic("");
    setLength(null);
    restart();
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "var(--space-xl)" }}>
      <h1 style={{ fontFamily: "var(--font-title)", fontSize: "var(--text-h1)", margin: "0 0 4px" }}>{t("quiz.title")}</h1>
      <p style={{ color: "var(--muted)", marginTop: 0 }}>{t("quiz.subtitle")}</p>

      {asked === null && (
        <div className="mt-6 rounded-lg border border-border bg-surface p-5 shadow-e1">
          <div role="group" aria-label={t("quiz.mode_label")} className="mb-5 flex flex-wrap gap-2">
            {(["subject", "multi"] as const).map((value) => (
              <Button
                key={value}
                size="sm"
                variant={mode === value ? "default" : "secondary"}
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
              >
                {value === "multi" && <Shuffle aria-hidden />}
                {t(value === "multi" ? "quiz.mode_multi" : "quiz.mode_subject")}
              </Button>
            ))}
          </div>

          {mode === "subject" ? (
            <div className="grid gap-4">
              <Field label={t("quiz.subject_label")}>
                <Select value={subject} onValueChange={setSubject}>
                  <SelectTrigger className="w-full sm:w-[280px]" aria-label={t("quiz.subject_label")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {subjectOptions.map((option) => (
                      <SelectItem key={option.code} value={option.code} disabled={option.disabled}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {subjectsQuery.data?.length === 0 && (
                  <p className="m-0 mt-2 text-xs text-muted-foreground">{t("quiz.no_subjects")}</p>
                )}
              </Field>

              {/* La précision vient APRÈS la matière : elle affine dedans (ou dans
                  toute la base si aucune matière n'est choisie), elle ne la
                  concurrence pas. */}
              <Field label={t("quiz.topic_label")} htmlFor="quiz-topic">
                <TopicInput
                  value={topic}
                  onChange={setTopic}
                  onSubmit={() => startQuiz()}
                  placeholder={
                    subject
                      ? t("quiz.topic_placeholder_in", { subject: subjectName(subject) })
                      : t("quiz.topic_placeholder")
                  }
                />
              </Field>
            </div>
          ) : (
            <div className="flex items-center gap-1 rounded-md bg-surface-soft py-1.5 pr-1.5 pl-3.5">
              <p className="m-0 flex-1 text-sm text-text-soft">{t("quiz.multi_hint")}</p>
              <WhyButton whyKey="interleaving" variant="icon" label={t("quiz.multi_why")} />
            </div>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border pt-4">
            <label htmlFor="quiz-length" className="text-[13px] font-semibold">
              {t("quiz.length_label")}
            </label>
            {options && chosenLength != null && (
              <>
                <QuestionCountInput
                  value={chosenLength}
                  min={options.min_length}
                  max={options.max_length}
                  onChange={setLength}
                  onSubmit={startQuiz}
                />
                <span className="text-xs text-muted-foreground">
                  {t("quiz.length_range", { min: options.min_length, max: options.max_length })}
                </span>
              </>
            )}
          </div>

          <Button size="lg" onClick={() => startQuiz()} className="mt-5">
            {t("quiz.start")}
          </Button>
        </div>
      )}

      {isFetching && <p style={{ color: "var(--muted)" }}>{t("quiz.generating")}</p>}
      {isError && !isFetching && (
        // Même impasse que ci-dessous : le panneau est masqué, il faut un retour.
        <div style={{ marginTop: 32 }}>
          <p style={{ color: "var(--danger)" }}>{t("quiz.error")}</p>
          <Button variant="secondary" onClick={restart}>
            {t("quiz.restart")}
          </Button>
        </div>
      )}
      {!isFetching && data && data.length === 0 && (
        // Le panneau de réglages est masqué pendant une session : sans ce retour,
        // un sujet sans résultat laissait l'écran dans une impasse.
        <div style={{ marginTop: 32 }}>
          <p style={{ color: "var(--muted)", fontStyle: "italic" }}>
            {asked?.mode === "multi"
              ? t("quiz.multi_none")
              : asked?.topic
                ? asked.subject
                  ? t("quiz.noneForTopicInSubject", {
                      topic: asked.topic,
                      subject: subjectName(asked.subject),
                    })
                  : t("quiz.noneForTopic", { topic: asked.topic })
                : t("quiz.none")}
          </p>
          <Button variant="secondary" onClick={restart}>
            {t("quiz.restart")}
          </Button>
        </div>
      )}

      {!isFetching && data && data.length > 0 && !done && (
        <QuestionCard
          key={data[index].id}
          q={data[index]}
          position={`${index + 1} / ${data.length}`}
          onAnswered={(outcome) => answered(data[index], outcome)}
          onDeferred={(written, ms) => deferred(data[index], written, ms)}
          onNext={() => next(data.length)}
        />
      )}

      {!isFetching && data && done && (
        <div style={{ marginTop: 32, textAlign: "center" }}>
          <div style={{ fontSize: 48, fontWeight: 700 }}>{formatScore(score)} / {data.length}</div>
          <p style={{ color: "var(--muted)" }}>{t("quiz.done")}</p>

          <div className="mx-auto my-4.5 grid max-w-[360px] grid-cols-3 gap-3">
            {[
              { label: t("exit.duration"), value: formatDuration(durationS) },
              { label: t("exit.questions"), value: `${formatScore(score)} / ${data.length}` },
              {
                label: t("exit.success"),
                value: `${data.length > 0 ? Math.round((100 * score) / data.length) : 0}%`,
              },
            ].map((m, i) => (
              <Metric key={m.label} label={m.label} value={m.value} index={i} reduce={reduce} />
            ))}
          </div>

          <div style={{ maxWidth: 360, margin: "16px auto", display: "grid", gap: 8, textAlign: "left" }}>
            {Object.entries(byCat).map(([cat, r]) => (
              <div key={cat} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span style={{ color: "var(--text-soft)" }}>{subjectName(cat)}</span>
                <span style={{ fontWeight: 700, color: r.correct === r.total ? "var(--success)" : "var(--warning)" }}>
                  {formatScore(r.correct)}/{r.total}
                </span>
              </div>
            ))}
          </div>

          {grading && grading.done < grading.total && (
            <p style={{ color: "var(--muted)" }}>{t("quiz.grading", { done: grading.done, total: grading.total })}</p>
          )}
          <DeferredCorrections
            history={history}
            corrections={corrections}
            toSelfGrade={toSelfGrade}
            expected={expected.current}
            onSelfGrade={selfGradeLater}
          />

          {analysisQuery.isFetching && <p style={{ color: "var(--muted)" }}>{t("quiz.analyzing")}</p>}
          {analysisQuery.data && (
            <div style={{ maxWidth: 520, margin: "8px auto 0", textAlign: "left" }}>
              {analysisQuery.data.analysis && (
                <div style={{ background: "var(--surface-soft)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-md)", marginBottom: 12 }}>
                  <div style={{ fontWeight: 700, marginBottom: 6 }}>{t("quiz.analysisTitle")}</div>
                  <MathText text={analysisQuery.data.analysis} style={{ display: "block", color: "var(--text-soft)", fontSize: 14 }} />
                </div>
              )}
              {analysisQuery.data.courses_to_review.length > 0 ? (
                <div style={{ display: "grid", gap: 10 }}>
                  <div style={{ fontWeight: 700 }}>{t("quiz.reviewTitle")}</div>
                  {analysisQuery.data.courses_to_review.map((course) => (
                    <div key={course.document_id} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-sm)", padding: "var(--space-md)" }}>
                      <div style={{ fontWeight: 600 }}>{course.title}</div>
                      <div style={{ color: "var(--muted)", fontSize: 13, margin: "4px 0 8px" }}>
                        <div>{t("quiz.course_missed", { missed: course.missed, answered: course.answered })}</div>
                        {course.chapters.length > 0 && (
                          <div>{t("quiz.course_chapters", { chapters: course.chapters.join(", ") })}</div>
                        )}
                      </div>
                      <Button size="sm" onClick={() => navigate(`/reader/${course.document_id}`)}>
                        {t("quiz.launchReading")}
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                // Pas de cours à proposer ne veut pas dire « aucune faiblesse » : les
                // questions manquées peuvent venir du catalogue, qui n'a pas de cours.
                score === data.length && <p style={{ color: "var(--success)", fontWeight: 600 }}>{t("quiz.noWeakness")}</p>
              )}
            </div>
          )}

          <div className="mt-5 flex flex-wrap justify-center gap-2.5">
            <Button variant="secondary" onClick={backToStart}>
              <ArrowLeft aria-hidden />
              {t("quiz.back")}
            </Button>
            <Button onClick={restart}>{t("quiz.restart")}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Tuile de métrique du bilan de fin de session (durée, questions, réussite). */
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

/** Champ « préciser » : un mot ou quelques mots dans la matière, Entrée pour lancer. */
function TopicInput({
  value,
  onChange,
  onSubmit,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
}) {
  const t = useT();
  return (
    // Même coque que la recherche de bibliothèque : le champ n'a pas de focus
    // propre, `focus-within` reporte l'anneau sur le conteneur.
    <div
      className="flex items-center gap-1.5 rounded-sm border border-border bg-background px-2.5 py-2
                 transition-[border-color,box-shadow] duration-fast ease-brand
                 focus-within:border-brand focus-within:ring-[3px] focus-within:ring-ring/50
                 hover:border-border-strong"
    >
      <Search className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <input
        id="quiz-topic"
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSubmit();
          if (e.key === "Escape") onChange("");
        }}
        className="min-w-0 flex-1 border-none bg-transparent font-[inherit] text-sm text-foreground outline-none placeholder:text-muted-light"
      />
      {value && (
        <button
          type="button"
          title={t("quiz.topic_clear")}
          aria-label={t("quiz.topic_clear")}
          onClick={() => onChange("")}
          className="flex shrink-0 rounded-full p-0.5 text-muted-foreground
                     transition-colors duration-fast ease-brand
                     hover:bg-accent hover:text-accent-foreground
                     focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}

/**
 * Nombre de questions exact : `−` / saisie / `+`, borné par le serveur.
 *
 * La frappe passe par un brouillon : borner à chaque touche rendrait « 25 »
 * impossible à taper (« 2 » serait aussitôt remonté au minimum). Une valeur
 * valide est transmise dès qu'elle l'est ; le reste est borné en quittant le
 * champ, ou avec Entrée, qui lance aussitôt la session avec la valeur arrêtée.
 */
function QuestionCountInput({
  value,
  min,
  max,
  onChange,
  onSubmit,
}: {
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
  onSubmit: (value: number) => void;
}) {
  const t = useT();
  // `null` = pas de saisie en cours : le champ affiche la valeur arrêtée.
  const [draft, setDraft] = useState<string | null>(null);
  const clamp = (n: number) => Math.max(min, Math.min(max, n));

  /** Arrête la saisie : brouillon borné (ou valeur précédente s'il est vide). */
  function settle(): number {
    const typed = draft === null || draft === "" ? value : clamp(Number(draft));
    setDraft(null);
    onChange(typed);
    return typed;
  }

  function edit(raw: string) {
    const digits = raw.replace(/\D/g, "");
    setDraft(digits);
    const n = Number(digits);
    if (digits !== "" && n >= min && n <= max) onChange(n);
  }

  function step(delta: number) {
    setDraft(null);
    onChange(clamp(value + delta));
  }

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="secondary"
        size="icon-sm"
        aria-label={t("quiz.length_less")}
        title={t("quiz.length_less")}
        disabled={value <= min}
        onClick={() => step(-1)}
      >
        <Minus aria-hidden />
      </Button>
      <input
        id="quiz-length"
        type="text"
        inputMode="numeric"
        value={draft ?? String(value)}
        onChange={(e) => edit(e.target.value)}
        onBlur={settle}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSubmit(settle());
          else if (e.key === "ArrowUp") {
            e.preventDefault();
            step(1);
          } else if (e.key === "ArrowDown") {
            e.preventDefault();
            step(-1);
          }
        }}
        className="h-8 w-14 rounded-sm border border-border bg-background text-center text-sm font-semibold tabular-nums
                   text-foreground outline-none transition-[border-color,box-shadow] duration-fast ease-brand
                   hover:border-border-strong focus:border-brand focus:ring-[3px] focus:ring-ring/50"
      />
      <Button
        variant="secondary"
        size="icon-sm"
        aria-label={t("quiz.length_more")}
        title={t("quiz.length_more")}
        disabled={value >= max}
        onClick={() => step(1)}
      >
        <Plus aria-hidden />
      </Button>
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  /** Champ natif à relier au libellé ; un Select Radix porte son `aria-label`. */
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {htmlFor ? (
        <label htmlFor={htmlFor} className="text-[13px] font-semibold">
          {label}
        </label>
      ) : (
        <span className="text-[13px] font-semibold">{label}</span>
      )}
      {children}
    </div>
  );
}

function QuestionCard({
  q,
  position,
  onAnswered,
  onDeferred,
  onNext,
}: {
  q: QuizQuestion;
  position: string;
  onAnswered: (outcome: QuizOutcome) => void;
  /** Réponse rédigée : corrigée en arrière-plan, verdict au bilan. */
  onDeferred: (written: string, responseTimeMs: number) => void;
  onNext: () => void;
}) {
  const t = useT();
  const [picked, setPicked] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<QuizEvaluation | null>(null);
  // Réponse rédigée que le serveur n'a pas pu corriger (LLM éteint) : l'apprenant
  // tranche lui-même plutôt que de voir la session s'arrêter là.
  const [selfGrading, setSelfGrading] = useState<string | null>(null);
  // Réponse rédigée envoyée à la correction différée : la réponse attendue
  // s'affiche tout de suite, le verdict de Clikoda au bilan.
  const [sent, setSent] = useState(false);
  const widget = answerWidget(q.question_type, q.choices);
  const settled = picked !== null || result !== null || sent;
  // Temps de réponse (attention) : de l'affichage de la question au geste qui y
  // répond. L'attente de la correction n'y entre pas — d'où le temps figé à la
  // soumission, que reprend une auto-évaluation arrivée après coup.
  const shownAt = useRef(0);
  const answeredIn = useRef(0);
  useEffect(() => {
    shownAt.current = Date.now();
  }, []);
  const elapsedMs = () => Math.max(0, Date.now() - shownAt.current);

  /** QCM : la comparaison est locale et immédiate — aucun aller-retour à attendre. */
  function pick(choice: string) {
    if (settled) return;
    setPicked(choice);
    const correct = choice.trim() === q.answer.trim();
    onAnswered({
      verdict: correct ? "correct" : "incorrect",
      score: correct ? 1 : 0,
      userAnswer: choice,
      graded: true,
      responseTimeMs: elapsedMs(),
    });
  }

  /** Réponse rédigée : la question suivante est tout de suite là, Clikoda corrige
   *  en arrière-plan. Une remise en ordre, elle, a un verdict objectif et
   *  immédiat : elle passe par le serveur sans attendre de modèle. */
  async function submit(answer: string) {
    const written = answer.trim();
    if (busy || settled || selfGrading !== null || !written) return;
    answeredIn.current = elapsedMs();
    if (widget === "text") {
      setSent(true);
      onDeferred(written, answeredIn.current);
      return;
    }
    setBusy(true);
    try {
      const evaluation = await api.quizEvaluate({
        question_id: q.id,
        question: q.question,
        user_answer: written,
        question_type: q.question_type,
        answer: q.answer,
        choices: q.choices,
      });
      if (evaluation.graded && evaluation.verdict) {
        setResult(evaluation);
        onAnswered({
          verdict: evaluation.verdict,
          score: evaluation.score,
          userAnswer: written,
          graded: true,
          responseTimeMs: answeredIn.current,
          signals: evaluation.signals ?? null,
        });
      } else setSelfGrading(written);
    } catch {
      setSelfGrading(written);
    } finally {
      setBusy(false);
    }
  }

  /** « Je ne sais pas » : la réponse attendue s'affiche, la question compte pour zéro. */
  function giveUp() {
    if (settled) return;
    setSelfGrading(null);
    setResult(localVerdict(q.answer, "incorrect"));
    onAnswered({ verdict: "incorrect", score: 0, userAnswer: "", graded: false, responseTimeMs: elapsedMs() });
  }

  function selfGrade(correct: boolean) {
    const written = selfGrading ?? "";
    setSelfGrading(null);
    const verdict: QuizVerdict = correct ? "correct" : "incorrect";
    setResult(localVerdict(q.answer, verdict));
    onAnswered({
      verdict,
      score: correct ? 1 : 0,
      userAnswer: written,
      graded: false,
      responseTimeMs: answeredIn.current,
    });
  }

  // Une liste de choix et une remise en ordre portent leur propre verdict (couleurs,
  // étapes marquées) : elles restent affichées. Le champ de rédaction, lui, cède la
  // place à la correction.
  const showInput = widget !== "text" || !(settled || selfGrading !== null);

  return (
    <div style={{ marginTop: "var(--space-lg)" }}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
        <span>{position} · {q.category}</span>
        <QuestionTypeBadge type={q.question_type} />
      </div>
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-sm)", padding: "var(--space-lg)" }}>
        <QuestionStem
          question={q.question}
          type={q.question_type}
          // La consigne du type n'a de sens que si l'on écrit sa réponse ; devant
          // une liste de choix, elle ne ferait que doubler l'évidence.
          showHint={widget !== "choices"}
          className="mb-4 [&>div:first-child]:text-lg"
        />

        {showInput && (
          <AnswerInput
            key={q.id}
            type={q.question_type}
            choices={q.choices}
            seed={q.id}
            draft={draft}
            setDraft={setDraft}
            busy={busy}
            picked={picked}
            expectedChoice={q.answer}
            correctOrder={result && widget === "ordering" ? (q.choices ?? []) : null}
            onSubmit={widget === "choices" ? pick : submit}
          />
        )}

        {busy && <p className="mt-2 text-[13px] text-muted-foreground">{t("quiz.checking")}</p>}

        {/* Sortie de secours d'une question à rédiger : voir la réponse sans tricher
            sur le score. Devant une liste de choix, il suffit de cliquer. */}
        {widget !== "choices" && !busy && !settled && selfGrading === null && (
          <Button variant="ghost" size="sm" onClick={giveUp} className="mt-2 text-muted-foreground">
            <Eye className="size-4" aria-hidden />
            {t("quiz.reveal")}
          </Button>
        )}

        {selfGrading !== null && (
          <div className="mt-3 grid gap-2">
            <p className="m-0 text-[13px] text-muted-foreground">{t("quiz.selfGrade")}</p>
            <div style={{ display: "flex", gap: 10 }}>
              <Button
                variant="secondary"
                onClick={() => selfGrade(true)}
                className="border-success/50 text-success hover:border-success hover:bg-success-soft hover:text-success"
              >
                <Check className="size-4" aria-hidden />
                {t("quiz.knew")}
              </Button>
              <Button
                variant="secondary"
                onClick={() => selfGrade(false)}
                className="border-danger/50 text-danger hover:border-danger hover:bg-danger-soft hover:text-danger"
              >
                <X className="size-4" aria-hidden />
                {t("quiz.didntKnow")}
              </Button>
            </div>
          </div>
        )}

        {result && <Correction result={result} />}
        {sent && (
          <div className="mt-4 grid gap-2">
            <p className="m-0 text-[13px] text-muted-foreground">{t("quiz.deferred_note")}</p>
            {q.answer && <ExpectedAnswer text={q.answer} />}
          </div>
        )}

        {settled && (
          <Button onClick={onNext} className="mt-4.5">
            {t("quiz.next")}
            <ArrowRight className="size-4" aria-hidden />
          </Button>
        )}
      </div>
    </div>
  );
}

/** Correction affichée sous la question : verdict, retour de Clikoda, réponse attendue. */
function Correction({ result }: { result: QuizEvaluation }) {
  return (
    <div className="mt-4 grid gap-2">
      <VerdictBadge verdict={result.verdict} />
      {result.feedback && <MathText text={result.feedback} className="block text-[13px] text-[var(--text-soft)]" />}
      {result.completion && <MathText text={result.completion} className="block text-[13px] text-[var(--text-soft)]" />}
      {result.hint && (
        <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Lightbulb className="mt-px size-3.5 shrink-0 text-warning" aria-hidden />
          <MathText text={result.hint} />
        </div>
      )}
      {result.expected_answer && <ExpectedAnswer text={result.expected_answer} />}
    </div>
  );
}

function ExpectedAnswer({ text }: { text: string }) {
  const t = useT();
  return (
    <div className="grid gap-1">
      <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
        {t("quiz.expected")}
      </span>
      <div
        style={{ background: "var(--accent-soft)", borderRadius: "var(--radius-sm)", padding: 12, color: "var(--accent-ink)" }}
        dangerouslySetInnerHTML={{ __html: renderMathToHtml(text) }}
      />
    </div>
  );
}

/**
 * Bilan des réponses rédigées : la correction de Clikoda, arrivée pendant la
 * séance ou à sa fin, et celles qu'il n'a pas pu rendre, à trancher soi-même.
 */
function DeferredCorrections({
  history,
  corrections,
  toSelfGrade,
  expected,
  onSelfGrade,
}: {
  history: QuizAnswerRecord[];
  corrections: Record<number, QuizEvaluation>;
  toSelfGrade: number[];
  expected: Map<number, string>;
  onSelfGrade: (rank: number, knew: boolean) => void;
}) {
  const t = useT();
  const ranks = [...Object.keys(corrections).map(Number), ...toSelfGrade].sort((a, b) => a - b);
  if (ranks.length === 0) return null;
  return (
    <div style={{ maxWidth: 520, margin: "8px auto 16px", display: "grid", gap: 10, textAlign: "left" }}>
      <div style={{ fontWeight: 700 }}>{t("quiz.corrections_title")}</div>
      {ranks.map((rank) => {
        const entry = history[rank];
        const correction = corrections[rank];
        if (!entry) return null;
        return (
          <div
            key={rank}
            data-testid="deferred-correction"
            style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-sm)", padding: "var(--space-md)" }}
          >
            <MathText text={entry.question} className="block text-sm font-semibold" />
            <div className="mt-2 text-[13px] text-[var(--text-soft)]">
              <span className="font-semibold">{t("quiz.your_answer")} : </span>
              {entry.user_answer}
            </div>
            {correction ? (
              <Correction result={correction} />
            ) : (
              <div className="mt-3 grid gap-2">
                {expected.get(rank) && <ExpectedAnswer text={expected.get(rank) ?? ""} />}
                <p className="m-0 text-[13px] text-muted-foreground">{t("quiz.selfGrade")}</p>
                <div style={{ display: "flex", gap: 10 }}>
                  <Button variant="secondary" onClick={() => onSelfGrade(rank, true)}>
                    <Check className="size-4" aria-hidden />
                    {t("quiz.knew")}
                  </Button>
                  <Button variant="secondary" onClick={() => onSelfGrade(rank, false)}>
                    <X className="size-4" aria-hidden />
                    {t("quiz.didntKnow")}
                  </Button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Verdict rendu sans le serveur — abandon (« je ne sais pas ») ou auto-évaluation
 * hors ligne. Seule la réponse attendue est à montrer : il n'y a pas de retour
 * rédigé à inventer.
 */
function localVerdict(expected: string, verdict: QuizVerdict): QuizEvaluation {
  return {
    verdict,
    score: verdict === "correct" ? 1 : 0,
    feedback: "",
    hint: "",
    completion: "",
    expected_answer: expected,
    graded: false,
    signals: null,
  };
}
