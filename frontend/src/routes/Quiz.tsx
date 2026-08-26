import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { QuizAnswerRecord, QuizEvaluation, QuizQuestion, QuizVerdict } from "../api/types";
import { ArrowRight, Check, Eye, Lightbulb, Search, X } from "lucide-react";

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
import { formatDuration } from "../features/session/duration";
import { useT } from "../i18n";

// Code de matière (tel que stocké en base) -> clé i18n du libellé affiché.
const SUBJ_LABEL_KEY: Record<string, string> = {
  "mathématiques": "subj.math",
  "physique": "subj.physics",
  "chimie": "subj.chemistry",
  "biologie": "subj.biology",
  "sciences": "subj.science",
  "informatique": "subj.cs",
  "technologie": "subj.technology",
  "histoire": "subj.history",
  "géographie": "subj.geography",
  "français": "subj.french",
  "philosophie": "subj.philosophy",
  "littérature": "subj.literature",
  "langues": "subj.languages",
  "économie": "subj.economics",
  "sciences-sociales": "subj.social",
  "droit": "subj.law",
  "gestion": "subj.management",
  "psychologie": "subj.psychology",
  "sociologie": "subj.sociology",
  "arts": "subj.arts",
  "musique": "subj.music",
  "médecine": "subj.medicine",
  "sport": "subj.sport",
  "religion": "subj.religion",
  "culture": "subj.culture",
};

/**
 * Ce qu'une question rapporte à la session. Le verdict vient du serveur pour une
 * réponse rédigée ou une remise en ordre, de la comparaison locale pour un QCM ;
 * `score` en est le poids (1 / 0,5 / 0), un « partiel » valant un demi-point.
 */
type QuizOutcome = { verdict: QuizVerdict; score: number; userAnswer: string };

