// GaugeCurves.tsx — Les courbes de jauges d'UNE session.
//
// `session_gauges` enregistrait ces points depuis toujours et personne ne les
// avait jamais vus. C'est la preuve visible que le moteur métacognitif tourne :
// six lignes qui montent et descendent pendant qu'on lit.
//
// Le trait pointillé porte l'AMORCE (profil × 0,8). Sans lui, une jauge restée
// à son point de départ ressemble à une mesure — c'est exactement la confusion
// que `services/session._measured_gauges` évite déjà côté finalisation.
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ProgressSession } from "@/api/client";

import { useT } from "../../i18n";
import { criterionLabel } from "../stats/labels";

/** Une teinte par jauge, prises dans les jetons — jamais des littéraux. Six
 *  séries superposées ont besoin d'être distinguables, pas assorties. */
const GAUGE_COLOR: Record<string, string> = {
  attention: "var(--accent)",
  context_comprehension: "var(--hl-explain)",
  retention: "var(--success)",
  curiosity: "var(--hl-key)",
  creativity: "var(--code-keyword)",
  meta_cognition: "var(--warning)",
};

export function GaugeCurves({ gauges }: { gauges: ProgressSession["gauges"] }) {
  const t = useT();
  const names = Object.keys(gauges.series);
  if (names.length === 0) {
    return <p className="m-0 text-sm text-muted-foreground italic">{t("progress.no_gauges")}</p>;
  }

  // Recharts veut une ligne par instant, pas une série par jauge : on fusionne
  // sur `t`, qui est déjà l'horloge commune écrite par `LiveGauges`.
  const byTime = new Map<number, Record<string, number>>();
  for (const name of names) {
    for (const point of gauges.series[name]) {
      const row = byTime.get(point.t) ?? { t: point.t };
      row[name] = point.value;
      byTime.set(point.t, row);
    }
  }
  const rows = [...byTime.values()].sort((a, b) => a.t - b.t);
  const seedAverage =
    Object.values(gauges.seed).reduce((sum, v) => sum + v, 0) /
    Math.max(1, Object.values(gauges.seed).length);

  return (
    <>
      <div className="h-64 w-full">
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              dataKey="t"
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              stroke="var(--border-strong)"
              tickFormatter={(value: number) => `${Math.round(value / 60)}′`}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              stroke="var(--border-strong)"
            />
            <ReferenceLine y={seedAverage} stroke="var(--muted-light)" strokeDasharray="4 4" />
            <Tooltip
              contentStyle={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text)",
              }}
              formatter={(value: number, name: string) => [Math.round(value), criterionLabel(name)]}
              labelFormatter={(value: number) => `${Math.round(Number(value))} s`}
            />
            <Legend formatter={(name: string) => criterionLabel(name)} wrapperStyle={{ fontSize: 12 }} />
            {names.map((name) => (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={GAUGE_COLOR[name] ?? "var(--muted)"}
                strokeWidth={2}
                dot={false}
                // Une jauge jamais exercée est tracée en pointillé : elle est
                // dans le graphe (elle existe), sans prétendre à une mesure.
                strokeDasharray={gauges.measured.includes(name) ? undefined : "4 4"}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 mb-0 text-[13px] text-muted-foreground">{t("progress.gauges_hint")}</p>
    </>
  );
}
