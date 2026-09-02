// WeeklyRecap.tsx — Le bilan de la semaine.
//
// Un abonnement mensuel à un logiciel de bureau ne tient pas sans rythme
// visible : il faut un objet qui revienne, qu'on attende, et qui raconte
// quelque chose qu'on ne savait pas. C'est celui-là.
//
// Quatre éléments, dans l'ordre où on veut les lire : ce que j'ai lu, ce qui a
// bougé, ce que Gemma a remarqué, ce qu'il me reste à revoir. Rien de plus —
// un bilan qui déborde n'est plus lu.
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, CalendarDays } from "lucide-react";

import { api } from "@/api/client";

import { useT } from "../../i18n";
import { criterionLabel } from "../stats/labels";

export function WeeklyRecap() {
  const t = useT();
  const { data } = useQuery({ queryKey: ["progress", "weekly"], queryFn: api.weeklyRecap });

  if (!data) return null;

  return (
    <section className="rounded-lg border border-border bg-surface p-5.5 shadow-e1">
      <div className="flex items-center gap-2 text-[11px] font-bold tracking-wide text-brand-ink uppercase">
        <CalendarDays className="size-3.5" aria-hidden />
        {t("recap.weekly")}
      </div>

      {data.sessions === 0 ? (
        <p className="mt-2 mb-0 text-sm text-muted-foreground">{t("recap.empty")}</p>
      ) : (
        <>
          <p className="mt-1.5 mb-0 text-sm text-muted-foreground">{t("recap.weekly_hint")}</p>

          <dl className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-4">
            <Stat value={String(data.sessions)} label={t("recap.sessions", { n: data.sessions })} />
            <Stat
              value={String(Math.round(data.duration_s / 60))}
              label={t("recap.reading_time", { n: Math.round(data.duration_s / 60) })}
            />
            <Stat value={String(data.pages_read)} label={t("recap.pages_read", { n: data.pages_read })} />
            <Stat value={String(data.cards.length)} label={t("recap.cards_due", { n: data.cards.length })} />
          </dl>

          {data.movers.length > 0 && (
            <div className="mt-4">
              <h3 className="m-0 mb-2 text-[11px] font-bold tracking-wide text-muted-foreground uppercase">
                {t("recap.movers")}
              </h3>
              <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
                {data.movers.map((mover) => (
                  <li
                    key={mover.criterion}
                    className="flex items-center gap-1.5 rounded-full bg-surface-soft px-3 py-1.5 text-[13px] font-semibold"
                  >
                    {mover.delta > 0 ? (
                      <ArrowUp className="size-3.5 text-success" aria-hidden />
                    ) : (
                      <ArrowDown className="size-3.5 text-warning" aria-hidden />
                    )}
                    {criterionLabel(mover.criterion)}
                    <span className="tabular-nums text-muted-foreground">
                      {mover.delta > 0 ? "+" : ""}
                      {Math.round(mover.delta)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Ce que Gemma a remarqué. C'est l'observation personnelle qui
              accroche — l'étude qui la fonde se consulte APRÈS, sur /stats/science. */}
          {data.analysis && (
            <p className="mt-4 mb-0 border-l-2 border-brand pl-3.5 text-sm leading-relaxed text-text-soft">
              {data.analysis}
            </p>
          )}

          {data.cards.length > 0 && (
            <ul className="m-0 mt-4 flex list-none flex-col gap-1.5 p-0">
              {data.cards.map((card) => (
                <li
                  key={card.id}
                  className="truncate rounded-sm bg-surface-soft px-3 py-2 text-[13px] text-text-soft"
                >
                  {card.front}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <dd className="m-0 text-h2 font-bold tabular-nums">{value}</dd>
      <dt className="text-[12px] text-muted-foreground">{label}</dt>
    </div>
  );
}