/** Un demi-point doit rester lisible dans le bilan : « 3,5 » et pas « 3.5000 ». */
function formatScore(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function Quiz() {
  const t = useT();
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const [subject, setSubject] = useState("");
  // Sujet libre : `topic` suit la frappe, `askedTopic` est celui de la session
  // en cours (figé au lancement, pour que le message d'absence de résultat parle
  // du sujet réellement joué et non de ce que l'on est en train de retaper).
  const [topic, setTopic] = useState("");
  const [askedTopic, setAskedTopic] = useState("");
  const [length, setLength] = useState<number | null>(null);
  const [runId, setRunId] = useState(0);
  const [started, setStarted] = useState(false);

  const subjectsQuery = useQuery({
    queryKey: ["quiz", "subjects"],
    queryFn: () => api.quizSubjects(),
  });

  // Longueurs proposées : c'est le serveur qui les déclare (config/settings.py),
  // l'UI ne fait que les afficher — et se tait tant qu'elle ne les a pas.
  const optionsQuery = useQuery({
    queryKey: ["quiz", "options"],
    queryFn: () => api.quizOptions(),
    staleTime: Infinity,
  });
  const lengths = optionsQuery.data?.lengths ?? [];
  const askedLength = length ?? optionsQuery.data?.default_length;

  // La génération LLM (un seul appel batch) n'est déclenchée qu'après un clic
  // explicite sur « Lancer le quiz » : on laisse le temps de régler la session.
  const { data, isFetching, isError } = useQuery({
    queryKey: ["quiz", "questions", subject, askedTopic, askedLength, runId],
    queryFn: () => api.quizQuestions(askedLength, subject || undefined, askedTopic || undefined),
    enabled: started,
  });

  const [index, setIndex] = useState(0);
  const [score, setScore] = useState(0);
  const [done, setDone] = useState(false);
  const [byCat, setByCat] = useState<Record<string, { correct: number; total: number }>>({});
  const [history, setHistory] = useState<QuizAnswerRecord[]>([]);
  const [durationS, setDurationS] = useState(0);
  const startedAt = useRef(0);
  // Une session ne se clôt qu'une fois : garde-fou contre un double `/finalize`
  // (qui compterait la session deux fois dans le profil long terme).
  const finalized = useRef(false);

  const analysisQuery = useQuery({
    queryKey: ["quiz", "analysis", subject, askedTopic, runId],
    queryFn: () => api.quizAnalysis(history),
    enabled: done && history.length > 0,
  });

  const subjectOptions = useMemo(() => {
    const avail = subjectsQuery.data ?? [];
    const total = avail.reduce((s, x) => s + x.count, 0);
    return [
      { code: "", label: `${t("subj.all")} (${total})` },
      ...avail.map((x) => {
        const key = SUBJ_LABEL_KEY[x.subject];
        const name = key ? t(key) : x.subject;
        return { code: x.subject, label: `${name} (${x.count})` };
      }),
    ];
  }, [subjectsQuery.data, t]);

  function resetState() {
    setIndex(0);
    setScore(0);
    setDone(false);
    setByCat({});
    setHistory([]);
    setDurationS(0);
    finalized.current = false;
  }

  function answered(q: QuizQuestion, outcome: QuizOutcome) {
    setScore((s) => s + outcome.score);
    const cat = q.category || "autre";
    setByCat((b) => ({ ...b, [cat]: { correct: (b[cat]?.correct ?? 0) + outcome.score, total: (b[cat]?.total ?? 0) + 1 } }));
    setHistory((h) => [
      ...h,
      {
        question: q.question,
        user_answer: outcome.userAnswer,
        verdict: outcome.verdict,
        score: outcome.score,
        category: cat,
        source: q.source,
        document: q.document ?? null,
        document_id: q.document_id ?? null,
        chapter_title: q.chapter_title ?? null,
      },
    ]);
    // Le verdict accompagne le booléen : la rétention du profil distingue le
    // « partiel », que `correct` seul écrasait en « incorrect ».
    void api.submitQuizAnswer(q.category, outcome.verdict === "correct", outcome.verdict);
  }

  // Clôture métacognitive de la session : même chemin serveur qu'une fin de lecture
  // (`/api/quiz/finalize` → `nudge_metacog_profile`), pour qu'un quiz pèse sur le profil
  // long terme. Sans questions de réflexion — le bilan est une page, plus un rituel.
  // Déclenché depuis le handler et non un effet : l'app est montée en StrictMode.
  function finalize(total: number, elapsed: number) {
    if (finalized.current) return;
    finalized.current = true;
    void api
      .quizFinalize({
        responses: [],
        score: total > 0 ? Math.round((100 * score) / total) : 0,
        questions_answered: total,
        correct: Math.round(score),
        duration_s: elapsed,
        subject: subject || null,
        topic: askedTopic || null,
      })
      .catch(() => {
        /* la clôture ne doit jamais abîmer l'affichage du bilan */
      });
  }

  function next(total: number) {
    if (index + 1 >= total) {
      const elapsed = Math.max(0, Math.round((Date.now() - startedAt.current) / 1000));
      setDurationS(elapsed);
      setDone(true);
      finalize(total, elapsed);
    } else setIndex((i) => i + 1);
  }

  function changeSubject(code: string) {
    setSubject(code);
    resetState();
    setStarted(false);
  }

  function startQuiz() {
    resetState();
    setAskedTopic(topic.trim());
    setRunId((r) => r + 1);
    startedAt.current = Date.now();
    setStarted(true);
  }

  function restart() {
    resetState();
    setStarted(false);
  }

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "var(--space-xl)" }}>
      <h1 style={{ fontFamily: "var(--font-title)", fontSize: 32, margin: "0 0 4px" }}>{t("quiz.title")}</h1>
      <p style={{ color: "var(--muted)", marginTop: 0 }}>{t("quiz.subtitle")}</p>

      {!started && !done && (
        <div className="mt-6 rounded-lg border border-border bg-surface p-5 shadow-e1">
          <label className="text-[13px] font-semibold" htmlFor="quiz-topic">
            {t("quiz.topic_label")}
          </label>
          <TopicInput value={topic} onChange={setTopic} onSubmit={startQuiz} />

          <div className="mt-4 flex flex-wrap items-end gap-4">
            <Field label={t("quiz.subject_label")}>
              <Select value={subject} onValueChange={changeSubject}>
                <SelectTrigger className="w-[240px]" aria-label={t("quiz.subject_label")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {subjectOptions.map((option) => (
                    <SelectItem key={option.code} value={option.code}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            {lengths.length > 0 && askedLength != null && (
              <Field label={t("quiz.length_label")}>
                <Select value={String(askedLength)} onValueChange={(v) => setLength(Number(v))}>
                  <SelectTrigger className="w-[160px]" aria-label={t("quiz.length_label")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {lengths.map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {t("quiz.length_option", { n })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            )}
          </div>

          <p style={{ color: "var(--muted)", margin: "16px 0 12px" }}>{t("quiz.pickThemeHint")}</p>
          <Button size="lg" onClick={startQuiz}>
            {t("quiz.start")}
          </Button>
        </div>
      )}

      {isFetching && <p style={{ color: "var(--muted)" }}>{t("quiz.generating")}</p>}
      {isError && !isFetching && <p style={{ color: "var(--danger)" }}>{t("quiz.error")}</p>}
      {!isFetching && data && data.length === 0 && (
        // Le panneau de réglages est masqué pendant une session : sans ce retour,
        // un sujet sans résultat laissait l'écran dans une impasse.
        <div style={{ marginTop: 32 }}>
          <p style={{ color: "var(--muted)", fontStyle: "italic" }}>
            {askedTopic ? t("quiz.noneForTopic", { topic: askedTopic }) : t("quiz.none")}
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
                <span style={{ color: "var(--text-soft)" }}>{cat}</span>
                <span style={{ fontWeight: 700, color: r.correct === r.total ? "var(--success)" : "var(--warning)" }}>
                  {formatScore(r.correct)}/{r.total}
                </span>
              </div>
            ))}
          </div>

          {analysisQuery.isFetching && <p style={{ color: "var(--muted)" }}>{t("quiz.analyzing")}</p>}
          {analysisQuery.data && (
            <div style={{ maxWidth: 520, margin: "8px auto 0", textAlign: "left" }}>
              {analysisQuery.data.analysis && (
                <div style={{ background: "var(--surface-soft)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-md)", marginBottom: 12 }}>
                  <div style={{ fontWeight: 700, marginBottom: 6 }}>{t("quiz.analysisTitle")}</div>
                  <div style={{ color: "var(--text-soft)", fontSize: 14 }}>{analysisQuery.data.analysis}</div>
                </div>
              )}
              {analysisQuery.data.courses_to_review.length > 0 ? (
                <div style={{ display: "grid", gap: 10 }}>
                  <div style={{ fontWeight: 700 }}>{t("quiz.reviewTitle")}</div>
                  {analysisQuery.data.courses_to_review.map((course, i) => (
                    <div key={`${course.title}-${i}`} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-sm)", padding: "var(--space-md)" }}>
                      <div style={{ fontWeight: 600 }}>{course.title}</div>
                      {course.reason && <div style={{ color: "var(--muted)", fontSize: 13, margin: "4px 0 8px" }}>{course.reason}</div>}
                      {course.document_id != null && (
                        <Button size="sm" onClick={() => navigate(`/reader/${course.document_id}`)}>
                          {t("quiz.launchReading")}
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                analysisQuery.data.analysis && <p style={{ color: "var(--success)", fontWeight: 600 }}>{t("quiz.noWeakness")}</p>
              )}
            </div>
          )}

          <div className="mt-5 flex flex-wrap justify-center gap-2.5">
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

/** Champ « sujet de la session » : un mot ou quelques mots, Entrée pour lancer. */
function TopicInput({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const t = useT();
  return (
    // Même coque que la recherche de bibliothèque : le champ n'a pas de focus
    // propre, `focus-within` reporte l'anneau sur le conteneur.
    <div
      className="mt-1.5 flex items-center gap-1.5 rounded-sm border border-border bg-background px-2.5 py-2
                 transition-[border-color,box-shadow] duration-fast ease-brand
                 focus-within:border-brand focus-within:ring-[3px] focus-within:ring-ring/50
                 hover:border-border-strong"
    >
      <Search className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <input
        id="quiz-topic"
        type="text"
        value={value}
        placeholder={t("quiz.topic_placeholder")}
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[13px] font-semibold">{label}</span>
      {children}
    </div>
  );
}

function QuestionCard({
  q,
  position,
  onAnswered,
  onNext,
}: {
  q: QuizQuestion;
  position: string;
  onAnswered: (outcome: QuizOutcome) => void;
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
  const widget = answerWidget(q.question_type, q.choices);
  const settled = picked !== null || result !== null;

  /** QCM : la comparaison est locale et immédiate — aucun aller-retour à attendre. */
  function pick(choice: string) {
    if (settled) return;
    setPicked(choice);
    const correct = choice.trim() === q.answer.trim();
    onAnswered({ verdict: correct ? "correct" : "incorrect", score: correct ? 1 : 0, userAnswer: choice });
  }

  /** Réponse rédigée ou remise en ordre : corrigée par le serveur, comme en lecture. */
  async function submit(answer: string) {
    const written = answer.trim();
    if (busy || settled || selfGrading !== null || !written) return;
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
        onAnswered({ verdict: evaluation.verdict, score: evaluation.score, userAnswer: written });
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
    onAnswered({ verdict: "incorrect", score: 0, userAnswer: "" });
  }

  function selfGrade(correct: boolean) {
    const written = selfGrading ?? "";
    setSelfGrading(null);
    const verdict: QuizVerdict = correct ? "correct" : "incorrect";
    setResult(localVerdict(q.answer, verdict));
    onAnswered({ verdict, score: correct ? 1 : 0, userAnswer: written });
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

/** Correction affichée sous la question : verdict, retour de Gemma, réponse attendue. */
function Correction({ result }: { result: QuizEvaluation }) {
  const t = useT();
  return (
    <div className="mt-4 grid gap-2">
      <VerdictBadge verdict={result.verdict} />
      {result.feedback && <div className="text-[13px] text-[var(--text-soft)]">{result.feedback}</div>}
      {result.completion && <div className="text-[13px] text-[var(--text-soft)]">{result.completion}</div>}
      {result.hint && (
        <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Lightbulb className="mt-px size-3.5 shrink-0 text-warning" aria-hidden />
          {result.hint}
        </div>
      )}
      {result.expected_answer && (
        <div className="grid gap-1">
          <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
            {t("quiz.expected")}
          </span>
          <div
            style={{ background: "var(--accent-soft)", borderRadius: "var(--radius-sm)", padding: 12, color: "var(--accent-hover)" }}
            dangerouslySetInnerHTML={{ __html: renderMathToHtml(result.expected_answer) }}
          />
        </div>
      )}
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
  };
}
