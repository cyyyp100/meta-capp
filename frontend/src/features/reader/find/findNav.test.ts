// findNav.test.ts — Du compte par page à « 3 / 17 », sans erreur d'une unité.
import { describe, expect, it } from "vitest";

import { firstHitFrom, locate, neighbourPages, step } from "./findNav";

const pages = [
  { page: 2, count: 3 },
  { page: 5, count: 1 },
  { page: 9, count: 2 },
];

describe("firstHitFrom", () => {
  it("part de la page à l'écran", () => {
    expect(firstHitFrom(pages, 1)).toBe(0);
    expect(firstHitFrom(pages, 2)).toBe(0);
    expect(firstHitFrom(pages, 3)).toBe(3); // la page 5
    expect(firstHitFrom(pages, 9)).toBe(4);
  });

  it("revient au début quand il n'y a plus rien après", () => {
    expect(firstHitFrom(pages, 10)).toBe(0);
  });

  it("dit qu'il n'y a rien", () => {
    expect(firstHitFrom([], 1)).toBe(-1);
  });
});

describe("step", () => {
  it("avance et recule en bouclant", () => {
    expect(step(0, 6, 1)).toBe(1);
    expect(step(5, 6, 1)).toBe(0);
    expect(step(0, 6, -1)).toBe(5);
    expect(step(3, 6, -1)).toBe(2);
  });

  it("part d'un bout sans occurrence courante, et ne bouge pas sans résultat", () => {
    expect(step(-1, 6, 1)).toBe(0);
    expect(step(-1, 6, -1)).toBe(5);
    expect(step(0, 0, 1)).toBe(-1);
  });
});

describe("locate", () => {
  it("trouve la page et le rang sur la page", () => {
    expect(locate(pages, 0)).toEqual({ page: 2, index: 0 });
    expect(locate(pages, 2)).toEqual({ page: 2, index: 2 });
    expect(locate(pages, 3)).toEqual({ page: 5, index: 0 });
    expect(locate(pages, 5)).toEqual({ page: 9, index: 1 });
  });

  it("rend null hors des bornes", () => {
    expect(locate(pages, 6)).toBeNull();
    expect(locate(pages, -1)).toBeNull();
  });
});

describe("neighbourPages", () => {
  it("demande les pages qui ont des occurrences, autour de l'occurrence et de l'écran", () => {
    const many = [1, 2, 3, 4, 8, 12].map((page) => ({ page, count: 1 }));
    expect(neighbourPages(many, [3, 9])).toEqual([2, 3, 4, 8]);
    expect(neighbourPages(many, [null, undefined])).toEqual([]);
  });
});
