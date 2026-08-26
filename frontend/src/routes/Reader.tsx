import { useQuery } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useConfirm } from "@/components/ui/confirm";

import { api, pageImageUrl } from "../api/client";
import type { Highlight, HighlightAnchor, PageWord, SavedHighlight, SessionMetrics } from "../api/types";
import type { TextMark } from "../features/reader/anchorText";
import { GemmaPanel, type QaMask } from "../features/reader/GemmaPanel";
import { BlockPages } from "../features/reader/BlockPages";
import { EntrySas } from "../features/session/EntrySas";
import { ExitSas } from "../features/session/ExitSas";
import { PostExitRestSas } from "../features/session/PostExitRestSas";
import { useT } from "../i18n";

const HL_COLORS: Record<string, string> = {
  key: "var(--hl-key)",
  explain: "var(--hl-explain)",
  reference: "var(--hl-reference)",
};

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const BASE_WIDTH = 820;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

// Fusionne des rects par mot en un bloc continu par ligne : on regroupe les rects
// dont le centre vertical tombe dans la même bande (ligne), puis on soude les runs
// horizontalement contigus (tolérance ≈ 0.8× hauteur de ligne pour les espaces).
function mergeLineRects(rects: number[][]): number[][] {
  const valid = rects.filter((r) => r.length >= 4);
  if (valid.length <= 1) return valid;
  const lines: number[][][] = [];
  for (const r of [...valid].sort((a, b) => a[1] - b[1] || a[0] - b[0])) {
    const line = lines.find((ln) => {
      const midY = (ln[0][1] + ln[0][3]) / 2;
      return r[1] < midY && r[3] > midY;
    });
    if (line) line.push(r);
    else lines.push([r]);
  }
  const merged: number[][] = [];
  for (const line of lines) {
    line.sort((a, b) => a[0] - b[0]);
    let cur = [...line[0]];
    for (let i = 1; i < line.length; i++) {
      const r = line[i];
      if (r[0] - cur[2] <= (cur[3] - cur[1]) * 0.8) {
        cur = [Math.min(cur[0], r[0]), Math.min(cur[1], r[1]), Math.max(cur[2], r[2]), Math.max(cur[3], r[3])];
      } else {
        merged.push(cur);
        cur = [...r];
      }
    }
    merged.push(cur);
  }
  return merged;
}

