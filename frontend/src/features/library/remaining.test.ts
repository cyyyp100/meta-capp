// remaining.test.ts — Une durée arrondie comme on la dit à voix haute.
import { describe, expect, it } from "vitest";

import { remainingParts } from "./remaining";

describe("remainingParts", () => {
  it("garde les minutes telles quelles sous l'heure", () => {
    expect(remainingParts(1)).toEqual({ kind: "min", min: 1 });
    expect(remainingParts(42)).toEqual({ kind: "min", min: 42 });
    expect(remainingParts(59)).toEqual({ kind: "min", min: 59 });
    // Jamais « 0 min » : il reste au moins la page en cours.
    expect(remainingParts(0)).toEqual({ kind: "min", min: 1 });
  });

  it("arrondit à la dizaine de minutes la plus proche jusqu'à 10 h", () => {
    expect(remainingParts(60)).toEqual({ kind: "h", h: 1 });
    expect(remainingParts(124)).toEqual({ kind: "h", h: 2 });
    expect(remainingParts(126)).toEqual({ kind: "h_min", h: 2, min: 10 });
    expect(remainingParts(347)).toEqual({ kind: "h_min", h: 5, min: 50 });
    // 9 h 56 s'arrondit à 10 h, pas à « 9 h 60 ».
    expect(remainingParts(596)).toEqual({ kind: "h", h: 10 });
  });

  it("passe aux heures rondes au-delà de 10 h", () => {
    expect(remainingParts(600)).toEqual({ kind: "h", h: 10 });
    expect(remainingParts(760)).toEqual({ kind: "h", h: 13 });
    expect(remainingParts(1500)).toEqual({ kind: "h", h: 25 });
  });
});
