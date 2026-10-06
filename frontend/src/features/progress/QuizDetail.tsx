// QuizDetail.tsx — Le détail d'une séance de quiz dans « Ma progression ».
//
// Le tronc commun (courbe des jauges, mouvements du profil) et ce qui n'appartient
// qu'au quiz : le cadre choisi au lancement, l'analyse de Clikoda et les cours à
// renforcer tels que le bilan les a montrés, les points par matière, et chaque
// réponse donnée — la question, ce qu'on a répondu, le verdict.
import { BookOpen } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { QuizPlayedAnswer, QuizProgress } from "@/api/client";
import { Button } from "@/components/ui/button";

import { useT } from "../../i18n";
import { QuestionTypeBadge } from "../questions/QuestionTypeBadge";
import { VerdictBadge } from "../questions/VerdictBadge";
import { renderMathToHtml } from "../reader/renderMath";
import { formatDuration } from "../session/duration";
import { subjectName } from "../stats/labels";
import {
  AnalysisBlock,
  Bar,
  Block,
  DetailHeader,
  formatPoints,
  GaugesBlock,
  Metric,
  Metrics,
  ProfileChangesBlock,
  ReflectionsBlock,
} from "./blocks";
import { quizName } from "./names";

export function QuizDetail({ data }: { data: QuizProgress }) {
  const t = useT();
  const navigate = useNavigate();
  const { metrics, quiz } = data;

  return (
    <div className="flex flex-col gap-5">
      <DetailHeader title={quizName(t, quiz)} startedAt={data.started_at} completed={data.completed} />

      <Block title={t("progress.metrics")}>
        <Metrics>
          <Metric label={t("exit.duration")} value={formatDuration(metrics.duration_s)} />
          <Metric
            label={t("exit.questions")}
            value={`${formatPoints(metrics.points)} / ${metrics.questions_answered}`}
          />
          <Metric label={t("exit.success")} value={`${metrics.success_rate} %`} />
        </Metrics>
      </Block>

      <GaugesBlock gauges={data.gauges} />
      <ProfileChangesBlock changes={data.profile_changes} />

      <AnalysisBlock analysis={data.analysis}>
        {quiz.courses_to_review.length > 0 && (
          <div className={data.analysis ? "mt-4" : undefined}>
            <p className="m-0 mb-2 text-[13px] font-semibold">{t("quiz.reviewTitle")}</p>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {quiz.courses_to_review.map((course) => (
                <li
                  key={course.document_id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-sm bg-surface-soft px-3 py-2.5"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{course.title}</span>
                    <span className="block text-[12px] text-muted-foreground">
                      {t("quiz.course_missed", { missed: course.missed, answered: course.answered })}
                      {course.chapters.length > 0 &&
                        ` · ${t("quiz.course_chapters", { chapters: course.chapters.join(", ") })}`}
                    </span>
                  </span>
                  <Button size="sm" variant="secondary" onClick={() => navigate(`/reader/${course.document_id}`)}>
                    <BookOpen aria-hidden />
                    {t("quiz.launchReading")}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </AnalysisBlock>

      {/* Une seule matière : la tuile « Questions » dit déjà tout. */}
      {quiz.by_category.length > 1 && (
        <Block title={t("progress.by_category")}>
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
            {quiz.by_category.map((entry) => (
              <li key={entry.category} className="flex items-center gap-3">
                <span className="w-36 shrink-0 truncate text-[12px] text-muted-foreground">
                  {subjectName(t, entry.category)}
                </span>
                <Bar
                  ratio={entry.total ? entry.points / entry.total : 0}
                  tone={entry.points === entry.total ? "bg-success" : "bg-brand"}
                />
                <span className="w-14 shrink-0 text-right text-[12px] tabular-nums text-muted-foreground">
                  {formatPoints(entry.points)}/{entry.total}
                </span>
              </li>
            ))}
          </ul>
        </Block>
      )}

      <Block title={t("progress.answers")}>
        <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
          {quiz.answers.map((answer) => (
            <li key={answer.position}>
              <AnswerRow answer={answer} />
            </li>
          ))}
        </ol>
      </Block>

      <ReflectionsBlock reflections={data.reflections} empty={null} />
    </div>
  );
}

function AnswerRow({ answer }: { answer: QuizPlayedAnswer }) {
  const t = useT();
  return (
    <div className="rounded-sm bg-surface-soft px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
        <span className="font-semibold tabular-nums">{t("progress.point_question", { n: answer.position + 1 })}</span>
        <QuestionTypeBadge type={answer.question_type} />
        {answer.category && <span>{subjectName(t, answer.category)}</span>}
        {answer.response_time_ms != null && (
          <span className="tabular-nums">{t("progress.seconds", { n: Math.round(answer.response_time_ms / 1000) })}</span>
        )}
        {!answer.graded && <span>{t("progress.self_graded")}</span>}
        <span className="ml-auto">
          <VerdictBadge verdict={answer.verdict} />
        </span>
      </div>
      <p
        className="mt-2 mb-0 text-sm font-semibold"
        dangerouslySetInnerHTML={{ __html: renderMathToHtml(answer.question) }}
      />
      {answer.user_answer ? (
        <p className="mt-1.5 mb-0 border-l-2 border-border-strong pl-3 text-sm text-text-soft">
          <span className="sr-only">{t("progress.your_answer")} : </span>
          <span dangerouslySetInnerHTML={{ __html: renderMathToHtml(answer.user_answer) }} />
        </p>
      ) : (
        <p className="mt-1.5 mb-0 text-sm text-muted-foreground italic">{t("progress.no_answer")}</p>
      )}
      {answer.document_title && (
        <p className="mt-1.5 mb-0 text-[12px] text-muted-foreground">
          {answer.document_title}
          {answer.chapter_title ? ` · ${answer.chapter_title}` : ""}
        </p>
      )}
    </div>
  );
}
