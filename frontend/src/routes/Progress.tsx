// routes/Progress.tsx — « Ma progression ».
//
// C'est l'écran que le produit n'avait pas, alors qu'il en avait toutes les
// données : `metacog_history`, `session_gauges`, `session_reflections`,
// `page_dwell` étaient écrits depuis des mois et aucun routeur ne les exposait.
// L'utilisateur ne voyait qu'un radar sur une page appelée « Profil ».
//
// Le radar reste chez `/stats` : il dit OÙ on en est. Cet écran-ci dit COMMENT
// on y est arrivé — et c'est cette seconde chose qui prend de la valeur avec
// l'ancienneté, donc qui coûte cher à abandonner.
//
// Trois catégories de séances y figurent — lecture, quiz, langue —, chacune avec
// ses particularités, toutes avec la courbe des jauges pendant la séance.
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BookOpen, Languages, ListChecks } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import type { ProgressKind, ProgressSessionRow } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { useT } from "../i18n";
import { formatDay } from "../features/progress/blocks";
import { rowName } from "../features/progress/names";
import { SessionDetail } from "../features/progress/SessionDetail";
import { WeeklyRecap } from "../features/progress/WeeklyRecap";

type Category = "all" | ProgressKind;
const CATEGORIES: Category[] = ["all", "reading", "quiz", "lang"];
const KIND_ICON: Record<ProgressKind, typeof BookOpen> = {
  reading: BookOpen,
  quiz: ListChecks,
  lang: Languages,
};

/** Clé d'une ligne : un id n'est unique qu'au sein de sa famille de séances. */
const rowKey = (row: { kind: ProgressKind; session_id: number }) => `${row.kind}:${row.session_id}`;

export function Progress() {
  const t = useT();
  const [category, setCategory] = useState<Category>("all");
  const [picked, setPicked] = useState<string | null>(null);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["progress", "sessions", category],
    queryFn: () => api.progressSessions(40, category === "all" ? undefined : category),
  });

  const sessions = data?.sessions ?? [];
  const total = data ? Object.values(data.counts).reduce((sum, n) => sum + n, 0) : 0;

  // Sélection : celle de l'apprenant si elle est dans la catégorie affichée,
  // sinon la séance la plus récente qui a réellement quelque chose à montrer.
  // Ouvrir sur une séance vide donnerait de l'écran une première impression fausse.
  const current =
    sessions.find((s) => rowKey(s) === picked) ?? sessions.find((s) => s.completed) ?? sessions[0] ?? null;

  return (
    // La page défile EN ENTIER (c'est `<main>` qui porte le défilement). Elle
    // était en `h-full` avec la frise et le détail en `flex-1 min-h-0` : le
    // bilan hebdomadaire prenait la hauteur qu'il voulait, et la zone du bas —
    // les courbes, les réflexions — se retrouvait comprimée dans le reliquat,
    // à lire par un ascenseur intérieur de quelques lignes.
    <div className="flex flex-col gap-5 p-8.5">
      <header>
        {/* Retour explicite : cet écran n'a plus d'entrée dans la barre
            latérale, on y arrive depuis le profil et on doit pouvoir y revenir
            autrement qu'avec le bouton « précédent » du navigateur — qui
            n'existe pas dans une fenêtre native. */}
        <Link
          to="/stats"
          className="mb-3 inline-flex items-center gap-1.5 text-[13px] font-semibold
                     text-muted-foreground no-underline transition-colors duration-fast
                     ease-brand hover:text-foreground"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {t("progress.back")}
        </Link>
        <h1 data-tour="progress" className="m-0 font-serif text-h1 font-bold">{t("progress.title")}</h1>
        <p className="mt-1 mb-0 text-muted-foreground">{t("progress.subtitle")}</p>
      </header>

      {/* Le bilan hebdomadaire passe en tête : c'est le rendez-vous, la frise
          n'est que l'archive dans laquelle on retourne ensuite. */}
      <WeeklyRecap />

      {/* Les catégories : même motif que le choix du type de session du quiz
          (boutons à bascule), avec l'effectif de chacune. */}
      <div role="group" aria-label={t("progress.categories")} className="flex flex-wrap gap-2">
        {CATEGORIES.map((value) => {
          const count = value === "all" ? total : data?.counts[value];
          const Icon = value === "all" ? null : KIND_ICON[value];
          return (
            <Button
              key={value}
              size="sm"
              variant={category === value ? "default" : "secondary"}
              aria-pressed={category === value}
              onClick={() => setCategory(value)}
            >
              {Icon && <Icon aria-hidden />}
              {t(`progress.cat_${value}`)}
              {count !== undefined && <span className="tabular-nums opacity-70">{count}</span>}
            </Button>
          );
        })}
      </div>

      {isLoading && (
        <div className="flex gap-6" role="status" aria-busy="true">
          <span className="sr-only">{t("progress.loading")}</span>
          <Skeleton className="h-80 w-72 shrink-0 rounded-lg" />
          <Skeleton className="h-80 flex-1 rounded-lg" />
        </div>
      )}

      {isError && <p className="text-danger">{t("progress.error")}</p>}

      {data && sessions.length === 0 && (
        <p className="max-w-prose text-muted-foreground">
          {t(category === "all" ? "progress.empty" : `progress.empty_${category}`)}
        </p>
      )}

      {data && current && (
        <div className="flex items-start gap-6">
          {/* La frise reste sous la main pendant qu'on défile le détail :
              collée en haut de la fenêtre, et bornée à sa hauteur pour qu'une
              longue frise défile en son sein sans repousser le reste. */}
          <nav
            aria-label={t("progress.title")}
            className="sticky top-0 max-h-[calc(100vh-2rem)] w-72 shrink-0 overflow-y-auto pr-1"
          >
            <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
              {sessions.map((session) => (
                <li key={rowKey(session)}>
                  <TimelineRow
                    session={session}
                    active={rowKey(session) === rowKey(current)}
                    onSelect={() => setPicked(rowKey(session))}
                  />
                </li>
              ))}
            </ol>
          </nav>

          <div className="min-w-0 flex-1 pr-1 pb-8">
            <SessionDetail key={rowKey(current)} kind={current.kind} sessionId={current.session_id} />
          </div>
        </div>
      )}
    </div>
  );
}