const selBtn: React.CSSProperties = {
  border: "1px solid var(--border)",
  background: "var(--surface-soft)",
  color: "var(--text)",
  borderRadius: "var(--radius-sm)",
  padding: "5px 10px",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

export function Reader() {
  const { docId } = useParams();
  const navigate = useNavigate();
  const t = useT();
  const confirm = useConfirm();
  const id = Number(docId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);

  const [sessionId, setSessionId] = useState<number | null>(null);
  const [exitMetrics, setExitMetrics] = useState<SessionMetrics | null>(null);
  const [showPostExitRest, setShowPostExitRest] = useState(false);
  const [entered, setEntered] = useState(false);
  // 0 = pas encore monté ; la vraie valeur est posée par l'effet de démarrage de session.
  const startTimeRef = useRef(0);
  const maxPageRef = useRef(1);

  const [zoom, setZoom] = useState(1);
  // Décalage horizontal du PDF (px). Découplé du scroll natif (transform) -> reste
  // utilisable même quand le scroll vertical est figé (question bloquante de Gemma),
  // et permet de pousser le PDF à gauche pour loger Gemma à droite.
  const [panX, setPanX] = useState(0);
  const [panning, setPanning] = useState(false);
  const panDragRef = useRef<{ startX: number; startPan: number } | null>(null);
  const widthRef = useRef(BASE_WIDTH);
  const [renderZoom, setRenderZoom] = useState(2.5);
  const [currentPage, setCurrentPage] = useState(1);
  // Marque-page : page quittée à la session précédente (figée à l'ouverture, > 1 seulement).
  const [bookmarkPage, setBookmarkPage] = useState<number | null>(null);
  const ratios = useRef<Map<number, number>>(new Map());
  const [highlightsByPage, setHighlightsByPage] = useState<Record<number, { rect: number[]; color: string }[]>>({});

  // Calque de texte transparent (sélection native) + surlignages mémorisés.
  const [wordsByPage, setWordsByPage] = useState<Record<number, PageWord[]>>({});
  const [savedHighlights, setSavedHighlights] = useState<SavedHighlight[]>([]);
  // Citations de Gemma sur pages reconstruites (marquées par recherche pliée).
  const [quoteMarksByPage, setQuoteMarksByPage] = useState<Record<number, TextMark[]>>({});
  const [selection, setSelection] = useState<
    {
      text: string;
      page: number;
      rects: number[][];
      anchor: HighlightAnchor | null;
      x: number;
      y: number;
    } | null
  >(null);
  // Extraits ajoutés au contexte du LLM (consommés par GemmaPanel pour la prochaine question).
  const [contextChips, setContextChips] = useState<{ id: number; page: number; text: string }[]>([]);
  // Question automatique bloquante : scroll figé sur la page-contexte.
  const [locked, setLocked] = useState(false);
  const [lockedPage, setLockedPage] = useState(1);
  // Rappel libre : passage caché sous un cache opaque le temps de répondre.
  const [maskByPage, setMaskByPage] = useState<Record<number, number[][]>>({});

  async function handleMask(mask: QaMask | null, page: number) {
    if (!mask?.quote) {
      setMaskByPage({});
      setQuoteMarksByPage((prev) => {
        const next = { ...prev };
        for (const key of Object.keys(next)) {
          next[Number(key)] = next[Number(key)].filter((m) => !m.masked);
        }
        return next;
      });
      return;
    }
    // Lecture reconstruite : on cache par marquage de texte, faute de géométrie.
    if (isCode) {
      setQuoteMarksByPage((prev) => ({
        ...prev,
        [page]: [...(prev[page] ?? []), { text: mask.quote, color: "var(--surface-soft)", masked: true }],
      }));
      return;
    }
    try {
      const { rects_pts } = await api.searchPage(id, page, mask.quote);
      const rects = mergeLineRects(rects_pts);
      // Passage introuvable (extraction ≠ rendu) : plutôt que de cacher la page
      // entière, on laisse la question posée — elle reste jouable, en plus facile.
      if (rects.length) setMaskByPage({ [page]: rects });
    } catch {
      /* rien à masquer : dégradation silencieuse, comme pour les citations */
    }
  }

  async function handleHighlights(items: Highlight[], page: number) {
    // Lecture reconstruite : les citations sont localisées par recherche pliée
    // dans le texte des blocs (anchorText), pas par géométrie PyMuPDF.
    if (isCode) {
      const marks: TextMark[] = [];
      for (const h of items) {
        const quote = (h.quote || h.text || "").trim();
        if (!quote) continue;
        const color = HL_COLORS[h.purpose ?? "key"] ?? "var(--hl-key)";
        marks.push({ text: quote, color: `color-mix(in srgb, ${color} 45%, transparent)` });
      }
      if (marks.length) setQuoteMarksByPage((prev) => ({ ...prev, [page]: marks }));
      return;
    }
    const groups: { rect: number[]; color: string }[] = [];
    for (const h of items) {
      const quote = (h.quote || h.text || "").trim();
      if (!quote) continue;
      try {
        const { rects_pts } = await api.searchPage(id, page, quote);
        const color = HL_COLORS[h.purpose ?? "key"] ?? "var(--hl-key)";
        for (const r of mergeLineRects(rects_pts)) groups.push({ rect: r, color });
      } catch {
        /* citation introuvable sur la page : on ignore */
      }
    }
    if (groups.length) setHighlightsByPage((prev) => ({ ...prev, [page]: groups }));
  }

  // Surlignages mémorisés : chargés à l'ouverture, redessinés à l'identique.
  useEffect(() => {
    if (!Number.isFinite(id)) return;
    let cancelled = false;
    api.listHighlights(id).then((items) => !cancelled && setSavedHighlights(items)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id]);

  function removeSavedHighlight(hid: number) {
    setSavedHighlights((prev) => prev.filter((h) => h.id !== hid));
    api.deleteHighlight(id, hid).catch(() => {});
  }

  /**
   * Suppression d'un surlignage : demandée depuis deux endroits (le lecteur de
   * code et le calque SVG du PDF), qui appelaient chacun leur `window.confirm`.
   * Une seule fonction ici — le message et le libellé ne peuvent plus diverger.
   */
  async function askRemoveHighlight(hid: number) {
    const ok = await confirm({
      title: t("reader.hl_delete_confirm"),
      confirmLabel: t("common.delete"),
      destructive: true,
    });
    if (ok) removeSavedHighlight(hid);
  }

  // Action « ➕ Contexte » : mémorise l'extrait pour la prochaine question.
  function addSelectionToContext() {
    if (!selection) return;
    setContextChips((prev) => [...prev, { id: Date.now(), page: selection.page, text: selection.text }]);
    clearSelection();
  }

  // Action « 🖊 Surligner » : persiste le surlignage (réapparaît la prochaine fois).
  // Document raster : ancrage par rects (points PDF). Document reconstruit :
  // ancrage TEXTE {block_id, start, end} + quote (rects vides).
  async function highlightSelection() {
    if (!selection) return clearSelection();
    if (!isCode && !selection.rects.length) return clearSelection();
    const { page, text, rects, anchor } = selection;
    try {
      const { id: hid } = await api.createHighlight(id, {
        page,
        quote: text,
        rects,
        color: "key",
        anchor: anchor ?? undefined,
      });
      setSavedHighlights((prev) => [...prev, { id: hid, page, quote: text, rects, color: "key", anchor }]);
    } catch {
      /* persistance best-effort */
    }
    clearSelection();
  }

  function clearSelection() {
    window.getSelection()?.removeAllRanges();
    setSelection(null);
  }

  function removeContextChip(chipId: number) {
    setContextChips((prev) => prev.filter((c) => c.id !== chipId));
  }

  const { data, isLoading, isError } = useQuery({
    queryKey: ["document", id],
    queryFn: () => api.document(id),
    enabled: Number.isFinite(id),
  });

  // Fichier de code : lecteur en blocs (monospace + numéros de ligne), sans PDF
  // ni image de page. Un PDF reste rendu tel quel, en images.
  const isCode = data?.extraction_engine === "code";

  // Marque-page : on fige la page de reprise au tout premier chargement (valeur de la
  // session précédente, écrite en fin de session côté backend). On ignore la page 1
  // (document jamais lu) où le repère n'aurait pas de sens. Le PDF ouvre toujours page 1.
  useEffect(() => {
    if (data && bookmarkPage === null && (data.last_page ?? 1) > 1) {
      setBookmarkPage(data.last_page);
    }
  }, [data, bookmarkPage]);

  // Re-rendu HD à palier quand le zoom se stabilise (texte net au repos).
  useEffect(() => {
    const t = setTimeout(() => setRenderZoom(clamp(Math.ceil(zoom * 2), 2, 5)), 250);
    return () => clearTimeout(t);
  }, [zoom]);

  // Ancrage du zoom : on mémorise le point visé (sous le pointeur, sinon centre du
  // viewport) AVANT le changement, puis on rétablit le scroll APRÈS la nouvelle mise
  // en page -> le PDF ne saute plus verticalement (y compris en question bloquante).
  const zoomAnchorRef = useRef<{ frac: number; focal: number } | null>(null);
  function captureZoomAnchor(focalClientY?: number) {
    const el = scrollRef.current;
    if (!el || el.scrollHeight <= 0) {
      zoomAnchorRef.current = null;
      return;
    }
    const focal = focalClientY != null ? focalClientY - el.getBoundingClientRect().top : el.clientHeight / 2;
    zoomAnchorRef.current = { frac: (el.scrollTop + focal) / el.scrollHeight, focal };
  }
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (locked) {
      // Page bloquée : on garde la page-contexte en haut, sans saut.
      el.querySelector(`[data-page="${lockedPage}"]`)?.scrollIntoView({ block: "start" });
      zoomAnchorRef.current = null;
      return;
    }
    const anchor = zoomAnchorRef.current;
    if (anchor) {
      el.scrollTop = clamp(anchor.frac * el.scrollHeight - anchor.focal, 0, el.scrollHeight - el.clientHeight);
      zoomAnchorRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom]);

  // Borne le décalage horizontal : on peut parcourir un PDF zoomé plus large que le
  // viewport (overflow/2 de chaque côté) PLUS une marge pour le pousser sur le côté.
  function clampPanX(px: number) {
    const vw = scrollRef.current?.clientWidth ?? 0;
    const overflow = Math.max((widthRef.current - vw) / 2, 0);
    const max = overflow + vw * 0.75;
    return clamp(px, -max, max);
  }

  // Zoom fluide à la molette/pincement (Ctrl/Cmd) + déplacement horizontal (molette
  // horizontale du trackpad ou Maj+molette). preventDefault => pas de zoom/navigation
  // navigateur, et le déplacement reste actif même quand le scroll vertical est figé.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        captureZoomAnchor(e.clientY);
        setZoom((z) => clamp(z - e.deltaY * 0.0025, MIN_ZOOM, MAX_ZOOM));
        return;
      }
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault();
        const delta = e.shiftKey ? e.deltaY : e.deltaX;
        setPanX((p) => clampPanX(p - delta));
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // Déplacement horizontal à la souris : on n'amorce le glissé que sur le fond/les
  // marges (jamais sur une page, qui reste sélectionnable). Indépendant du scroll
  // -> fonctionne aussi pendant une question bloquante.
  function startPan(e: React.MouseEvent) {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("[data-page]")) return;
    panDragRef.current = { startX: e.clientX, startPan: panX };
    setPanning(true);
  }
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = panDragRef.current;
      if (d) setPanX(clampPanX(d.startPan + (e.clientX - d.startX)));
    };
    const onUp = () => {
      if (panDragRef.current) {
        panDragRef.current = null;
        setPanning(false);
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // Curseur « main fermée » pendant le glissé, où qu'aille le pointeur.
  useEffect(() => {
    if (!panning) return;
    const prev = document.body.style.cursor;
    document.body.style.cursor = "grabbing";
    return () => {
      document.body.style.cursor = prev;
    };
  }, [panning]);

  // Le zoom change la largeur du PDF -> on reborne le décalage en conséquence.
  useEffect(() => {
    setPanX((p) => clampPanX(p));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom]);

  // Raccourcis clavier Ctrl/Cmd + +/-/0.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        captureZoomAnchor();
        setZoom((z) => clamp(z + 0.2, MIN_ZOOM, MAX_ZOOM));
      } else if (e.key === "-") {
        e.preventDefault();
        captureZoomAnchor();
        setZoom((z) => clamp(z - 0.2, MIN_ZOOM, MAX_ZOOM));
      } else if (e.key === "0") {
        e.preventDefault();
        captureZoomAnchor();
        setZoom(1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Suivi de la page dominante (la plus visible) pour donner le bon contexte à Gemma.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || !data) return;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const p = Number((e.target as HTMLElement).dataset.page);
          ratios.current.set(p, e.intersectionRatio);
        }
        let best = 1;
        let bestRatio = -1;
        ratios.current.forEach((r, p) => {
          if (r > bestRatio) {
            bestRatio = r;
            best = p;
          }
        });
        setCurrentPage(best);
      },
      { root, threshold: [0, 0.25, 0.5, 0.75, 1] },
    );
    root.querySelectorAll("[data-page]").forEach((el) => obs.observe(el));
    return () => obs.disconnect();
    // `isCode` change le rendu des [data-page] -> l'observer doit se rebrancher.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.page_count, isCode]);

  // Démarre une session de lecture à l'ouverture du document.
  useEffect(() => {
    if (!Number.isFinite(id)) return;
    startTimeRef.current = Date.now();
    maxPageRef.current = 1;
    let cancelled = false;
    api.startSession(id).then((r) => !cancelled && setSessionId(r.session_id)).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Suit la page la plus avancée atteinte (pour les métriques de session).
  useEffect(() => {
    if (currentPage > maxPageRef.current) maxPageRef.current = currentPage;
  }, [currentPage]);

  // Charge les mots (calque de texte) de la page dominante et de ses voisines.
  // Inutile en lecture reconstruite : le texte y est nativement sélectionnable.
  useEffect(() => {
    if (!data || isCode) return;
    const pages = [currentPage - 1, currentPage, currentPage + 1].filter(
      (p) => p >= 1 && p <= data.page_count,
    );
    for (const p of pages) {
      if (wordsByPage[p]) continue;
      api
        .pageWords(id, p)
        .then(({ words }) => setWordsByPage((prev) => (prev[p] ? prev : { ...prev, [p]: words })))
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage, data?.page_count, isCode]);

  function computeSelectionRects(pageEl: HTMLElement, page: number, sel: Selection): number[][] {
    const words = wordsByPage[page] || [];
    const spans = pageEl.querySelectorAll<HTMLElement>("[data-wi]");
    const rects: number[][] = [];
    spans.forEach((span) => {
      if (!sel.containsNode(span, true)) return;
      const wi = Number(span.dataset.wi);
      const w = words[wi];
      if (w) rects.push([w[0], w[1], w[2], w[3]]);
    });
    return mergeLineRects(rects);
  }

  // Ancrage texte d'une sélection sur page reconstruite : offsets dans le
  // textContent du bloc porteur (robuste au zoom, indépendant de la géométrie).
  function computeSelectionAnchor(sel: Selection): HighlightAnchor | null {
    const node =
      sel.anchorNode instanceof Element ? sel.anchorNode : sel.anchorNode?.parentElement ?? null;
    const blockEl = node?.closest("[data-block-id]") as HTMLElement | null;
    if (!blockEl || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    const pre = range.cloneRange();
    pre.selectNodeContents(blockEl);
    try {
      pre.setEnd(range.startContainer, range.startOffset);
    } catch {
      return null;
    }
    const start = pre.toString().length;
    return { block_id: blockEl.dataset.blockId ?? "", start, end: start + sel.toString().length };
  }

  // Sélection de texte -> barre flottante (➕ Contexte / 🖊 Surligner).
  useEffect(() => {
    const onUp = (e: MouseEvent) => {
      // Un clic dans la barre elle-même ne doit rien vider (ses boutons
      // consomment la sélection mémorisée avant de la nettoyer).
      if (e.target instanceof Node && toolbarRef.current?.contains(e.target)) return;
      const sel = window.getSelection();
      // Plus rien de sélectionné -> on masque la barre flottante.
      if (!sel || sel.isCollapsed || !sel.rangeCount) {
        setSelection(null);
        return;
      }
      const text = sel.toString().trim();
      if (!text) {
        setSelection(null);
        return;
      }
      const anchorEl =
        sel.anchorNode instanceof Element ? sel.anchorNode : sel.anchorNode?.parentElement ?? null;
      const pageEl = anchorEl?.closest("[data-page]") as HTMLElement | null;
      const rootEl = rootRef.current;
      if (!pageEl || !rootEl) {
        setSelection(null);
        return;
      }
      const page = Number(pageEl.dataset.page);
      const rects = isCode ? [] : computeSelectionRects(pageEl, page, sel);
      const anchor = isCode ? computeSelectionAnchor(sel) : null;
      const rangeRect = sel.getRangeAt(0).getBoundingClientRect();
      const rootRect = rootEl.getBoundingClientRect();
      setSelection({
        text,
        page,
        rects,
        anchor,
        x: rangeRect.left + rangeRect.width / 2 - rootRect.left,
        y: rangeRect.top - rootRect.top,
      });
    };
    document.addEventListener("mouseup", onUp);
    return () => document.removeEventListener("mouseup", onUp);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wordsByPage, isCode]);

  // Marques des pages reconstruites : citations de Gemma + surlignages mémorisés.
  const marksByPage = useMemo(() => {
    if (!isCode) return {};
    const out: Record<number, TextMark[]> = {};
    for (const [p, marks] of Object.entries(quoteMarksByPage)) out[Number(p)] = [...marks];
    for (const hl of savedHighlights) {
      const color = HL_COLORS[hl.color] ?? "var(--hl-key)";
      (out[hl.page] ??= []).push({
        text: hl.quote,
        color: `color-mix(in srgb, ${color} 40%, transparent)`,
        id: hl.id,
      });
    }
    return out;
  }, [isCode, quoteMarksByPage, savedHighlights]);

  // Verrouillage de la lecture pendant une question automatique : on amène la
  // page-contexte dans la vue et on fige le scroll jusqu'à la bonne réponse.
  useEffect(() => {
    if (!locked) return;
    clearSelection();
    const pageEl = scrollRef.current?.querySelector(`[data-page="${lockedPage}"]`);
    pageEl?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [locked, lockedPage]);

  function handleGatedChange(active: boolean, page?: number) {
    if (active && page) setLockedPage(page);
    setLocked(active);
  }

  async function handleEnd() {
    if (sessionId == null) {
      navigate("/");
      return;
    }
    const duration = Math.round((Date.now() - startTimeRef.current) / 1000);
    try {
      setExitMetrics(await api.endSession(sessionId, maxPageRef.current, duration));
    } catch {
      navigate("/");
    }
  }

  function handleExitSasClose() {
    setExitMetrics(null);
    setShowPostExitRest(true);
  }

  const width = BASE_WIDTH * zoom;
  widthRef.current = width;
  const sizes = data?.page_sizes_pts ?? [];

  return (
    <div ref={rootRef} style={{ position: "relative", height: "100%" }}>
      <div
        ref={scrollRef}
        onMouseDown={startPan}
        style={{
          height: "100%",
          // Vertical : figé pendant une question bloquante. Horizontal : jamais de
          // scroll natif, le déplacement passe par `panX` (transform) -> reste actif
          // même verrouillé.
          overflowY: locked ? "hidden" : "auto",
          overflowX: "hidden",
          background: "var(--bg-alt)",
          cursor: panning ? "grabbing" : undefined,
        }}
      >
        {isLoading && <Centered>{t("reader.opening")}</Centered>}
        {isError && <Centered danger>{t("reader.not_found")}</Centered>}

        {data && (
          // Wrapper centré + min-content : le PDF reste centré quand il rentre.
          // Le décalage horizontal (translateX) est porté par la colonne -> on peut
          // pousser le PDF sur le côté (Gemma à droite) même quand il rentre.
          <div style={{ display: "flex", justifyContent: "center", minWidth: "min-content", cursor: "grab" }}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 18,
              padding: "70px 0 40px",
              cursor: "grab",
              transform: `translateX(${panX}px)`,
            }}
          >
            {isCode ? (
              <BlockPages
                docId={id}
                pageCount={data.page_count}
                width={width}
                zoom={zoom}
                currentPage={currentPage}
                sizes={sizes}
                bookmarkPage={bookmarkPage}
                locked={locked}
                lockedPage={lockedPage}
                marksByPage={marksByPage}
                onDeleteHighlight={(hid) => void askRemoveHighlight(hid)}
              />
            ) : (
            Array.from({ length: data.page_count }, (_, i) => i + 1).map((n) => {
              const [w, h] = sizes[n - 1] ?? [595, 842];
              const scale = width / w;
              const words = wordsByPage[n];
              const pageSaved = savedHighlights.filter((hl) => hl.page === n);
              const dimmed = locked && n !== lockedPage;
              return (
                <div
                  key={n}
                  data-page={n}
                  style={{
                    position: "relative",
                    width,
                    aspectRatio: `${w} / ${h}`,
                    background: "var(--surface)",
                    boxShadow: "var(--shadow-md)",
                    borderRadius: 4,
                    overflow: "hidden",
                    cursor: "default",
                    opacity: dimmed ? 0.3 : 1,
                    transition: "opacity 0.2s",
                  }}
                >
                  <img
                    src={pageImageUrl(id, n, renderZoom)}
                    alt={`Page ${n}`}
                    loading="lazy"
                    draggable={false}
                    style={{
                      width: "100%",
                      height: "100%",
                      display: "block",
                      // L'image ne doit jamais capter le drag de sélection (WebKit/pywebview).
                      pointerEvents: "none",
                      userSelect: "none",
                      WebkitUserSelect: "none",
                    }}
                  />
                  {/* Marque-page : ruban sur le bord droit de la page quittée la dernière fois. */}
                  {n === bookmarkPage ? (
                    <div
                      title={t("reader.last_position")}
                      style={{
                        position: "absolute",
                        top: 24,
                        right: 0,
                        width: 10,
                        height: 46,
                        background: "var(--accent)",
                        borderRadius: "3px 0 0 3px",
                        boxShadow: "var(--shadow-sm)",
                        zIndex: 5,
                      }}
                    />
                  ) : null}
                  {highlightsByPage[n]?.length ? (
                    <svg
                      viewBox={`0 0 ${w} ${h}`}
                      preserveAspectRatio="none"
                      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
                    >
                      {highlightsByPage[n].map((g, gi) => (
                        <rect
                          key={gi}
                          x={g.rect[0]}
                          y={g.rect[1]}
                          width={g.rect[2] - g.rect[0]}
                          height={g.rect[3] - g.rect[1]}
                          fill={g.color}
                          opacity={0.35}
                          rx={1}
                        />
                      ))}
                    </svg>
                  ) : null}
                  {/* Rappel libre : cache opaque sur le passage à restituer. Il
                      recouvre le calque de texte, donc on ne peut ni le lire ni
                      le sélectionner tant que la réponse n'est pas donnée. */}
                  {maskByPage[n]?.length ? (
                    <svg
                      viewBox={`0 0 ${w} ${h}`}
                      preserveAspectRatio="none"
                      aria-label={t("qa.recall.masked")}
                      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", zIndex: 6 }}
                    >
                      {maskByPage[n].map((rect, ri) => (
                        <rect
                          key={ri}
                          x={rect[0] - 1}
                          y={rect[1] - 1}
                          width={rect[2] - rect[0] + 2}
                          height={rect[3] - rect[1] + 2}
                          fill="var(--surface-soft)"
                          stroke="var(--border-strong)"
                          strokeDasharray="4 3"
                          rx={3}
                        />
                      ))}
                    </svg>
                  ) : null}
                  {/* Calque de texte transparent : sélection native par-dessus l'image. */}
                  {words ? (
                    <div
                      data-textlayer
                      style={{
                        position: "absolute",
                        inset: 0,
                        cursor: "text",
                        userSelect: "text",
                        WebkitUserSelect: "text",
                      }}
                    >
                      {words.map((wd, wi) => (
                        <span
                          key={wi}
                          data-wi={wi}
                          style={{
                            position: "absolute",
                            left: wd[0] * scale,
                            top: wd[1] * scale,
                            height: (wd[3] - wd[1]) * scale,
                            fontSize: (wd[3] - wd[1]) * scale * 0.86,
                            lineHeight: 1,
                            color: "transparent",
                            whiteSpace: "pre",
                            userSelect: "text",
                            WebkitUserSelect: "text",
                          }}
                        >
                          {wd[4]}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {/* Surlignages mémorisés (cliquables pour suppression). */}
                  {pageSaved.length ? (
                    <svg
                      viewBox={`0 0 ${w} ${h}`}
                      preserveAspectRatio="none"
                      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
                    >
                      {pageSaved.map((hl) =>
                        mergeLineRects(hl.rects).map((r, ri) => (
                          <rect
                            key={`${hl.id}-${ri}`}
                            x={r[0]}
                            y={r[1]}
                            width={r[2] - r[0]}
                            height={r[3] - r[1]}
                            fill={HL_COLORS[hl.color] ?? "var(--hl-key)"}
                            opacity={0.32}
                            rx={1}
                            style={{ pointerEvents: "all", cursor: "pointer" }}
                            onClick={() => void askRemoveHighlight(hl.id)}
                          />
                        )),
                      )}
                    </svg>
                  ) : null}
                </div>
              );
            })
            )}
          </div>
          </div>
        )}
      </div>

      {/* Barre supérieure flottante */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "12px 18px",
          background: "color-mix(in srgb, var(--surface) 88%, transparent)",
          backdropFilter: "blur(8px)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <button
          onClick={handleEnd}
          style={{
            cursor: "pointer",
            color: "var(--text-soft)",
            fontWeight: 600,
            fontSize: 13,
            padding: "6px 12px",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border)",
            background: "var(--surface)",
          }}
        >
          {t("reader.end")}
        </button>
        <span style={{ fontWeight: 600, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {data?.title ?? ""}
        </span>
        {data && (
          <span style={{ color: "var(--muted)", fontSize: 13, whiteSpace: "nowrap" }}>
            {t("reader.page", { cur: currentPage, total: data.page_count })}
          </span>
        )}
      </div>

      {/* Contrôles de zoom */}
      <ZoomControls
        zoom={zoom}
        onChange={(z) => {
          captureZoomAnchor();
          setZoom(clamp(z, MIN_ZOOM, MAX_ZOOM));
        }}
        onReset={() => {
          captureZoomAnchor();
          setZoom(1);
        }}
      />

      {/* Barre flottante au-dessus d'une sélection de texte. */}
      {selection && (
        <div
          ref={toolbarRef}
          style={{
            position: "absolute",
            left: clamp(selection.x, 80, (rootRef.current?.clientWidth ?? 800) - 80),
            top: Math.max(8, selection.y - 44),
            transform: "translateX(-50%)",
            display: "flex",
            gap: 6,
            padding: 4,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-md)",
            boxShadow: "var(--shadow-lg)",
            zIndex: 60,
          }}
          onMouseDown={(e) => e.preventDefault()}
        >
          <button style={selBtn} onClick={addSelectionToContext}>
            {t("reader.add_context")}
          </button>
          <button style={selBtn} onClick={highlightSelection}>
            {t("reader.highlight")}
          </button>
        </div>
      )}

      {/* Bannière de question bloquante. */}
      {locked && (
        <div
          style={{
            position: "absolute",
            top: 64,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "8px 16px",
            background: "var(--accent)",
            color: "#fff",
            borderRadius: 999,
            fontSize: 13,
            fontWeight: 600,
            boxShadow: "var(--shadow-md)",
            zIndex: 40,
          }}
        >
          {t("reader.gated_banner")}
        </div>
      )}

      {/* Assistant déplaçable connecté à Gemma */}
      <GemmaPanel
        docId={id}
        currentPage={currentPage}
        sessionId={sessionId}
        onHighlights={handleHighlights}
        contextChips={contextChips}
        onRemoveContextChip={removeContextChip}
        onGatedChange={handleGatedChange}
        onMask={handleMask}
      />

      {data && !entered && <EntrySas docId={id} title={data.title} onStart={() => setEntered(true)} />}

      {exitMetrics && <ExitSas metrics={exitMetrics} onClose={handleExitSasClose} />}

      {showPostExitRest && <PostExitRestSas onDone={() => navigate("/")} />}
    </div>
  );
}

function ZoomControls({ zoom, onChange, onReset }: { zoom: number; onChange: (z: number) => void; onReset: () => void }) {
  const btn: React.CSSProperties = {
    width: 34,
    height: 34,
    border: "1px solid var(--border)",
    background: "var(--surface)",
    color: "var(--text)",
    borderRadius: "var(--radius-sm)",
    cursor: "pointer",
    fontSize: 16,
    fontWeight: 700,
  };
  return (
    <div
      style={{
        position: "absolute",
        left: 18,
        bottom: 18,
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: 6,
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-md)",
      }}
    >
      <button style={btn} onClick={() => onChange(zoom - 0.2)} title="Dézoomer (Ctrl -)">
        −
      </button>
      <button
        onClick={onReset}
        title="Réinitialiser (Ctrl 0)"
        style={{ minWidth: 52, height: 34, border: "none", background: "transparent", cursor: "pointer", fontWeight: 600, fontSize: 13 }}
      >
        {Math.round(zoom * 100)}%
      </button>
      <button style={btn} onClick={() => onChange(zoom + 0.2)} title="Zoomer (Ctrl +)">
        +
      </button>
    </div>
  );
}

function Centered({ children, danger }: { children: React.ReactNode; danger?: boolean }) {
  return (
    <div style={{ display: "grid", placeItems: "center", height: "100%", color: danger ? "var(--danger)" : "var(--muted)" }}>
      {children}
    </div>
  );
}
