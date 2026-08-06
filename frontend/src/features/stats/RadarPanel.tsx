import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";

import type { CriterionEntry } from "../../api/types";
import { useT } from "../../i18n";

interface RadarPanelProps {
  criteria: CriterionEntry[];
}

export function RadarPanel({ criteria }: RadarPanelProps) {
  const t = useT();
  const data = criteria.map((c) => ({
    criterion: t(`crit.${c.key}`),
    value: Math.round(c.value),
  }));

  return (
    <ResponsiveContainer width="100%" height={320}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="var(--border)" />
        <PolarAngleAxis
          dataKey="criterion"
          tick={{ fill: "var(--text-soft)", fontSize: 12 }}
        />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        <Radar
          dataKey="value"
          stroke="var(--accent)"
          fill="var(--accent)"
          fillOpacity={0.28}
          isAnimationActive
          animationDuration={600}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}
