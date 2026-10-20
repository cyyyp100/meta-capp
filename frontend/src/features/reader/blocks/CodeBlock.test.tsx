// CodeBlock.test.tsx — Les occurrences de la recherche dans un fichier de code.
//
// Le serveur envoie des plages en offsets UTF-16 du texte du bloc (Python et
// JavaScript ne replient pas les accents pareil). Elles passent devant les
// surlignages, la courante est désignée, et rien n'échappe à l'échappement.
import { describe, expect, it } from "vitest";

import { renderCode } from "./CodeBlock";

function dom(html: string): HTMLElement {
  const root = document.createElement("pre");
  root.innerHTML = html;
  return root;
}

describe("renderCode — occurrences de la recherche", () => {
  it("pose une marque par plage, et désigne la courante", () => {
    const code = "x = '😀 Équation'\ny = 'equation'";
    const root = dom(renderCode(code, "python", [], [[8, 16], [23, 31]], 1));
    const marks = [...root.querySelectorAll("mark[data-find]")];
    expect(marks.map((m) => m.textContent)).toEqual(["Équation", "equation"]);
    const current = root.querySelectorAll("mark[data-find-current]");
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toBe("equation");
    // Le texte entier est intact autour des marques.
    expect(root.textContent).toBe(code);
  });

  it("passe devant un surlignage qui la chevauche", () => {
    const code = "def equation(): pass";
    const root = dom(renderCode(code, "python", [{ text: "def equation", color: "yellow", id: 7 }], [[4, 12]], 0));
    expect(root.querySelector("mark[data-find-current]")?.textContent).toBe("equation");
    expect(root.querySelector("mark[data-hl]")).toBeNull();
    // Hors recherche, le surlignage revient.
    expect(dom(renderCode(code, "python", [{ text: "def equation", color: "yellow", id: 7 }])).querySelector(
      "mark[data-hl]",
    )?.textContent).toBe("def equation");
  });

  it("échappe le code des occurrences et ignore une plage hors du texte", () => {
    const html = renderCode("a <b> c", "text", [], [[2, 5], [40, 50]], -1);
    expect(html).toContain("&lt;b&gt;");
    expect(html).not.toContain("<b>");
    expect(dom(html).querySelectorAll("mark[data-find]")).toHaveLength(1);
  });
});
