// SessionDetail.tsx — Ce qu'une session a produit.
//
// Trois blocs, trois questions différentes :
//   1. les courbes — comment j'ai lu, minute par minute ;
//   2. les mouvements de profil — ce que ça a changé (`value_before` →
//      `value_after` sont déjà stockés par critère, il n'y a rien à recalculer) ;
//   3. MES MOTS, relus tels quels.
//
// C'est le troisième qui crée l'attachement, et c'est le seul qu'aucun autre
// outil ne peut restituer : ni ChatGPT (il n'observe pas la lecture dans la
// durée), ni Anki (il modélise le rappel, pas la compréhension).
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";

import { api } from "@/api/client";
import type { ProgressChange } from "@/api/client";

import { useT } from "../../i18n";
import { criterionLabel } from "../stats/labels";
import { GaugeCurves } from "./GaugeCurves";

export function SessionDetail({ sessionId }: { sessionId: number }) {
  const t = useT();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["progress", "session", sessionId],
    queryFn: () => api.progressSession(sessionId),
  });

  if (isLoading) return <p className="text-muted-foreground">{t("progress.loading")}</p>;
  if (isError || !data) return <p className="text-danger">{t("progress.error")}</p>;

  return (
    <div className="flex flex-col gap-5">
      <header>
        <h2 className="m-0 font-serif text-h2 font-bold">{data.document.title || t("progress.detail_title")}</h2>
        <p className="mt-1 mb-0 text-sm text-muted-foreground">
          {data.completed
            ? t("progress.session_of", { date: formatDate(data.started_at) })
            : t("progress.in_progress")}
        </p>
      </header>

      <Block title={t("progress.metrics")}>
        <dl className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-4">
          <Metric label={t("exit.duration")} value={t("progress.minutes", { n: Math.round((data.metrics.duration_s ?? 0) / 60) })} />
          <Metric label={t("exit.pages")} value={String(data.metrics.pages_read ?? 0)} />
          <Metric label={t("exit.questions")} value={String(data.metrics.questions_answered ?? 0)} />
          <Metric label={t("exit.success")} value={`${data.metrics.success_rate ?? 0} %`} />
        </dl>
      </Block>

      <Block title={t("progress.gauges")}>
        <GaugeCurves gauges={data.gauges} />
      </Block>

      <Block title={t("progress.changes")}>
        {data.profile_changes.length === 0 ? (
          <p className="m-0 text-sm text-muted-foreground italic">{t("progress.no_changes")}</p>
        ) : (
          <ul className="m-0 grid list-none grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-2.5 p-0">
            {data.profile_changes.map((change) => (
              <li key={change.criterion}>
                <ChangeRow change={change} />
              </li>
            ))}
          </ul>
        )}
      </Block>

      <Block title={t("progress.reflections")}>
        {data.reflections.length === 0 ? (
          <p className="m-0 text-sm text-muted-foreground italic">{t("progress.no_reflections")}</p>
        ) : (
          <div className="flex flex-col gap-4">
            {data.reflections.map((reflection, index) => (
              <div key={index}>
                <p className="m-0 text-[13px] font-semibold text-muted-foreground">{reflection.question}</p>
                {/* `whitespace-pre-wrap` : ce que quelqu'un a écrit se relit
                    comme il l'a écrit, retours à la ligne compris. */}
                <p className="mt-1.5 mb-0 border-l-2 border-brand pl-3 text-sm leading-relaxed whitespace-pre-wrap">
                  {reflection.answer}
                </p>
              </div>
            ))}
          </div>
        )}
      </Block>

      {data.page_dwell.length > 0 && (
        <Block title={t("progress.dwell")}>
          <DwellBars dwell={data.page_dwell} />
        </Block>
      )}
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-border bg-surface p-5 shadow-e1">
      <h3 className="m-0 mb-3.5 text-[13px] font-bold tracking-wide text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] font-bold tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="m-0 mt-1 text-h3 font-bold tabular-nums">{value}</dd>
    </div>
  );
}

function ChangeRow({ change }: { change: ProgressChange }) {
  const up = change.delta > 0.05;
  const down = change.delta < -0.05;
  const Icon = up ? ArrowUp : down ? ArrowDown : Minus;
  const tone = up ? "text-success" : down ? "text-warning" : "text-muted-foreground";
  return (
    <div className="flex items-center justify-between gap-3 rounded-sm bg-surface-soft px-3 py-2.5">
      <span className="truncate text-sm font-semibold">{criterionLabel(change.criterion)}</span>
      <span className={`flex shrink-0 items-center gap-1.5 text-sm font-bold tabular-nums ${tone}`}>
        <Icon className="size-3.5" aria-hidden />
        {Math.round(change.before)} → {Math.round(change.after)}
      </span>
    </div>
  );
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
          <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-border">
            <span
              className="block h-full rounded-full bg-brand"
              style={{ width: `${Math.round((entry.dwell_s / max) * 100)}%` }}
            />
          </span>
          <span className="w-12 shrink-0 text-right text-[12px] tabular-nums text-muted-foreground">
            {Math.round(entry.dwell_s)}s
          </span>
        </li>
      ))}
    </ul>
  );
}

function formatDate(value: string): string {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 16);
}
