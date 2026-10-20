// palette.test.ts — Couleurs et tracés de la prise de notes.
import { describe, expect, it } from "vitest";

import type { AnnotationLabel } from "../../../api/types";
import { labelColor, labelName, markCss, NEUTRAL_COLOR, svgStyle } from "./palette";

const label = (over: Partial<AnnotationLabel> = {}): AnnotationLabel => ({
  id: 1,
  preset: "definition",
  name: null,
  color: "blue",
  position: 0,
  usage: 0,
  ...over,
});

describe("palette", () => {
  it("nomme une étiquette prédéfinie dans la langue de l'interface, sauf si l'élève l'a renommée", () => {
    expect(labelName(label(), "fr")).toBe("Définition");
    expect(labelName(label(), "en")).toBe("Definition");
    expect(labelName(label({ name: "Défs" }), "en")).toBe("Défs");
    expect(labelName(null, "fr")).toBe("Sans étiquette");
  });

  it("colore d'après l'étiquette, en neutre quand elle a disparu", () => {
    expect(labelColor(label())).toBe("var(--note-blue)");
    expect(labelColor(null)).toBe(NEUTRAL_COLOR);
  });

  it("trace chaque style sur la ligne", () => {
    const r = [10, 100, 90, 112];
    expect(svgStyle("highlight", "c", r)).toMatchObject({ x: 10, y: 100, width: 80, height: 12, fillOpacity: 0.32 });
    const under = svgStyle("underline", "c", r);
    expect(under.y + under.height).toBe(112);
    expect(under.height).toBeLessThan(3);
    const strike = svgStyle("strike", "c", r);
    expect(strike.y).toBeGreaterThan(100);
    expect(strike.y + strike.height).toBeLessThan(112);
    expect(svgStyle("outline", "c", r)).toMatchObject({ fill: "none", stroke: "c" });
  });

  it("traduit le style en CSS de <mark>", () => {
    expect(markCss("highlight", "var(--note-red)")).toContain("color-mix(in srgb, var(--note-red) 40%");
    expect(markCss("underline", "var(--note-red)")).toContain("text-decoration:underline");
    expect(markCss("strike", "var(--note-red)")).toContain("line-through");
    expect(markCss("outline", "var(--note-red)")).toContain("outline:1.5px solid var(--note-red)");
  });
});
