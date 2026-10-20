// features/reader/find/findNav.ts — Parcourir les occurrences d'une recherche.
//
// Le serveur répond par page (`{page, count}`) ; l'élève parcourt une seule
// liste, « 3 / 17 ». Ces fonctions passent de l'une à l'autre — pures, parce
// que c'est là que se nichent les erreurs d'une unité.

export interface PageCount {
  page: number;
  count: number;
}

/** Rang (0-based) de la première occurrence sur `fromPage` ou après, en
 *  revenant au début s'il n'y en a plus ensuite ; -1 sans occurrence. */
export function firstHitFrom(pages: PageCount[], fromPage: number): number {
  let seen = 0;
  for (const { page, count } of pages) {
    if (page >= fromPage && count > 0) return seen;
    seen += count;
  }
  return seen > 0 ? 0 : -1;
}

/** Occurrence suivante (`dir` 1) ou précédente (-1), en bouclant. */
export function step(current: number, total: number, dir: 1 | -1): number {
  if (total <= 0) return -1;
  if (current < 0) return dir === 1 ? 0 : total - 1;
  return (((current + dir) % total) + total) % total;
}

/** Où tombe l'occurrence de rang `ordinal` : sa page, et son rang sur la page. */
export function locate(pages: PageCount[], ordinal: number): { page: number; index: number } | null {
  if (ordinal < 0) return null;
  let rest = ordinal;
  for (const { page, count } of pages) {
    if (rest < count) return { page, index: rest };
    rest -= count;
  }
  return null;
}

/** Pages dont on demande les occurrences : celles qui en ont, autour des pages
 *  données (l'occurrence courante, la page à l'écran), une de chaque côté. */
export function neighbourPages(pages: PageCount[], around: (number | null | undefined)[]): number[] {
  const withHits = new Set(pages.filter((p) => p.count > 0).map((p) => p.page));
  const wanted = new Set<number>();
  for (const center of around) {
    if (center == null) continue;
    for (const page of [center - 1, center, center + 1]) if (withHits.has(page)) wanted.add(page);
  }
  return [...wanted].sort((a, b) => a - b);
}

/** Le raccourci de la recherche : ⌘F sur macOS, Ctrl+F ailleurs. */
export function isMacPlatform(): boolean {
  const nav = typeof navigator === "undefined" ? null : navigator;
  return /Mac|iPhone|iPad/i.test(nav?.platform || nav?.userAgent || "");
}
