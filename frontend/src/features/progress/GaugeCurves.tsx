// GaugeCurves.tsx — Les courbes de jauges d'UNE séance.
//
// `session_gauges` enregistrait ces points depuis toujours et personne ne les
// avait jamais vus. C'est la preuve visible que le moteur métacognitif tourne :
// six lignes qui montent et descendent pendant qu'on lit.
//
// C'est aussi le point commun des trois catégories de « Ma progression » : une
// lecture, un quiz et une séance de langue tracent la même courbe. Seul change
// ce que porte l'axe — le temps (lecture, épisode), le numéro de question (quiz)
// ou d'exercice (leçon de langue) —, que le serveur déclare (`gauges.axis`).
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

import type { GaugeSeries } from "@/api/client";

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

export function GaugeCurves({ gauges }: { gauges: GaugeSeries }) {
  const t = useT();
  const names = Object.keys(gauges.series);
  if (names.length === 0) {
    return <p className="m-0 text-sm text-muted-foreground italic">{t("progress.no_gauges")}</p>;
  }

  // Recharts veut une ligne par instant, pas une série par jauge : on fusionne
  // sur `t`, qui est déjà l'horloge commune écrite par la séance.
  const byTime = new Map<number, Record<string, number>>();
  for (const name of names) {
    for (const point of gauges.series[name]) {
      const row = byTime.get(point.t) ?? { t: point.t };
      row[name] = point.value;
      byTime.set(point.t, row);
    }
  }
  const rows = [...byTime.values()].sort((a, b) => a.t - b.t);
  const lastT = rows[rows.length - 1]?.t ?? 0;
  // Une échelle de temps suppose du temps : des points tous écrits dans la même
  // seconde (amorce et révision éclair, sans aucune réponse) s'empileraient.
  const timeScale = gauges.axis === "time" && lastT - (rows[0]?.t ?? 0) >= 1;
  const seedAverage =
    Object.values(gauges.seed).reduce((sum, v) => sum + v, 0) /
    Math.max(1, Object.values(gauges.seed).length);

  // Le point 0 est l'amorce, quel que soit l'axe ; ensuite, des minutes ou des
  // numéros de question / d'exercice.
  const tick = (value: number): string => {
    if (gauges.axis === "time") return lastT < 60 ? `${Math.round(value)} s` : `${Math.round(value / 60)}′`;
    if (value === 0) return t("progress.axis_start");
    return t(gauges.axis === "question" ? "progress.axis_question" : "progress.axis_exercise", { n: value });
  };
  // Le temps est une ÉCHELLE : deux mesures à quelques secondes d'écart sont
  // proches sur l'axe, et les graduations tombent sur des minutes rondes (une
  // graduation par mesure affichait « 6′ 6′ » pour 5 min 30 et 6 min).
  const timeTicks = (() => {
    if (!timeScale) return undefined;
    if (lastT < 60) return [0, lastT];
    const step = 60 * Math.max(1, Math.ceil(lastT / 60 / 6));
    const ticks: number[] = [];
    for (let at = 0; at <= lastT; at += step) ticks.push(at);
    return ticks;
  })();
  const pointLabel = (value: number): string => {
    if (gauges.axis === "time") return `${Math.round(Number(value))} s`;
    if (Number(value) === 0) return t("progress.axis_start");
    return t(gauges.axis === "question" ? "progress.point_question" : "progress.point_exercise", {
      n: Number(value),
    });
  };

  return (
    <>
      <div className="h-64 w-full">
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              dataKey="t"
              type={timeScale ? "number" : "category"}
              domain={timeScale ? [0, "dataMax"] : undefined}
              ticks={timeTicks}
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              stroke="var(--border-strong)"
              tickFormatter={tick}
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
              labelFormatter={pointLabel}
            />
            <Legend formatter={(name: string) => criterionLabel(name)} wrapperStyle={{ fontSize: 12 }} />
            {names.map((name) => (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={GAUGE_COLOR[name] ?? "var(--muted)"}
                strokeWidth={2}
                dot={gauges.axis !== "time"}
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
