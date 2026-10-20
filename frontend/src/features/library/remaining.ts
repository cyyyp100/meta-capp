// features/library/remaining.ts — Une durée de lecture, arrondie comme on la dit.
//
// « 763 min » ne se lit pas ; « 12 h 43 » promet une précision que l'allure
// mesurée n'a pas. Sous l'heure, les minutes telles quelles ; jusqu'à 10 h, des
// heures et la dizaine de minutes la plus proche ; au-delà, des heures rondes.

export type RemainingParts =
  | { kind: "min"; min: number }
  | { kind: "h"; h: number }
  | { kind: "h_min"; h: number; min: number };

const LONG_READ_MIN = 10 * 60;

export function remainingParts(minutes: number): RemainingParts {
  const total = Math.max(1, Math.ceil(minutes));
  if (total < 60) return { kind: "min", min: total };
  if (total >= LONG_READ_MIN) return { kind: "h", h: Math.round(total / 60) };
  const rounded = Math.round(total / 10) * 10;
  const h = Math.floor(rounded / 60);
  const min = rounded % 60;
  return min === 0 ? { kind: "h", h } : { kind: "h_min", h, min };
}
