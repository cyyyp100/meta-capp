import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { QuizAnswerRecord, QuizQuestion } from "../api/types";
import { ArrowRight, Check, Eye, Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { AnswerInput, serializeOrder } from "../features/questions/AnswerInput";
import { QuestionStem } from "../features/questions/QuestionStem";
import { QuestionTypeBadge } from "../features/questions/QuestionTypeBadge";
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

  function answered(q: QuizQuestion, correct: boolean, userAnswer: string) {
    if (correct) setScore((s) => s + 1);
    const cat = q.category || "autre";
    setByCat((b) => ({ ...b, [cat]: { correct: (b[cat]?.correct ?? 0) + (correct ? 1 : 0), total: (b[cat]?.total ?? 0) + 1 } }));
    setHistory((h) => [
      ...h,
      {
        question: q.question,
        user_answer: userAnswer,
        verdict: correct ? "correct" : "incorrect",
        score: correct ? 1.0 : 0.0,
        category: cat,
        source: q.source,
        document: q.document ?? null,
        document_id: q.document_id ?? null,
        chapter_title: q.chapter_title ?? null,
      },
    ]);
    void api.submitQuizAnswer(q.category, correct);
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
        correct: score,
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
          onAnswered={(correct, userAnswer) => answered(data[index], correct, userAnswer)}
          onNext={() => next(data.length)}
        />
      )}

      {!isFetching && data && done && (
        <div style={{ marginTop: 32, textAlign: "center" }}>
          <div style={{ fontSize: 48, fontWeight: 700 }}>{score} / {data.length}</div>
          <p style={{ color: "var(--muted)" }}>{t("quiz.done")}</p>

          <div className="mx-auto my-4.5 grid max-w-[360px] grid-cols-3 gap-3">
            {[
              { label: t("exit.duration"), value: formatDuration(durationS) },
              { label: t("exit.questions"), value: `${score} / ${data.length}` },
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
                  {r.correct}/{r.total}
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
  onAnswered: (correct: boolean, userAnswer: string) => void;
  onNext: () => void;
}) {
  const t = useT();
  const [picked, setPicked] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  // Ordre validé : conservé pour afficher l'ordre attendu ligne par ligne.
  const [orderDone, setOrderDone] = useState(false);
  const widget = answerWidget(q.question_type, q.choices);
  const answered = picked !== null || revealed || orderDone;

  /** Une remise en ordre se corrige sans LLM : `choices` EST la bonne séquence. */
  function submitOrder(answer: string) {
    if (orderDone) return;
    setOrderDone(true);
    onAnswered(answer === serializeOrder(q.choices ?? []), answer);
  }

  function pick(choice: string) {
    if (picked !== null) return;
    setPicked(choice);
    onAnswered(choice.trim() === q.answer.trim(), choice);
  }

  function selfGrade(correct: boolean) {
    setRevealed(true);
    onAnswered(correct, correct ? q.answer : "");
  }

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

        <AnswerInput
          key={q.id}
          type={q.question_type}
          choices={q.choices}
          seed={q.id}
          picked={picked}
          expectedChoice={q.answer}
          correctOrder={orderDone ? (q.choices ?? []) : null}
          onSubmit={widget === "ordering" ? submitOrder : pick}
          textFallback={
            <div>
              {revealed && (
                <div
                  style={{ background: "var(--accent-soft)", borderRadius: "var(--radius-sm)", padding: 12, color: "var(--accent-hover)" }}
                  dangerouslySetInnerHTML={{ __html: renderMathToHtml(q.answer) }}
                />
              )}
              {!revealed && (
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
                    <Eye className="size-4" aria-hidden />
                    {t("quiz.reveal")}
                  </Button>
                </div>
              )}
            </div>
          }
        />

        {answered && (
          <Button onClick={onNext} className="mt-4.5">
            {t("quiz.next")}
            <ArrowRight className="size-4" aria-hidden />
          </Button>
        )}
      </div>
    </div>
  );
}
