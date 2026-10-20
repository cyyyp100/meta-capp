import { afterEach, describe, expect, it } from "vitest";

import { registerTextLayer, selectedWordIndices } from "./textSelection";

/** Un calque minimal : « Bonjour Meta Capp », un span par mot et par espace. */
function makeLayer(): { layer: HTMLDivElement; words: Text[] } {
  const layer = document.createElement("div");
  layer.setAttribute("data-textlayer", "");
  const words: Text[] = [];
  ["Bonjour", "Meta", "Capp"].forEach((text, wi) => {
    if (wi) {
      const space = document.createElement("span");
      space.textContent = " ";
      layer.append(space);
    }
    const span = document.createElement("span");
    span.dataset.wi = String(wi);
    span.textContent = text;
    layer.append(span);
    words.push(span.firstChild as Text);
  });
  document.body.append(layer);
  return { layer, words };
}

function range(start: [Node, number], end: [Node, number]): Range {
  const r = document.createRange();
  r.setStart(...start);
  r.setEnd(...end);
  return r;
}

afterEach(() => {
  document.getSelection()?.removeAllRanges();
  document.body.innerHTML = "";
});

describe("selectedWordIndices", () => {
  it("ne prend pas le mot que la sélection ne fait qu'effleurer", () => {
    const { layer, words } = makeLayer();
    // Jusqu'au tout début de « Meta » : seul « Bonjour » est sélectionné.
    expect(selectedWordIndices(range([words[0], 2], [words[1], 0]), layer)).toEqual([0]);
    // Depuis la toute fin de « Bonjour » : seul « Meta ».
    expect(selectedWordIndices(range([words[0], 7], [words[1], 2]), layer)).toEqual([1]);
  });

  it("prend tout mot dont un caractère est sélectionné", () => {
    const { layer, words } = makeLayer();
    expect(selectedWordIndices(range([words[0], 6], [words[2], 1]), layer)).toEqual([0, 1, 2]);
  });
});

describe("registerTextLayer", () => {
  it("pose un bloc de fin de contenu, et le retire au démontage", () => {
    const { layer } = makeLayer();
    const unregister = registerTextLayer(layer);
    expect(layer.lastElementChild?.hasAttribute("data-textlayer-end")).toBe(true);
    unregister();
    expect(layer.querySelector("[data-textlayer-end]")).toBeNull();
  });

  it("suit l'extrémité de la sélection pendant un glissé, puis retourne à la fin", () => {
    const { layer, words } = makeLayer();
    const unregister = registerTextLayer(layer);
    const end = layer.querySelector("[data-textlayer-end]");

    document.dispatchEvent(new Event("pointerdown"));
    document.getSelection()!.setBaseAndExtent(words[0], 1, words[1], 2);
    document.dispatchEvent(new Event("selectionchange"));
    // Juste après le span où la sélection se termine : un vide survolé la
    // ramène là, pas au bout de la page.
    expect(words[1].parentElement!.nextElementSibling).toBe(end);

    document.dispatchEvent(new Event("pointerup"));
    expect(layer.lastElementChild).toBe(end);
    unregister();
  });

  it("un appui dans le blanc efface la sélection sans en commencer une", () => {
    const { layer, words } = makeLayer();
    const unregister = registerTextLayer(layer);
    document.getSelection()!.setBaseAndExtent(words[0], 1, words[1], 2);
    const press = new MouseEvent("mousedown", { button: 0, bubbles: true, cancelable: true });
    layer.querySelector("[data-textlayer-end]")!.dispatchEvent(press);
    expect(press.defaultPrevented).toBe(true);
    expect(document.getSelection()!.rangeCount).toBe(0);
    unregister();
  });

  it("ne bouge rien hors d'un glissé (sélection au clavier, effacée par le lecteur)", () => {
    const { layer, words } = makeLayer();
    const unregister = registerTextLayer(layer);
    const end = layer.querySelector("[data-textlayer-end]");
    document.getSelection()!.setBaseAndExtent(words[0], 1, words[1], 2);
    document.dispatchEvent(new Event("selectionchange"));
    expect(layer.lastElementChild).toBe(end);
    unregister();
  });
});
