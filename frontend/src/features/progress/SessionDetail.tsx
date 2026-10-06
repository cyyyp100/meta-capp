// SessionDetail.tsx — Ce qu'une séance a produit, selon sa catégorie.
//
// Trois catégories, chacune avec ses particularités — une lecture dit où l'on a
// ralenti, un quiz les réponses données, une séance de langue ce qu'elle a fait
// gagner — et un tronc commun, dans cet ordre :
//   1. les courbes — comment la séance s'est déroulée, mesure par mesure ;
//   2. les mouvements de profil — ce que ça a changé (`value_before` →
//      `value_after` sont déjà stockés par critère, il n'y a rien à recalculer) ;
//   3. MES MOTS, relus tels quels.
//
// C'est le troisième qui crée l'attachement, et c'est le seul qu'aucun autre
// outil ne peut restituer : ni ChatGPT (il n'observe pas la lecture dans la
// durée), ni Anki (il modélise le rappel, pas la compréhension).
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { ProgressKind, SessionPause } from "@/api/client";

import { useT } from "../../i18n";
import { formatDuration } from "../session/duration";
import {
  Bar,
  Block,
  DetailHeader,
  GaugesBlock,
  Metric,
  Metrics,
  ProfileChangesBlock,
  ReflectionsBlock,
} from "./blocks";
import { LangDetail } from "./LangDetail";
import { sessionName } from "./names";
import { QuizDetail } from "./QuizDetail";

export function SessionDetail({ kind, sessionId }: { kind: ProgressKind; sessionId: number }) {
  return kind === "reading" ? <ReadingDetail sessionId={sessionId} /> : <PracticeDetail sessionId={sessionId} />;
}

function ReadingDetail({ sessionId }: { sessionId: number }) {
  const t = useT();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["progress", "session", sessionId],
    queryFn: () => api.progressSession(sessionId),
  });

  if (isLoading) return <p className="text-muted-foreground">{t("progress.loading")}</p>;
  if (isError || !data) return <p className="text-danger">{t("progress.error")}</p>;

  return (
    <div className="flex flex-col gap-5">
      <DetailHeader
        title={sessionName(t, data.document.title, data.reading_index)}
        startedAt={data.started_at}
        completed={data.completed}
      />

      <Block title={t("progress.metrics")}>
        <Metrics>
          <Metric label={t("exit.duration")} value={t("progress.minutes", { n: Math.round((data.metrics.duration_s ?? 0) / 60) })} />
          <Metric label={t("exit.pages")} value={String(data.metrics.pages_read ?? 0)} />
          <Metric label={t("exit.questions")} value={String(data.metrics.questions_answered ?? 0)} />
          <Metric label={t("exit.success")} value={`${data.metrics.success_rate ?? 0} %`} />
          {(data.metrics.pauses ?? 0) > 0 && (
            <Metric
              label={t("progress.pauses")}
              value={t("progress.pauses_value", {
                n: data.metrics.pauses ?? 0,
                time: formatDuration(data.metrics.pause_s ?? 0),
              })}
            />
          )}
        </Metrics>
      </Block>

      <GaugesBlock gauges={data.gauges} />
      <ProfileChangesBlock changes={data.profile_changes} />
      <ReflectionsBlock reflections={data.reflections} />

      {data.page_dwell.length > 0 && (
        <Block title={t("progress.dwell")}>
          <DwellBars dwell={data.page_dwell} />
        </Block>
      )}

      {(data.pauses?.length ?? 0) > 0 && (
        <Block title={t("progress.pauses_title")}>
          <PauseList pauses={data.pauses ?? []} />
        </Block>
      )}
    </div>
  );
}

/** Quiz et langue partagent leur route (`/api/progress/practice/{id}`) : le
 *  détail reçu dit lui-même sa catégorie. */
function PracticeDetail({ sessionId }: { sessionId: number }) {
  const t = useT();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["progress", "practice", sessionId],
    queryFn: () => api.progressPractice(sessionId),
  });

  if (isLoading) return <p className="text-muted-foreground">{t("progress.loading")}</p>;
  if (isError || !data) return <p className="text-danger">{t("progress.error")}</p>;
  return data.kind === "quiz" ? <QuizDetail data={data} /> : <LangDetail data={data} />;
}

/** Où la lecture a ralenti. Une barre par page, normalisée sur la plus longue :
 *  l'échelle absolue n'apprend rien, le contraste entre pages si. */
function DwellBars({ dwell }: { dwell: { page: number; dwell_s: number; visits: number }[] }) {
  const t = useT();
  const max = Math.max(...dwell.map((d) => d.dwell_s), 1);
  return (
    <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
      {dwell.map((entry) => (
        <li key={entry.page} className="flex items-center gap-3">
          <span className="w-20 shrink-0 text-[12px] text-muted-foreground">
            {t("progress.dwell_page", { page: entry.page })}
          </span>
          <Bar ratio={entry.dwell_s / max} />
          <span className="w-12 shrink-0 text-right text-[12px] tabular-nums text-muted-foreground">
            {Math.round(entry.dwell_s)}s
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Les pauses de la séance : où, combien de temps, et ce qui les a précédées —
 *  la carte de Clikoda acceptée, une recommandation juste avant, ou rien. */
function PauseList({ pauses }: { pauses: SessionPause[] }) {
  const t = useT();
  return (
    <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
      {pauses.map((pause, index) => (
        <li key={index} className="flex items-center gap-3 text-sm">
          <span className="w-20 shrink-0 text-[12px] text-muted-foreground">
            {pause.page ? t("progress.pause_page", { page: pause.page }) : ""}
          </span>
          <span className="w-14 shrink-0 font-bold tabular-nums">{formatDuration(pause.duration_s)}</span>
          <span className="text-muted-foreground">
            {pause.source === "suggested"
              ? t("progress.pause_suggested")
              : pause.after_recommendation
                ? t("progress.pause_after_reco")
                : t("progress.pause_spontaneous")}
          </span>
        </li>
      ))}
    </ul>
  );
}