function TimelineRow({
  session,
  active,
  onSelect,
}: {
  session: ProgressSessionRow;
  active: boolean;
  onSelect: () => void;
}) {
  const t = useT();
  const moved = session.criteria_moved > 0;
  const Icon = KIND_ICON[session.kind];
  // En minutes, sans libellé pour dire que c'est une durée : « 13:00 » se lisait
  // comme une heure. Sous la minute (quiz express), en secondes.
  const duration =
    session.duration_s < 60
      ? t("progress.seconds", { n: session.duration_s })
      : t("progress.minutes", { n: Math.round(session.duration_s / 60) });
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? "true" : undefined}
      className={cn(
        "w-full rounded-sm border px-3 py-2.5 text-left outline-none",
        "transition-[background-color,border-color] duration-fast ease-brand",
        "focus-visible:ring-[3px] focus-visible:ring-ring/50",
        active
          ? "border-brand bg-brand-soft"
          : "border-border bg-surface hover:border-border-strong hover:bg-surface-soft",
      )}
    >
      {/* Le nom d'une séance dit ce qu'elle a été : le document et la
          combientième lecture, la matière du quiz, la langue et l'épisode. */}
      <span className="flex items-center gap-2 text-sm font-semibold">
        <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span className="truncate">{rowName(t, session)}</span>
      </span>
      <span className="mt-0.5 block text-[12px] text-muted-foreground">
        {t(`progress.cat_${session.kind}`)}
        {" · "}
        {session.completed ? `${formatDay(session.started_at)} · ${duration}` : t("progress.in_progress")}
        {session.kind === "quiz" && session.quiz && session.completed && (
          <> · {t("progress.success_short", { n: session.quiz.success_rate })}</>
        )}
      </span>
      <span
        className={cn(
          "mt-1 block text-[12px] font-semibold",
          moved ? "text-brand-ink" : "text-muted-foreground",
        )}
      >
        {moved ? t("progress.moved", { n: session.criteria_moved }) : t("progress.no_move")}
      </span>
    </button>
  );
}
