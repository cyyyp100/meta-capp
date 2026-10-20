// features/reader/find/useReaderFind.ts — L'état de la recherche du lecteur.
//
// Deux temps, comme côté serveur (nwol/services/reader_find) : le RÉSUMÉ de
// tout le document (combien, sur quelles pages), puis les occurrences des
// seules pages utiles — celle de l'occurrence courante et celle à l'écran, et
// leurs voisines qui en ont. Un manuel de 400 pages ne demande ainsi jamais
// 400 réponses. Le seuil de longueur de la requête est celui du serveur
// (`too_short`) : il n'est pas recopié ici.
import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "../../../api/client";
import type { FindOnPage, FindSummary } from "../../../api/types";
import { useDebounced } from "../../library/useDebounced";
import { firstHitFrom, locate, neighbourPages, step, type PageCount } from "./findNav";

const FIND_DEBOUNCE_MS = 200;
const NO_PAGES: PageCount[] = [];

/** Les occurrences par page, réunies — fonction de module : stable, React
 *  Query ne recombine alors que si une des réponses change. */
function byPage(results: UseQueryResult<FindOnPage>[]): Record<number, FindOnPage> {
  const out: Record<number, FindOnPage> = {};
  for (const result of results) if (result.data) out[result.data.page] = result.data;
  return out;
}

export interface ReaderFind {
  open: boolean;
  /** Ouvre la barre (ou y ramène le curseur si elle l'est déjà). */
  openBar: () => void;
  close: () => void;
  query: string;
  setQuery: (value: string) => void;
  /** Le résumé de la requête en cours, une fois la frappe posée. */
  summary: FindSummary | undefined;
  searching: boolean;
  /** Rang de l'occurrence courante (0-based), -1 sans résultat. */
  ordinal: number;
  /** Sa page et son rang sur la page. */
  hit: { page: number; index: number } | null;
  next: () => void;
  prev: () => void;
  /** Les occurrences des pages demandées, par page. */
  pageHits: Record<number, FindOnPage>;
  /** Change à chaque `openBar()` : la barre y reprend le focus. */
  focusToken: number;
}

export function useReaderFind(docId: number, viewPage: number): ReaderFind {
  const [open, setOpen] = useState(false);
  const [query, setQueryState] = useState("");
  // -1 : pas encore choisie, c'est la première à partir de `startPage`.
  const [current, setCurrent] = useState(-1);
  // La page à l'écran quand la requête a été tapée : « 1 / 17 » est la
  // première occurrence à partir d'ICI, comme dans un navigateur.
  const [startPage, setStartPage] = useState(1);
  const [focusToken, setFocusToken] = useState(0);
  const typed = query.trim();
  const q = useDebounced(typed, FIND_DEBOUNCE_MS);

  const summaryQuery = useQuery({
    queryKey: ["find", docId, q],
    queryFn: () => api.findInDocument(docId, q),
    enabled: open && q.length > 0,
  });
  const summary = open && q ? summaryQuery.data : undefined;
  const pages = summary?.pages ?? NO_PAGES;
  const total = summary?.total ?? 0;
  const ordinal = total === 0 ? -1 : current >= 0 ? Math.min(current, total - 1) : firstHitFrom(pages, startPage);
  const hit = ordinal >= 0 ? locate(pages, ordinal) : null;
  const hitPage = hit?.page ?? null;

  const wanted = useMemo(() => neighbourPages(pages, [hitPage, viewPage]), [pages, hitPage, viewPage]);
  const pageHits = useQueries({
    queries: wanted.map((page) => ({
      queryKey: ["find", docId, q, page],
      queryFn: () => api.findOnPage(docId, page, q),
      staleTime: Infinity,
    })),
    combine: byPage,
  });

  return {
    open,
    openBar: () => {
      if (!open) setStartPage(viewPage);
      setOpen(true);
      setFocusToken((n) => n + 1);
    },
    close: () => setOpen(false),
    query,
    setQuery: (value) => {
      setQueryState(value);
      setCurrent(-1);
      setStartPage(viewPage);
    },
    summary,
    searching: open && typed.length > 0 && (typed !== q || summaryQuery.isFetching),
    ordinal,
    hit,
    next: () => {
      if (total > 0) setCurrent(step(ordinal, total, 1));
    },
    prev: () => {
      if (total > 0) setCurrent(step(ordinal, total, -1));
    },
    pageHits,
    focusToken,
  };
}
