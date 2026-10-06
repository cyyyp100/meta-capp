// LangDetail.tsx — Le détail d'une séance de langue dans « Ma progression ».
//
// Le tronc commun (courbe des jauges, mouvements du profil) et ce qui
// n'appartient qu'à la langue. Deux parcours, deux particularités :
//
//   * le feuilleton : l'épisode lu, le point du jour et ce que la séance a fait
//     GAGNER (mots, signes, cartes) — jamais de score, la règle de son écran de
//     fin (F11) vaut aussi ici. Ce que l'apprenant a dit de sa compréhension est
//     relu tel qu'il l'a dit ;
//   * la leçon (flux hérité) : les exercices, chacun avec sa compétence et sa
//     note, et l'analyse que Clikoda a écrite au sas de sortie.
import type { LangProgress } from "@/api/client";

import { useT } from "../../i18n";
import { formatDuration } from "../session/duration";
import {
  AnalysisBlock,
  Bar,
  Block,
  DetailHeader,
  GaugesBlock,
  Metric,
  Metrics,
  ProfileChangesBlock,
  ReflectionsBlock,
} from "./blocks";
import { langName } from "./names";

export function LangDetail({ data }: { data: LangProgress }) {
  const t = useT();
  const { lang, metrics } = data;
  const feuilleton = lang.flow === "feuilleton";

  return (
    <div className="flex flex-col gap-5">
      <DetailHeader title={langName(t, lang)} startedAt={data.started_at} completed={data.completed} />

      <Block title={t("progress.metrics")}>
        <Metrics>
          <Metric label={t("exit.duration")} value={formatDuration(metrics.duration_s)} />
          {feuilleton ? (
            <>
              <Metric label={t("progress.game_answers")} value={String(metrics.answered)} />
              <Metric label={t("progress.words_acquired")} value={String(lang.acquired_today)} />
              <Metric label={t("progress.cards_created")} value={String(lang.cards_created)} />
            </>
          ) : (
            <>
              <Metric label={t("progress.exercises_graded")} value={String(metrics.answered)} />
              {lang.level && <Metric label={t("lang.level")} value={lang.level} />}
            </>
          )}
        </Metrics>
      </Block>

      <GaugesBlock gauges={data.gauges} />
      <ProfileChangesBlock changes={data.profile_changes} />

      {feuilleton ? <EpisodeGains data={data} /> : <LessonExercises data={data} />}

      <AnalysisBlock analysis={data.analysis} />
      <ReflectionsBlock
        reflections={data.reflections}
        // Au feuilleton, l'au revoir pose une question à choix : c'est un
        // ressenti, pas une réflexion écrite.
        title={feuilleton ? t("progress.feeling") : undefined}
        empty={feuilleton ? null : undefined}
      />
    </div>
  );
}

function EpisodeGains({ data }: { data: LangProgress }) {
  const t = useT();
  const { lang } = data;
  const understood = lang.signals.understood;
  const gains: string[] = [];
  if (lang.acquired_today > 0) gains.push(t("progress.acquired_today", { n: lang.acquired_today }));
  if (lang.units_acquired_today > 0) gains.push(t("progress.units_acquired", { n: lang.units_acquired_today }));
  if (lang.cards_created > 0) gains.push(t("progress.cards_created_n", { n: lang.cards_created }));
  if (!lang.point && lang.new_words.length === 0 && gains.length === 0 && !understood) return null;

  return (
    <Block title={t("progress.gained")}>
      <div className="flex flex-col gap-3.5">
        {lang.point && (
          <div>
            <p className="m-0 text-[13px] font-semibold text-muted-foreground">{t("progress.point")}</p>
            <p className="mt-1 mb-0 text-sm font-semibold">{lang.point}</p>
          </div>
        )}
        {lang.new_words.length > 0 && (
          <div>
            <p className="m-0 text-[13px] font-semibold text-muted-foreground">{t("progress.new_words")}</p>
            <ul className="m-0 mt-1.5 flex list-none flex-wrap gap-1.5 p-0" dir="auto">
              {lang.new_words.map((word) => (
                <li key={word} className="rounded-full bg-surface-soft px-2.5 py-1 text-[13px] font-semibold">
                  {word}
                </li>
              ))}
            </ul>
          </div>
        )}
        {gains.length > 0 && <p className="m-0 text-sm text-text-soft">{gains.join(" · ")}</p>}
        {understood && (
          <p className="m-0 text-sm text-text-soft">
            {t("progress.understood", { answer: t(`feuil.understood.${understood}`) })}
          </p>
        )}
      </div>
    </Block>
  );
}

function LessonExercises({ data }: { data: LangProgress }) {
  const t = useT();
  const exercises = data.lang.exercises;
  if (exercises.length === 0) return null;
  return (
    <Block title={t("progress.exercises")}>
      <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
        {exercises.map((exercise, index) => (
          <li key={index} className="flex items-center gap-3">
            <span className="w-6 shrink-0 text-[12px] tabular-nums text-muted-foreground">{index + 1}</span>
            <span className="w-44 shrink-0 truncate text-[13px]">
              {exercise.label}
              {exercise.skill && (
                <span className="block text-[11px] text-muted-foreground">{t(`skill.${exercise.skill}`)}</span>
              )}
            </span>
            {exercise.score === null ? (
              <span className="text-[12px] text-muted-foreground italic">{t("progress.exercise_ungraded")}</span>
            ) : (
              <>
                <Bar ratio={exercise.score} tone={exercise.score >= 1 ? "bg-success" : "bg-brand"} />
                <span className="w-12 shrink-0 text-right text-[12px] tabular-nums text-muted-foreground">
                  {Math.round(exercise.score * 100)} %
                </span>
              </>
            )}
          </li>
        ))}
      </ol>
    </Block>
  );
}
