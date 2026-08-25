import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { QuizAnswerRecord, QuizQuestion } from "../api/types";
import { ArrowRight, Check, Eye, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { renderMathToHtml } from "../features/reader/renderMath";
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
  const [subject, setSubject] = useState("");
  const [runId, setRunId] = useState(0);
  const [started, setStarted] = useState(false);

  const subjectsQuery = useQuery({
    queryKey: ["quiz", "subjects"],
    queryFn: () => api.quizSubjects(),
  });

  // La génération LLM (un seul appel batch) n'est déclenchée qu'après un clic
  // explicite sur « Lancer le quiz » : on laisse le temps de choisir la matière.
  const { data, isFetching, isError } = useQuery({
    queryKey: ["quiz", "questions", subject, runId],
    queryFn: () => api.quizQuestions(10, subject || undefined),
    enabled: started,
  });

  const [index, setIndex] = useState(0);
  const [score, setScore] = useState(0);
  const [done, setDone] = useState(false);
  const [byCat, setByCat] = useState<Record<string, { correct: number; total: number }>>({});
  const [history, setHistory] = useState<QuizAnswerRecord[]>([]);

  const analysisQuery = useQuery({
    queryKey: ["quiz", "analysis", subject, runId],
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

  function next(total: number) {
    if (index + 1 >= total) setDone(true);
    else setIndex((i) => i + 1);
  }

  function changeSubject(code: string) {
    setSubject(code);
    resetState();
    setStarted(false);
  }

  function startQuiz() {
    resetState();
    setRunId((r) => r + 1);
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

      <Select value={subject} onValueChange={changeSubject}>
        <SelectTrigger className="mt-2 w-[260px]" aria-label={t("quiz.subject_label")}>
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

      {!started && !done && (
        <div style={{ marginTop: 28 }}>
          <p style={{ color: "var(--muted)", marginBottom: 12 }}>{t("quiz.pickThemeHint")}</p>
          <Button size="lg" onClick={startQuiz}>
            {t("quiz.start")}
          </Button>
        </div>
      )}

      {isFetching && <p style={{ color: "var(--muted)" }}>{t("quiz.generating")}</p>}
      {isError && !isFetching && <p style={{ color: "var(--danger)" }}>{t("quiz.error")}</p>}
      {!isFetching && data && data.length === 0 && <div style={{ marginTop: 32, color: "var(--muted)", fontStyle: "italic" }}>{t("quiz.none")}</div>}

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

          <button onClick={restart} style={{ marginTop: 20, border: "none", background: "var(--accent)", color: "#fff", borderRadius: "var(--radius-sm)", padding: "10px 22px", fontWeight: 600, cursor: "pointer" }}>
            {t("quiz.restart")}
          </button>
        </div>
      )}
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
  const isMcq = Array.isArray(q.choices) && q.choices.length > 0;

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
      <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 8 }}>{position} · {q.category}</div>
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-sm)", padding: "var(--space-lg)" }}>
        <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }} dangerouslySetInnerHTML={{ __html: renderMathToHtml(q.question) }} />

        {isMcq ? (
          <div style={{ display: "grid", gap: 8 }}>
            {q.choices!.map((choice) => {
              const isCorrect = choice.trim() === q.answer.trim();
              const isPicked = picked === choice;
              let bg = "var(--surface-soft)";
              let border = "var(--border)";
              if (picked !== null) {
                if (isCorrect) {
                  bg = "var(--success-soft)";
                  border = "var(--success)";
                } else if (isPicked) {
                  bg = "var(--danger-soft)";
                  border = "var(--danger)";
                }
              }
              return (
                <button
                  key={choice}
                  onClick={() => pick(choice)}
                  disabled={picked !== null}
                  // Un choix non repondu doit reagir au survol : sans cela, rien
                  // ne signale qu'il est cliquable.
                  className="flex items-center justify-between gap-3 rounded-sm border p-[10px_14px] text-left text-sm text-foreground
                             transition-[background-color,border-color,transform] duration-fast ease-brand
                             enabled:cursor-pointer enabled:hover:border-border-strong enabled:active:scale-[0.995]
                             focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none
                             disabled:cursor-default"
                  style={{ background: bg, borderColor: border }}
                >
                  <span dangerouslySetInnerHTML={{ __html: renderMathToHtml(choice) }} />
                  {/* La bonne et la mauvaise reponse ne se distinguaient QUE par
                      la couleur : illisible pour un daltonien. L'icone double
                      l'information. */}
                  {picked !== null && isCorrect && (
                    <Check className="size-4 shrink-0 text-success" aria-label={t("verdict.correct")} />
                  )}
                  {picked !== null && isPicked && !isCorrect && (
                    <X className="size-4 shrink-0 text-danger" aria-label={t("verdict.incorrect")} />
                  )}
                </button>
              );
            })}
          </div>
        ) : (
          <div>
            {revealed && <div style={{ background: "var(--accent-soft)", borderRadius: "var(--radius-sm)", padding: 12, color: "var(--accent-hover)" }} dangerouslySetInnerHTML={{ __html: renderMathToHtml(q.answer) }} />}
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
        )}

        {(picked !== null || revealed) && (
          <Button onClick={onNext} className="mt-4.5">
            {t("quiz.next")}
            <ArrowRight className="size-4" aria-hidden />
          </Button>
        )}
      </div>
    </div>
  );
}
