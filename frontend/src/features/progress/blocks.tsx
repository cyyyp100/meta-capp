// blocks.tsx — Les briques communes du détail d'une séance.
//
// Lecture, quiz et langue ont chacune leurs particularités, mais leur détail se
// lit de la même façon : un en-tête, des métriques, LA courbe des jauges, ce
// qu'elle a déplacé dans le profil, et les mots de l'apprenant. Ces blocs-là
// sont définis une seule fois, ici — sinon les trois écrans divergent.
import { ArrowDown, ArrowUp, Minus } from "lucide-react";

import type { GaugeSeries, ProgressChange, Reflection } from "@/api/client";

import { useT } from "../../i18n";
import { criterionLabel } from "../stats/labels";
import { GaugeCurves } from "./GaugeCurves";

export function DetailHeader({
  title,
  startedAt,
  completed,
}: {
  title: string;
  startedAt: string;
  completed: boolean;
}) {
  const t = useT();
  return (
    <header>
      <h2 className="m-0 font-serif text-h2 font-bold">{title}</h2>
      <p className="mt-1 mb-0 text-sm text-muted-foreground">
        {completed ? t("progress.session_of", { date: formatDate(startedAt) }) : t("progress.in_progress")}
      </p>
    </header>
  );
}

export function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-border bg-surface p-5 shadow-e1">
      <h3 className="m-0 mb-3.5 text-[13px] font-bold tracking-wide text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}

export function Metrics({ children }: { children: React.ReactNode }) {
  return <dl className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-4">{children}</dl>;
}

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] font-bold tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="m-0 mt-1 text-h3 font-bold tabular-nums">{value}</dd>
    </div>
  );
}

/** Le point commun des trois catégories : la courbe des jauges pendant la séance. */
export function GaugesBlock({ gauges }: { gauges: GaugeSeries }) {
  const t = useT();
  return (
    <Block title={t("progress.gauges")}>
      <GaugeCurves gauges={gauges} />
    </Block>
  );
}

/** Ce que la séance a déplacé dans le profil (`value_before` → `value_after`). */
export function ProfileChangesBlock({ changes }: { changes: ProgressChange[] }) {
  const t = useT();
  return (
    <Block title={t("progress.changes")}>
      {changes.length === 0 ? (
        <p className="m-0 text-sm text-muted-foreground italic">{t("progress.no_changes")}</p>
      ) : (
        <ul className="m-0 grid list-none grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-2.5 p-0">
          {changes.map((change) => (
            <li key={change.criterion}>
              <ChangeRow change={change} />
            </li>
          ))}
        </ul>
      )}
    </Block>
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

/** Les mots de l'apprenant, relus TELS QUELS — ni résumés, ni reformulés. */
export function ReflectionsBlock({
  reflections,
  title,
  empty,
}: {
  reflections: Reflection[];
  title?: string;
  /** Message sans réflexion ; `null` masque le bloc vide. */
  empty?: string | null;
}) {
  const t = useT();
  if (reflections.length === 0 && empty === null) return null;
  return (
    <Block title={title ?? t("progress.reflections")}>
      {reflections.length === 0 ? (
        <p className="m-0 text-sm text-muted-foreground italic">{empty ?? t("progress.no_reflections")}</p>
      ) : (
        <div className="flex flex-col gap-4">
          {reflections.map((reflection, index) => (
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
  );
}

/** Ce que Clikoda a écrit à la fin de la séance — relu, jamais régénéré. */
export function AnalysisBlock({ analysis, children }: { analysis: string; children?: React.ReactNode }) {
  const t = useT();
  if (!analysis && !children) return null;
  return (
    <Block title={t("progress.analysis")}>
      {analysis && <p className="m-0 text-sm leading-relaxed whitespace-pre-wrap text-text-soft">{analysis}</p>}
      {children}
    </Block>
  );
}

/** Une barre de proportion : l'échelle absolue n'apprend rien, le contraste si. */
export function Bar({ ratio, tone = "bg-brand" }: { ratio: number; tone?: string }) {
  return (
    <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-border">
      <span
        className={`block h-full rounded-full ${tone}`}
        style={{ width: `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%` }}
      />
    </span>
  );
}

export function formatDate(value: string): string {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 16);
}

export function formatDay(value: string): string {
  if (!value) return "—";
  return value.slice(0, 10);
}

/** Un nombre de points avec son demi-point éventuel : « 3,5 », pas « 3.5000 ». */
export function formatPoints(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
