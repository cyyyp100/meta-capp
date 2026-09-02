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
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import type { ProgressSessionRow } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { useT } from "../i18n";
import { SessionDetail } from "../features/progress/SessionDetail";
import { WeeklyRecap } from "../features/progress/WeeklyRecap";

export function Progress() {
  const t = useT();
  const [selected, setSelected] = useState<number | null>(null);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["progress", "sessions"],
    queryFn: () => api.progressSessions(),
  });

  const sessions = data?.sessions ?? [];

  // Sélection par défaut : la session la plus récente qui a réellement quelque
  // chose à montrer. Ouvrir sur une session vide donnerait de l'écran une
  // première impression fausse.
  useEffect(() => {
    if (selected !== null || sessions.length === 0) return;
    const best = sessions.find((s) => s.completed) ?? sessions[0];
    setSelected(best.session_id);
  }, [sessions, selected]);

  return (
    <div className="flex h-full flex-col gap-5 p-8.5">
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
        <h1 className="m-0 font-serif text-h1 font-bold">{t("progress.title")}</h1>
        <p className="mt-1 mb-0 text-muted-foreground">{t("progress.subtitle")}</p>
      </header>

      {/* Le bilan hebdomadaire passe en tête : c'est le rendez-vous, la frise
          n'est que l'archive dans laquelle on retourne ensuite. */}
      <WeeklyRecap />

      {isLoading && (
        <div className="flex flex-1 gap-6" role="status" aria-busy="true">
          <span className="sr-only">{t("progress.loading")}</span>
          <Skeleton className="h-full w-72 shrink-0 rounded-lg" />
          <Skeleton className="h-full flex-1 rounded-lg" />
        </div>
      )}

      {isError && <p className="text-danger">{t("progress.error")}</p>}

      {data && sessions.length === 0 && (
        <p className="max-w-prose text-muted-foreground">{t("progress.empty")}</p>
      )}

      {data && sessions.length > 0 && (
        <div className="flex min-h-0 flex-1 gap-6">
          <nav
            aria-label={t("progress.title")}
            className="w-72 shrink-0 overflow-y-auto pr-1"
          >
            <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
              {sessions.map((session) => (
                <li key={session.session_id}>
                  <TimelineRow
                    session={session}
                    active={selected === session.session_id}
                    onSelect={() => setSelected(session.session_id)}
                  />
                </li>
              ))}
            </ol>
          </nav>

          <div className="min-w-0 flex-1 overflow-y-auto pr-1 pb-8">
            {selected === null ? (
              <p className="text-muted-foreground">{t("progress.select")}</p>
            ) : (
              <SessionDetail sessionId={selected} />
            )}
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
      <span className="block truncate text-sm font-semibold">
        {session.document_title || t("progress.detail_title")}
      </span>
      <span className="mt-0.5 block text-[12px] text-muted-foreground">
        {session.completed
          ? `${formatDay(session.started_at)} · ${t("progress.minutes", { n: Math.round(session.duration_s / 60) })}`
          : t("progress.in_progress")}
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

function formatDay(value: string): string {
  if (!value) return "—";
  return value.slice(0, 10);
}
