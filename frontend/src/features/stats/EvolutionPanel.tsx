import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";

import type { CriterionEntry } from "../../api/types";
import { useT } from "../../i18n";
import { scoreColor, scoreInk } from "./labels";

export function EvolutionPanel({ criteria }: { criteria: CriterionEntry[] }) {
  const t = useT();
  const hasData = criteria.some((c) => c.history.length >= 2);
  if (!hasData) {
    return <div style={{ color: "var(--muted)", fontStyle: "italic" }}>{t("stats.no_history")}</div>;
  }
  return (
    <div style={{ display: "grid", gap: 10 }}>
      {criteria.map((c) => (
        <div key={c.key} style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ width: 130, fontSize: 13, fontWeight: 600 }}>{t(`crit.${c.key}`)}</span>
          <div style={{ flex: 1, height: 38 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={(c.history.length ? c.history : [c.value]).map((v, i) => ({ i, v }))}>
                <YAxis domain={[0, 100]} hide />
                <Line type="monotone" dataKey="v" stroke={scoreColor(c.value)} strokeWidth={2} dot={false} isAnimationActive />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <span style={{ width: 36, textAlign: "right", fontWeight: 700, color: scoreInk(c.value) }}>{Math.round(c.value)}</span>
        </div>
      ))}
    </div>
  );
}
