import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NotebookPen, Search, StickyNote } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api } from "../api/client";
import type { DocumentDetail, Highlight, HighlightAnchor, PageWord, ReaderNote, SessionMetrics } from "../api/types";
import type { TextMark } from "../features/reader/anchorText";
import { AnnotationPopover, annotationSelector, type EditingTarget } from "../features/reader/annotations/AnnotationPopover";
import {
  clampNotebookWidth,
  loadNotebookWidth,
  NotebookDrawer,
  saveNotebookWidth,
  type NotebookTarget,
} from "../features/reader/annotations/NotebookDrawer";
import { labelColor, labelName } from "../features/reader/annotations/palette";
import { loadToolPrefs, saveToolPrefs, SelectionToolbar } from "../features/reader/annotations/SelectionToolbar";
import { useAnnotations } from "../features/reader/annotations/useAnnotations";
import { ClikodaPanel, type QaMask } from "../features/reader/ClikodaPanel";
import { DEMO_METRICS, DEMO_REFLECTION_KEYS, type DemoBeat } from "../features/reader/demoScript";
import { BlockPages } from "../features/reader/BlockPages";
import { FindBar } from "../features/reader/find/FindBar";
import { isMacPlatform } from "../features/reader/find/findNav";
import { useReaderFind } from "../features/reader/find/useReaderFind";
import { boundsOf, frameRect, type PageGeometry } from "../features/reader/frame";
import { NO_HITS, NO_NOTES, PdfPage, ZONE_PAD_PTS, type SavedPageHighlight } from "../features/reader/PdfPage";
import { ReaderToolbar, ToolbarIconButton } from "../features/reader/ReaderToolbar";
import { buildQuote } from "../features/reader/selectionQuote";
import { placedBoxes } from "../features/reader/textLayer";
import { selectedWordIndices } from "../features/reader/textSelection";
import { useStableCallback } from "../features/reader/useStableCallback";
import { EntrySas } from "../features/session/EntrySas";
import { ExitSas } from "../features/session/ExitSas";
import type { WarmUpTiming } from "../features/session/WarmUp";
import { PauseSas, type ReadingPause } from "../features/session/PauseSas";
import { currentStep, useTour } from "../features/tour/useTour";
import { PostExitRestSas } from "../features/session/PostExitRestSas";
import { useLangStore, useT } from "../i18n";

// Couleurs des passages que CLIKODA cite (`purpose` de sa réponse). Les
// surlignages de l'élève suivent leur étiquette (annotations/palette).
const HL_COLORS: Record<string, string> = {
  key: "var(--hl-key)",
  explain: "var(--hl-explain)",
  reference: "var(--hl-reference)",
};

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const BASE_WIDTH = 820;
const INITIAL_ZOOM = 1;
// Zoom par geste (molette + Ctrl/Cmd, pincement) : la colonne est mise à
// l'échelle en CSS pendant le geste, et la vraie largeur n'est écrite qu'après
// ce temps sans nouvel événement — une seule re-mise en page par geste.
const GESTURE_IDLE_MS = 150;

// Cadrage de la zone d'une question : ce qu'il faut laisser libre autour pour
// qu'elle soit VISIBLE et non simplement dans le viewport — la barre d'outils
// et la bannière de blocage recouvrent le haut du cadre.
const ZONE_TOP_INSET = 112;
const ZONE_BOTTOM_INSET = 24;
const ZONE_SIDE_INSET = 24;
// Durée d'un défilement décidé par le lecteur (cadrage animé de la zone) : le
// garde-fou du plancher le laisse finir au lieu de le ramener en arrière.
const PROGRAMMATIC_SCROLL_MS = 800;
// Marge au-dessus de la première page : la barre d'outils flotte là. Une page
// amenée en haut de la vue (ouverture sur le marque-page) garde cette marge.
const COLUMN_PAD_TOP = 70;
// Ouverture sur le marque-page : la position est tenue au plus ce temps, ou
// jusqu'au premier geste (cf. l'effet d'ouverture).
const OPEN_HOLD_MS = 2000;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Palier de résolution des images de page pour un zoom (texte net au repos). */
const renderZoomFor = (zoom: number) => clamp(Math.ceil(zoom * 2), 2, 5);

/** Une page sans surlignage mémorisé : la même liste à chaque rendu (PdfPage est mémoïsée). */
const NO_SAVED: SavedPageHighlight[] = [];

/** Pincement du trackpad sous WebKit (WKWebView de pywebview, Safari) : pas de molette Ctrl. */
interface WebKitGestureEvent extends UIEvent {
  scale: number;
  clientX: number;
  clientY: number;
}

/** Distance qu'une touche ferait descendre le défilement natif (null : elle ne descend pas). */
function scrollKeyStep(e: KeyboardEvent, el: HTMLElement): number | null {
  const page = el.clientHeight * 0.85;
  switch (e.key) {
    case "ArrowDown":
      return e.metaKey || e.ctrlKey ? Infinity : e.altKey ? page : 40;
    case "PageDown":
      return page;
    case " ":
      return e.shiftKey ? null : page;
    case "End":
      return Infinity;
    default:
      return null;
  }
}

/** Delta vertical d'une molette, en pixels quel que soit son mode. */
function wheelPixels(e: WheelEvent, el: HTMLElement): number {
  if (e.deltaMode === 1) return e.deltaY * 16;
  if (e.deltaMode === 2) return e.deltaY * el.clientHeight;
  return e.deltaY;
}

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

/** Durée du clignotement d'un élément désigné par le carnet (cf. `note-flash`). */
const FLASH_MS = 1400;

export function Reader() {
  const { docId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const t = useT();
  // `prefers-reduced-motion` est neutralisé en CSS, mais Motion anime en JS :
  // la règle CSS ne l'atteint pas (même raison que dans AppLayout).
  const reduceMotion = useReducedMotion();
  const id = Number(docId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);

  const [sessionId, setSessionId] = useState<number | null>(null);
  // Sas de sortie : `null` tant qu'on lit. Au clic sur « Terminer », il
  // s'ouvre avec `metrics: null` — la clôture (`endSession`) répond ensuite et
  // remplit les chiffres. Le lecteur n'a donc jamais à attendre le serveur.
  const [exit, setExit] = useState<{ sessionId: number; metrics: SessionMetrics | null } | null>(null);
  const [showPostExitRest, setShowPostExitRest] = useState(false);
  const [entered, setEntered] = useState(false);
  // Le rythme de la révision éclair, remis à Clikoda à l'entrée en lecture.
  const [warmup, setWarmup] = useState<WarmUpTiming[]>([]);
  // 0 = pas encore monté ; la vraie valeur est posée par l'effet de démarrage de session.
  const startTimeRef = useRef(0);
  // Pause en cours (bouton « Pause » ou carte de Clikoda acceptée) : le PDF est
  // masqué, la vue figée, et le serveur ne mesure plus rien jusqu'à la reprise.
  // Le temps cumulé des pauses est retiré de la durée de la séance.
  const [pause, setPause] = useState<ReadingPause | null>(null);
  const pausedMsRef = useRef(0);

  const [zoom, setZoom] = useState(INITIAL_ZOOM);
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  // Décalage horizontal du PDF (px). Découplé du scroll natif (transform) -> reste
  // utilisable quelle que soit la borne du scroll vertical (question bloquante de
  // Clikoda), et permet de pousser le PDF à gauche pour loger Clikoda à droite.
  const [panX, setPanX] = useState(0);
  const panXRef = useRef(panX);
  panXRef.current = panX;
  const [panning, setPanning] = useState(false);
  const panDragRef = useRef<{ startX: number; startPan: number } | null>(null);
  // Décalage en attente de la prochaine frame : glissé et molette horizontale
  // émettent bien plus d'événements que l'écran n'affiche d'images — un rendu
  // par frame, pas un par événement.
  const panFrameRef = useRef<{ raf: number; value: number } | null>(null);
  // La colonne des pages : c'est elle que le zoom par geste met à l'échelle.
  const columnRef = useRef<HTMLDivElement>(null);
  // Geste de zoom en cours (molette + Ctrl/Cmd, pincement). `base` : le zoom
  // réel au départ ; `target` : celui que vise le geste ; `origin` : le point
  // visé dans la colonne, qui reste immobile ; `fx`/`fxr` : ce point à l'écran
  // et sa part de la largeur de la colonne, pour le garder en place au
  // moment où la vraie largeur est écrite.
  const gestureRef = useRef<{
    base: number;
    target: number;
    originX: number;
    originY: number;
    fx: number;
    fxr: number;
    raf: number;
    idle: number;
  } | null>(null);
  // Fin de geste à appliquer par l'effet de zoom (horizontal : cf. gestureRef).
  const gestureEndRef = useRef<{ fx: number; fxr: number } | null>(null);
  const widthRef = useRef(BASE_WIDTH);
  // Initialisé depuis le zoom de départ : partir de 2.5 puis passer au palier
  // du zoom faisait charger chaque page deux fois à l'ouverture.
  const [renderZoom, setRenderZoom] = useState(() => renderZoomFor(INITIAL_ZOOM));
  const [currentPage, setCurrentPage] = useState(1);
  // Dernière position : page quittée à la session précédente (figée à
  // l'ouverture, > 1 seulement). Un ruban la signale, sans marque-page posé.
  const [lastPositionPage, setLastPositionPage] = useState<number | null>(null);
  // Marque-page de l'élève (v44), un seul par document, qui se déplace. Lu une
  // fois à l'ouverture, puis tenu ici et recopié dans le cache du document.
  const [bookmark, setBookmark] = useState<number | null>(null);
  // La page où le lecteur s'ouvre : le marque-page à l'ouverture, sinon 1.
  // Figée — le sas en tire son accroche, et la déplacer ensuite ne rouvre rien.
  // null tant que le document n'est pas chargé.
  const [openPage, setOpenPage] = useState<number | null>(null);
  const bookmarkSeqRef = useRef(0);
  const ratios = useRef<Map<number, number>>(new Map());
  const [highlightsByPage, setHighlightsByPage] = useState<Record<number, { rect: number[]; color: string }[]>>({});

  // Calque de texte transparent (sélection native).
  const [wordsByPage, setWordsByPage] = useState<Record<number, PageWord[]>>({});
  // Citations de Clikoda sur pages reconstruites (marquées par recherche pliée).
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
  // Extraits ajoutés au contexte du LLM : ils partent avec la prochaine question
  // posée à Clikoda, s'affichent dans sa bulle, puis la liste se vide
  // (`onContextConsumed`) — la question suivante part sans eux.
  const [contextChips, setContextChips] = useState<{ id: number; page: number; text: string }[]>([]);
  // Question automatique bloquante : la lecture ne descend plus sous la page-contexte.
  const [locked, setLocked] = useState(false);
  const [lockedPage, setLockedPage] = useState(1);
  // Zone précise visée par la question en cours (boîte en points PDF) : on la
  // cadre ENTIÈRE à l'écran et on l'encadre d'un liseré, jusqu'à ce que la
  // carte se referme. Elle vient d'une citation retrouvée sur la page
  // (même chemin que le masque et les surlignages : api.searchPage).
  const [zone, setZone] = useState<{ page: number; rect: number[] } | null>(null);
  // Plancher de la question bloquante : le scrollTop qui cadre sa zone (à
  // défaut, le haut de la page bloquée). Au-dessus, on peut remonter relire ;
  // en dessous, on ne descend pas. null hors verrou.
  const lockFloorRef = useRef<number | null>(null);
  // Fin du dernier défilement décidé par le lecteur (cf. PROGRAMMATIC_SCROLL_MS).
  const programmaticUntilRef = useRef(0);
  // « ← Bibliothèque » cliqué avant que la session ne soit ouverte : on
  // l'abandonne dès qu'elle arrive, sinon elle resterait orpheline.
  const leftRef = useRef(false);
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
      const rects = await locateMask(page, mask.quote);
      // Passage introuvable (extraction ≠ rendu) : plutôt que de cacher la page
      // entière, on laisse la question posée — elle reste jouable, en plus facile.
      if (rects.length) setMaskByPage({ [page]: rects });
    } catch {
      /* rien à masquer : dégradation silencieuse, comme pour les citations */
    }
  }

  /**
   * Géométrie du cache d'un rappel libre. Même recherche que `locateQuote`,
   * mais quand la citation entière bute (ligature, césure, tiret) on ne peut
   * pas se contenter de ses deux extrémités : les lignes du milieu resteraient
   * lisibles, et le cache serait « transparent ». On renvoie alors l'enveloppe
   * du début et de la fin — un seul rectangle qui couvre tout le paragraphe,
   * quitte à déborder un peu sur les voisins.
   */
  async function locateMask(page: number, quote: string): Promise<number[][]> {
    const full = mergeLineRects((await api.searchPage(id, page, quote)).rects_pts);
    if (full.length) return full;
    const head = quote.slice(0, 60).trim();
    const tail = quote.slice(-60).trim();
    if (!head) return [];
    const [a, b] = await Promise.all([
      api.searchPage(id, page, head),
      tail && tail !== head ? api.searchPage(id, page, tail) : Promise.resolve({ rects_pts: [] as number[][] }),
    ]);
    const parts = [...a.rects_pts, ...b.rects_pts].filter((r) => r.length >= 4);
    if (!parts.length) return [];
    return [[
      Math.min(...parts.map((r) => r[0])),
      Math.min(...parts.map((r) => r[1])),
      Math.max(...parts.map((r) => r[2])),
      Math.max(...parts.map((r) => r[3])),
    ]];
  }

  /**
   * Localise la citation d'une zone sur sa page. PDFium retrouve un passage
   * qui court sur plusieurs lignes, mais une citation longue peut buter sur
   * un détail d'extraction (ligature, césure) : on retombe alors sur son début
   * et sa fin, dont l'union donne la même boîte.
   */
  async function locateQuote(page: number, quote: string): Promise<number[][]> {
    const full = mergeLineRects((await api.searchPage(id, page, quote)).rects_pts);
    if (full.length || quote.length < 80) return full;
    const head = quote.slice(0, 60).trim();
    const tail = quote.slice(-60).trim();
    const [a, b] = await Promise.all([api.searchPage(id, page, head), api.searchPage(id, page, tail)]);
    return mergeLineRects([...a.rects_pts, ...b.rects_pts]);
  }

  async function handleZone(quote: string | null, page: number) {
    // Lecture reconstruite (fichier de code) : pas de géométrie, la page fait zone.
    if (!quote || isCode) {
      setZone(null);
      return;
    }
    try {
      const rects = await locateQuote(page, quote);
      setZone(rects.length ? { page, rect: boundsOf(rects) } : null);
    } catch {
      setZone(null); // introuvable : on cadre le haut de page, comme avant
    }
  }

  async function handleHighlights(items: Highlight[], page: number) {
    // Lecture reconstruite : les citations sont localisées par recherche pliée
    // dans le texte des blocs (anchorText), pas par géométrie PDFium.
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

  // Action « ➕ Contexte » : mémorise l'extrait pour la prochaine question.
  function addSelectionToContext() {
    if (!selection) return;
    setContextChips((prev) => [...prev, { id: Date.now(), page: selection.page, text: selection.text }]);
    clearSelection();
  }

  /** Un extrait de plus pour la prochaine question à Clikoda (« Ajouter au
   *  contexte » d'un surlignage, qu'on ne peut plus sélectionner). */
  function addToContext(page: number, text: string) {
    setContextChips((prev) => [...prev, { id: Date.now(), page, text }]);
  }

  // Surligner la sélection avec une étiquette, dans le style choisi : elle
  // réapparaît à la réouverture. Document raster : ancrage par rects (points
  // PDF). Fichier de code : ancrage TEXTE {block_id, start, end} + quote
  // (rects vides). `openNote` : « Note » de la barre — l'édition s'ouvre,
  // le champ de la note pris.
  async function highlightSelection(labelId: number | null, openNote = false) {
    if (!selection) return clearSelection();
    if (!isCode && !selection.rects.length) return clearSelection();
    const { page, text, rects, anchor } = selection;
    clearSelection();
    const created = await annotations.createHighlight({ page, quote: text, rects, anchor, labelId, style: tool.style });
    if (created && openNote) setEditing({ kind: "highlight", id: created.id, focusNote: true });
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

  // ── Séance de démonstration de la visite guidée ─────────────────────────
  //
  // Ce document est celui que la visite a emprunté au serveur le temps de son
  // chapitre lecture. Tout ce qui écrirait quelque chose est débranché : pas de
  // session ouverte, pas de WebSocket, pas d'appel LLM, pas de finalisation.
  // C'est la garantie « la visite ne compte pas dans ton profil », tenue par ce
  // qu'on n'appelle pas plutôt que par un drapeau à respecter partout.
  // Figé À L'OUVERTURE, et non recalculé à chaque rendu. La visite rend le
  // document de démonstration en quittant le chapitre lecture, donc `demoDocId`
  // repasse à `null` alors que ce composant est encore monté une frame. Une
  // valeur réactive basculerait à `false` à cet instant précis et relancerait
  // les deux effets qu'elle gardait : ouverture d'une vraie session et d'un
  // WebSocket — sur un document qui vient d'être supprimé.
  const [demo] = useState(() => useTour.getState().demoDocId === id);
  const setTourControls = useTour((s) => s.setControls);
  // Chapitre lecture de la visite : la vue ne bouge plus. Défilement, molette et
  // glissé horizontal sont neutralisés — la découpe du voile est calculée à
  // partir de la position des éléments à l'écran, et tout ce qui les déplace
  // pendant qu'on lit la bulle la décale d'autant. On cale la vue une fois
  // (`pinPassage`), puis plus rien ne la déplace.
  const tourRunning = useTour((s) => s.running);
  // La pause fige la vue de la même façon : rien ne doit bouger derrière le voile.
  const frozen = (demo && tourRunning) || pause !== null;
  const frozenRef = useRef(frozen);
  frozenRef.current = frozen;
  const clikodaControls = useRef<{ openPanel: () => void; play: (beat: DemoBeat) => void } | null>(null);
  // Les métriques du sas de sortie sont inventées : elles décrivent une lecture
  // plausible, pas une mesure. Les intitulés de réflexion sont traduits ici,
  // `demoScript.ts` ne portant que leurs clés.
  //
  // Passées par une `ref` et non par une dépendance d'effet : `useT()` renvoie
  // une NOUVELLE fonction à chaque rendu, donc un `useMemo` sur `[t]` produirait
  // un objet différent à chaque fois et rebrancherait les contrôles de la visite
  // en boucle — avec, entre le nettoyage et la repose, une fenêtre où ils sont
  // nuls. Même idiome que les `onHighlightsRef` du panneau Clikoda.
  const demoMetricsRef = useRef(DEMO_METRICS);
  demoMetricsRef.current = {
    ...DEMO_METRICS,
    reflection_questions: DEMO_REFLECTION_KEYS.slice(0, 2).map((k) => t(k)),
  };

  const handleDemoReady = useCallback(
    (controls: { openPanel: () => void; play: (beat: DemoBeat) => void } | null) => {
      clikodaControls.current = controls;
    },
    [],
  );

  // La visite pilote le lecteur d'ici : ouvrir Clikoda, jouer une réplique, faire
  // apparaître le sas de sortie. Elle ne peut le faire que tant qu'il est monté.
  useEffect(() => {
    if (!demo) return;
    setTourControls({
      // Le sas d'entrée recouvre la page : sans ce passage explicite, l'étape
      // suivante s'ancrerait sur une page cachée derrière son voile.
      enterReading: () => setEntered(true),
      // Le bas de la première page : c'est là que vit la section que Clikoda
      // cite, et donc ce que les sept étapes suivantes commentent. Aligné sur
      // le bas du cadre plutôt que centré — la page suivante n'a rien à faire
      // à l'écran pendant qu'on parle de celle-ci.
      pinPassage: () => {
        const view = scrollRef.current;
        const page = view?.querySelector<HTMLElement>('[data-page="1"]');
        if (!view || !page) return;
        view.scrollTop += page.getBoundingClientRect().bottom - view.getBoundingClientRect().bottom;
      },
      openPanel: () => clikodaControls.current?.openPanel(),
      play: (beat) => clikodaControls.current?.play(beat),
      endSession: () => setExit({ sessionId: DEMO_METRICS.session_id, metrics: demoMetricsRef.current }),
      closeExitSas: () => {
        setExit(null);
        setShowPostExitRest(true);
      },
    });
    return () => setTourControls(null);
  }, [demo, setTourControls]);

  // ── Prise de notes ─────────────────────────────────────────────────────
  //
  // Surlignages (étiquette, style, note), post-it et signets du document, et
  // les étiquettes de l'élève. En lecture seule pendant la visite : rien n'y
  // est écrit, et ni carnet, ni post-it, ni signet n'y sont proposés.
  const annotations = useAnnotations(id, { readOnly: demo });
  const lang = useLangStore((s) => s.lang);
  // Le dernier style et la dernière étiquette de la barre de sélection.
  const [tool, setTool] = useState(loadToolPrefs);
  function chooseTool(next: typeof tool) {
    setTool(next);
    saveToolPrefs(next);
  }
  // L'étiquette retenue, si elle existe encore ; sinon la première.
  const toolLabel =
    tool.labelId !== null && annotations.labelsById.has(tool.labelId) ? tool.labelId : (annotations.labels[0]?.id ?? null);
  // L'élément en cours d'édition (popover sur la page).
  const [editing, setEditing] = useState<EditingTarget | null>(null);
  const closeEditing = useCallback(() => setEditing(null), []);
  // Les mêmes fonctions d'un rendu à l'autre : les pages sont mémoïsées.
  const editHighlight = useStableCallback((hid: number) => setEditing({ kind: "highlight", id: hid }));
  const editNote = useStableCallback((nid: number) => setEditing({ kind: "note", id: nid }));
  const [notebookOpen, setNotebookOpen] = useState(false);
  // Largeur du carnet, réglée par sa poignée et retenue dans le navigateur.
  const [notebookWidth, setNotebookWidth] = useState(loadNotebookWidth);
  const resizeNotebook = useCallback((width: number, done: boolean) => {
    setNotebookWidth(width);
    if (done) saveNotebookWidth(width);
  }, []);
  // Une fenêtre qui rétrécit ne doit pas laisser le carnet manger le document.
  useEffect(() => {
    const onResize = () => setNotebookWidth((width) => clampNotebookWidth(width));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  // Largeur que Clikoda, ancrée à droite, prend au document (0 sinon).
  const [clikodaDock, setClikodaDock] = useState(0);
  // Pose d'un post-it : le prochain clic sur une page le pose là.
  const [placing, setPlacing] = useState(false);
  // L'élément que le carnet vient de désigner, qui clignote sur sa page.
  const [flash, setFlash] = useState<{ page: number; key: string } | null>(null);
  useEffect(() => {
    if (!flash) return;
    const timer = window.setTimeout(() => setFlash(null), FLASH_MS);
    return () => window.clearTimeout(timer);
  }, [flash]);

  // Surlignages mémorisés groupés par page, rects fusionnés par ligne, couleur
  // et nom d'étiquette résolus une fois pour toutes — et non à chaque rendu de
  // chaque page. Le nom dépend de la langue (`lang`), pas de `t`, qui change à
  // chaque rendu.
  const savedByPage = useMemo(() => {
    const out: Record<number, SavedPageHighlight[]> = {};
    for (const hl of annotations.highlights) {
      const label = hl.label_id !== null ? annotations.labelsById.get(hl.label_id) : null;
      (out[hl.page] ??= []).push({
        id: hl.id,
        fill: labelColor(label),
        style: hl.style,
        rects: mergeLineRects(hl.rects),
        note: hl.note,
        labelName: labelName(label, lang),
      });
    }
    return out;
  }, [annotations.highlights, annotations.labelsById, lang]);
  const notesByPage = useMemo(() => {
    const out: Record<number, ReaderNote[]> = {};
    for (const note of annotations.notes) (out[note.page] ??= []).push(note);
    return out;
  }, [annotations.notes]);

  // Dernière position : on fige la page quittée au tout premier chargement (valeur de
  // la session précédente, écrite en fin de session côté backend). On ignore la page 1
  // (document jamais lu) où le repère n'aurait pas de sens.
  useEffect(() => {
    if (data && lastPositionPage === null && (data.last_page ?? 1) > 1) {
      setLastPositionPage(data.last_page);
    }
  }, [data, lastPositionPage]);

  // Marque-page et page d'ouverture, lus au premier chargement du document.
  // Pendant la visite, ni l'un ni l'autre : elle s'ouvre en page 1, toujours.
  if (data && openPage === null) {
    const marked = demo ? null : (data.bookmark_page ?? null);
    setBookmark(marked);
    setOpenPage(marked ?? 1);
  }

  // Ouverture sur le marque-page : on amène sa page en haut de la vue, sans
  // animation, pendant le sas — l'accroche porte sur elle et la lecture y
  // commence. Puis on TIENT la position jusqu'au premier geste (molette,
  // toucher, clic, touche), OPEN_HOLD_MS au plus : WKWebView n'ancre pas le
  // défilement, et une page de code change de hauteur en chargeant ses blocs —
  // la page marquée glissait hors de la vue. Ne dépend que de `openPage`, posé
  // une fois : les autres rendus ne la relancent pas.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const col = columnRef.current;
    if (openPage === null || openPage <= 1 || !el || !col) return;
    const jump = () => {
      const pageEl = el.querySelector<HTMLElement>(`[data-page="${openPage}"]`);
      if (!pageEl) return;
      const top = pageEl.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop;
      scrollViewTo(Math.max(0, top - COLUMN_PAD_TOP), "auto");
    };
    jump();
    const held = new ResizeObserver(jump);
    held.observe(col);
    const gestures = ["wheel", "touchstart", "pointerdown"] as const;
    const release = () => {
      held.disconnect();
      window.clearTimeout(timer);
      for (const ev of gestures) el.removeEventListener(ev, release);
      window.removeEventListener("keydown", release);
    };
    const timer = window.setTimeout(release, OPEN_HOLD_MS);
    for (const ev of gestures) el.addEventListener(ev, release, { passive: true });
    window.addEventListener("keydown", release);
    return release;
  }, [openPage]);

  /** Pose le marque-page sur `page`, ou l'y retire s'il y est. Optimiste : le
   *  bouton répond tout de suite, l'échec le remet où il était. Le cache du
   *  document suit — sans lui, rouvrir le lecteur le relirait et s'ouvrirait sur
   *  l'ancien marque-page —, et la bibliothèque (carte « Reprendre ») aussi. */
  const toggleBookmark = useStableCallback((page: number) => {
    const before = bookmark;
    const next = before === page ? null : page;
    const seq = ++bookmarkSeqRef.current;
    const write = (value: number | null) => {
      setBookmark(value);
      queryClient.setQueryData<DocumentDetail>(["document", id], (d) => (d ? { ...d, bookmark_page: value } : d));
    };
    write(next);
    api.setBookmark(id, next).then(
      () => queryClient.invalidateQueries({ queryKey: ["library"] }),
      () => {
        // Un geste plus récent a déjà décidé : ne pas l'écraser.
        if (seq !== bookmarkSeqRef.current) return;
        write(before);
        toast.error(t("reader.bookmark_error"));
      },
    );
  });
  // Visite guidée : pas de bouton (le document de démonstration est éphémère).
  const onToggleBookmark = demo ? undefined : toggleBookmark;

  // Re-rendu HD à palier quand le zoom se stabilise (texte net au repos).
  useEffect(() => {
    const t = setTimeout(() => setRenderZoom(renderZoomFor(zoom)), 250);
    return () => clearTimeout(t);
  }, [zoom]);

  // Ancrage du zoom : on mémorise le point visé (sous le pointeur, sinon centre du
  // viewport) AVANT le changement, puis on rétablit le scroll APRÈS la nouvelle mise
  // en page -> le PDF ne saute plus verticalement (y compris en question bloquante).
  // Le point visé est repéré dans la PAGE qu'il touche (`page`, `pageFrac`) :
  // les marges et les intervalles entre pages ne grandissent pas avec le zoom,
  // si bien qu'une simple fraction de la hauteur totale (`frac`, le repli)
  // faisait glisser le point visé de plusieurs dizaines de pixels.
  const zoomAnchorRef = useRef<{
    frac: number;
    focal: number;
    aboveFloor: boolean;
    page: number | null;
    pageFrac: number;
  } | null>(null);
  function captureZoomAnchor(focalClientY?: number) {
    const el = scrollRef.current;
    if (!el || el.scrollHeight <= 0) {
      zoomAnchorRef.current = null;
      return;
    }
    const elTop = el.getBoundingClientRect().top;
    const focal = focalClientY != null ? focalClientY - elTop : el.clientHeight / 2;
    const floor = lockFloorRef.current;
    let page: number | null = null;
    let pageFrac = 0;
    for (const pageEl of el.querySelectorAll<HTMLElement>("[data-page]")) {
      const r = pageEl.getBoundingClientRect();
      if (r.bottom < elTop + focal) continue;
      if (r.top <= elTop + focal && r.height > 0) {
        page = Number(pageEl.dataset.page);
        pageFrac = (elTop + focal - r.top) / r.height;
      }
      break;
    }
    zoomAnchorRef.current = {
      frac: (el.scrollTop + focal) / el.scrollHeight,
      focal,
      aboveFloor: floor !== null && el.scrollTop < floor - 2,
      page,
      pageFrac,
    };
  }

  /** scrollTop qui remet le point visé (cf. captureZoomAnchor) à sa place après une mise en page. */
  function anchoredScrollTop(el: HTMLElement, anchor: NonNullable<typeof zoomAnchorRef.current>): number {
    const max = Math.max(0, el.scrollHeight - el.clientHeight);
    const pageEl = anchor.page !== null ? el.querySelector<HTMLElement>(`[data-page="${anchor.page}"]`) : null;
    if (pageEl) {
      const r = pageEl.getBoundingClientRect();
      const point = r.top - el.getBoundingClientRect().top + anchor.pageFrac * r.height;
      return clamp(el.scrollTop + point - anchor.focal, 0, max);
    }
    return clamp(anchor.frac * el.scrollHeight - anchor.focal, 0, max);
  }
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // Fin d'un geste : la vraie largeur vient d'être écrite, l'échelle CSS qui
    // la simulait tombe dans la même frame — aucune image intermédiaire.
    const col = columnRef.current;
    const gestureEnd = gestureEndRef.current;
    gestureEndRef.current = null;
    if (col) {
      col.style.transform = `translateX(${panXRef.current}px)`;
      col.style.transformOrigin = "";
      if (gestureEnd) {
        // Le point visé reste sous le pointeur horizontalement aussi : sans ce
        // décalage, la colonne retomberait sur son centrage.
        const rect = col.getBoundingClientRect();
        const next = clampPanX(gestureEnd.fx - gestureEnd.fxr * rect.width - (rect.left - panXRef.current));
        col.style.transform = `translateX(${next}px)`;
        panXRef.current = next;
        setPanX(next);
      }
    }
    const anchor = zoomAnchorRef.current;
    zoomAnchorRef.current = null;
    const anchored = anchor ? anchoredScrollTop(el, anchor) : null;
    if (locked) {
      // Page bloquée, remontée relire : le zoom garde le point visé, sous le
      // plancher recalculé à la nouvelle échelle.
      const frame = anchor?.aboveFloor ? lockFrame() : null;
      if (frame && anchored !== null) {
        lockFloorRef.current = frame.top;
        el.scrollTop = Math.min(anchored, frame.top);
        return;
      }
      // Sinon la zone (à défaut, la page-contexte) reste cadrée à travers le
      // zoom, sans saut. `fit: false` : c'est l'utilisateur qui zoome, on ne
      // lui reprend pas la main — on garde seulement la zone dans la vue.
      frameZone("auto", false);
      return;
    }
    if (anchored !== null) el.scrollTop = anchored;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom]);

  /** Défilement décidé par le lecteur, pas par l'élève : le garde-fou du plancher le laisse finir. */
  function scrollViewTo(top: number, behavior: ScrollBehavior) {
    programmaticUntilRef.current = performance.now() + PROGRAMMATIC_SCROLL_MS;
    scrollRef.current?.scrollTo({ top, behavior });
  }

  /**
   * Cadrage de la page bloquée, calculé sans rien bouger : le scrollTop qui
   * amène la zone de la question ENTIÈRE au centre de la partie libre du
   * cadre (sans zone sur cette page : le haut de la page), le décalage
   * horizontal qui la ramène dans la vue, et — si elle ne tient pas au zoom
   * courant — le zoom sous lequel elle tiendrait. null tant que la page
   * bloquée n'est pas rendue.
   */
  function lockFrame(): { top: number; dx: number; fitZoom: number | null } | null {
    const geo = pageGeometry(lockedPage);
    if (!geo) return null;
    return frameRect(geo, zone && zone.page === lockedPage ? zone.rect : null, frameOptions());
  }

  /** La page `page` et la vue, mesurées pour `frameRect` ; null tant que la
   *  page n'est pas rendue. L'échelle est celle du zoom ÉCRIT (pas l'échelle
   *  CSS d'un geste en cours). */
  function pageGeometry(page: number): PageGeometry | null {
    const el = scrollRef.current;
    const pageEl = el?.querySelector<HTMLElement>(`[data-page="${page}"]`);
    if (!el || !pageEl) return null;
    const elRect = el.getBoundingClientRect();
    const pageRect = pageEl.getBoundingClientRect();
    const [w] = (data?.page_sizes_pts ?? [])[page - 1] ?? [595, 842];
    return {
      pageTop: pageRect.top - elRect.top + el.scrollTop,
      pageLeft: pageRect.left - elRect.left,
      maxTop: Math.max(0, el.scrollHeight - el.clientHeight),
      viewWidth: el.clientWidth,
      viewHeight: el.clientHeight,
      scale: (BASE_WIDTH * zoom) / w,
    };
  }

  function frameOptions() {
    return {
      pad: ZONE_PAD_PTS,
      topInset: ZONE_TOP_INSET,
      bottomInset: ZONE_BOTTOM_INSET,
      sideInset: ZONE_SIDE_INSET,
      zoom,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
    };
  }

  /**
   * Amène la zone de la question ENTIÈRE à l'écran : centrée verticalement
   * dans la partie libre du cadre, ramenée dans la vue horizontalement (par
   * `panX`, qui reste manipulable), et — au cadrage initial seulement (`fit`) —
   * si elle ne tient pas au zoom courant, le zoom baisse juste assez pour
   * qu'elle tienne. Jamais l'inverse, et jamais contre un zoom que
   * l'utilisateur vient de choisir : zoomer et dézoomer restent à lui pendant
   * le blocage. Sans zone sur la page bloquée, c'est le haut de cette page
   * qui est cadré. Le cadrage devient le plancher du verrou. Rend false tant
   * que la page bloquée n'est pas rendue.
   *
   * C'est ce qui remplace « page-contexte en haut » : entre la décision de
   * poser la question et son arrivée, on a pu défiler ou zoomer, et le passage
   * visé se retrouvait coupé au bord du cadre.
   */
  function frameZone(behavior: ScrollBehavior, fit = true): boolean {
    const frame = lockFrame();
    if (!frame) return false;
    if (fit && frame.fitZoom !== null) {
      setZoom(frame.fitZoom); // l'effet de zoom recadrera une fois la mise en page refaite
      return true;
    }
    lockFloorRef.current = frame.top;
    scrollViewTo(frame.top, behavior);
    if (frame.dx) setPanX((p) => clampPanX(p + frame.dx));
    return true;
  }

  // Borne le décalage horizontal : on peut parcourir un PDF zoomé plus large que le
  // viewport (overflow/2 de chaque côté) PLUS une marge pour le pousser sur le côté.
  function clampPanX(px: number) {
    const vw = scrollRef.current?.clientWidth ?? 0;
    const overflow = Math.max((widthRef.current - vw) / 2, 0);
    const max = overflow + vw * 0.75;
    return clamp(px, -max, max);
  }

  /** Décale la colonne à la prochaine frame (cf. panFrameRef). */
  function schedulePan(next: (current: number) => number) {
    const pending = panFrameRef.current;
    const value = clampPanX(next(pending ? pending.value : panXRef.current));
    if (pending) {
      pending.value = value;
      return;
    }
    const frame = { value, raf: 0 };
    frame.raf = requestAnimationFrame(() => {
      panFrameRef.current = null;
      setPanX(frame.value);
    });
    panFrameRef.current = frame;
  }

  // Zoom fluide à la molette/pincement (Ctrl/Cmd) + déplacement horizontal (molette
  // horizontale du trackpad ou Maj+molette). preventDefault => pas de zoom/navigation
  // navigateur, et le déplacement reste actif même quand le scroll vertical est figé.
  // Sous une question bloquante, la molette remonte librement mais s'arrête au plancher.
  //
  // Un geste de zoom ne re-met plus la page en forme à chaque événement : la
  // colonne est mise à l'échelle en CSS autour du point visé, une fois par
  // frame, et la vraie largeur n'est écrite qu'une fois le geste fini
  // (GESTURE_IDLE_MS sans événement). L'ancrage du zoom garde alors le point
  // visé en place. Les boutons et Ctrl +/-/0 restent des pas discrets.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // Pincement WebKit en cours : ses éventuelles molettes Ctrl sont le même geste.
    let webkitPinch = false;

    /** Le geste en cours, ou un nouveau qui part du point visé. */
    const gestureAt = (clientX: number, clientY: number) => {
      if (gestureRef.current) return gestureRef.current;
      const rect = columnRef.current?.getBoundingClientRect();
      captureZoomAnchor(clientY);
      const gesture = {
        base: zoomRef.current,
        target: zoomRef.current,
        originX: rect ? clientX - rect.left : 0,
        originY: rect ? clientY - rect.top : 0,
        fx: clientX,
        fxr: rect && rect.width > 0 ? (clientX - rect.left) / rect.width : 0.5,
        raf: 0,
        idle: 0,
      };
      gestureRef.current = gesture;
      return gesture;
    };
    const paintGesture = () => {
      const gesture = gestureRef.current;
      const col = columnRef.current;
      if (!gesture || !col) return;
      gesture.raf = 0;
      col.style.transformOrigin = `${gesture.originX}px ${gesture.originY}px`;
      col.style.transform = `translateX(${panXRef.current}px) scale(${gesture.target / gesture.base})`;
    };
    const endGesture = () => {
      const gesture = gestureRef.current;
      if (!gesture) return;
      gestureRef.current = null;
      cancelAnimationFrame(gesture.raf);
      clearTimeout(gesture.idle);
      if (Math.abs(gesture.target - gesture.base) < 0.001) {
        // Rien à écrire (zoom déjà en butée) : l'échelle tombe, c'est tout.
        const col = columnRef.current;
        if (col) {
          col.style.transform = `translateX(${panXRef.current}px)`;
          col.style.transformOrigin = "";
        }
        zoomAnchorRef.current = null;
        return;
      }
      gestureEndRef.current = { fx: gesture.fx, fxr: gesture.fxr };
      setZoom(gesture.target); // l'effet de zoom retire l'échelle et ancre la vue
    };
    const zoomBy = (clientX: number, clientY: number, next: (base: number, target: number) => number) => {
      const gesture = gestureAt(clientX, clientY);
      gesture.target = clamp(next(gesture.base, gesture.target), MIN_ZOOM, MAX_ZOOM);
      if (!gesture.raf) gesture.raf = requestAnimationFrame(paintGesture);
      clearTimeout(gesture.idle);
      gesture.idle = window.setTimeout(endGesture, GESTURE_IDLE_MS);
    };

    const onWheel = (e: WheelEvent) => {
      if (frozenRef.current) return;
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        if (!webkitPinch) zoomBy(e.clientX, e.clientY, (_base, target) => target - e.deltaY * 0.0025);
        return;
      }
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault();
        const delta = e.shiftKey ? e.deltaY : e.deltaX;
        schedulePan((p) => p - delta);
        return;
      }
      const floor = lockFloorRef.current;
      if (floor !== null && e.deltaY > 0 && el.scrollTop + wheelPixels(e, el) > floor) {
        e.preventDefault();
        el.scrollTop = floor;
      }
    };
    // Sous WebKit, le pincement du trackpad arrive en événements de geste, avec
    // une échelle relative à son début — pas en molette Ctrl.
    const onGestureStart = (e: Event) => {
      e.preventDefault();
      if (frozenRef.current) return;
      const pinch = e as WebKitGestureEvent;
      webkitPinch = true;
      gestureAt(pinch.clientX, pinch.clientY);
    };
    const onGestureChange = (e: Event) => {
      e.preventDefault();
      if (frozenRef.current || !webkitPinch) return;
      const pinch = e as WebKitGestureEvent;
      zoomBy(pinch.clientX, pinch.clientY, (base) => base * pinch.scale);
    };
    const onGestureEnd = (e: Event) => {
      e.preventDefault();
      if (!webkitPinch) return;
      webkitPinch = false;
      endGesture();
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("gesturestart", onGestureStart);
    el.addEventListener("gesturechange", onGestureChange);
    el.addEventListener("gestureend", onGestureEnd);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("gesturestart", onGestureStart);
      el.removeEventListener("gesturechange", onGestureChange);
      el.removeEventListener("gestureend", onGestureEnd);
      const gesture = gestureRef.current;
      if (gesture) {
        cancelAnimationFrame(gesture.raf);
        clearTimeout(gesture.idle);
        gestureRef.current = null;
      }
    };
    // Branchés une fois : `schedulePan` et le zoom par geste ne lisent que des refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Le plancher au clavier : les touches qui descendent s'y arrêtent. Pas dans
  // un champ ni sur un bouton (Espace y écrit ou y clique), ni dans le panneau
  // de Clikoda : seulement quand c'est le document qui défilerait.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = scrollRef.current;
      const floor = lockFloorRef.current;
      if (!el || floor === null || e.defaultPrevented) return;
      const step = scrollKeyStep(e, el);
      if (step === null) return;
      const target = e.target instanceof HTMLElement ? e.target : null;
      if (target && target !== document.body && !el.contains(target)) return;
      if (target?.closest("input, textarea, select, button, [contenteditable='true']")) return;
      if (el.scrollTop + step <= floor) return;
      e.preventDefault();
      el.scrollTop = floor;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Garde-fou du plancher : ce que ni la molette ni le clavier n'ont arrêté
  // (glissé de la barre de défilement, geste tactile) y est ramené. Sauf juste
  // après un défilement décidé par le lecteur : le cadrage animé part parfois
  // d'en dessous, et doit pouvoir finir son mouvement.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const floor = lockFloorRef.current;
      if (floor === null || performance.now() < programmaticUntilRef.current) return;
      if (el.scrollTop > floor + 1) el.scrollTop = floor;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Déplacement horizontal à la souris : on n'amorce le glissé que sur le fond/les
  // marges (jamais sur une page, qui reste sélectionnable). Indépendant du scroll
  // -> fonctionne aussi pendant une question bloquante.
  function startPan(e: React.MouseEvent) {
    if (e.button !== 0 || frozenRef.current) return;
    if ((e.target as HTMLElement).closest("[data-page]")) return;
    panDragRef.current = { startX: e.clientX, startPan: panFrameRef.current?.value ?? panX };
    setPanning(true);
  }
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = panDragRef.current;
      if (d) schedulePan(() => d.startPan + (e.clientX - d.startX));
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
      if (panFrameRef.current) cancelAnimationFrame(panFrameRef.current.raf);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
  }, [zoom]);

  // Raccourcis clavier Ctrl/Cmd + +/-/0.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || frozenRef.current) return;
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

  // Suivi de la page dominante (la plus visible) pour donner le bon contexte à Clikoda.
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
  //
  // Sauf en démonstration : c'est LA ligne qui, sinon, créerait une
  // `reading_sessions` pour la visite guidée. `sessionId` reste alors nul, ce
  // que tout le reste du lecteur sait déjà traiter (il l'est aussi le temps de
  // l'aller-retour réseau).
  useEffect(() => {
    if (!Number.isFinite(id) || demo) return;
    startTimeRef.current = Date.now();
    let cancelled = false;
    api
      .startSession(id)
      .then((r) => {
        // Parti avant la réponse : la session n'a pas eu lieu, on l'efface.
        if (leftRef.current) {
          api.abandonSession(r.session_id).catch(() => {});
          return;
        }
        if (!cancelled) setSessionId(r.session_id);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id, demo]);

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

  // Sélection sur une page PDF : les mots du calque (`data-wi`) dont au moins
  // un caractère est sélectionné. Leurs boîtes PLACÉES (bandes de ligne), pas
  // les boîtes brutes de PDFium, forment les rects — le surlignage enregistré
  // couvre exactement ce que l'utilisateur a vu se colorer —, et leur texte la
  // citation (`buildQuote` : césures recollées, marqueurs retirés).
  function pdfSelection(pageEl: HTMLElement, page: number, sel: Selection): { rects: number[][]; quote: string } {
    const words = wordsByPage[page] || [];
    const boxes = placedBoxes(words);
    const selected = selectedWordIndices(sel.getRangeAt(0), pageEl);
    const rects: number[][] = [];
    for (const wi of selected) {
      const box = boxes.get(wi);
      if (box) rects.push([...box]);
    }
    return { rects: mergeLineRects(rects), quote: buildQuote(words, selected, boxes) };
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

  // Sélection de texte -> barre flottante (Contexte, styles, étiquettes, Note).
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
      // Fichier de code : du vrai texte, espaces compris — `sel.toString()` suffit.
      const pdf = isCode ? null : pdfSelection(pageEl, page, sel);
      const rects = pdf ? pdf.rects : [];
      const anchor = isCode ? computeSelectionAnchor(sel) : null;
      const rangeRect = sel.getRangeAt(0).getBoundingClientRect();
      const rootRect = rootEl.getBoundingClientRect();
      setSelection({
        text: pdf?.quote || text,
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

  // Un nouveau geste efface la barre de la sélection précédente. Restée
  // affichée pendant le glissé suivant, elle était sur son chemin — juste
  // au-dessus de la ligne choisie — et la sélection sautait dedans, jusqu'au
  // bout du document. Elle revient au relâcher s'il y a encore une sélection.
  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      if (e.target instanceof Node && toolbarRef.current?.contains(e.target)) return;
      setSelection(null);
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, []);

  // Marques des pages reconstruites : citations de Clikoda + surlignages mémorisés.
  const flashKey = flash?.key ?? null;
  const marksByPage = useMemo(() => {
    if (!isCode) return {};
    const out: Record<number, TextMark[]> = {};
    for (const [p, marks] of Object.entries(quoteMarksByPage)) out[Number(p)] = [...marks];
    for (const hl of annotations.highlights) {
      const label = hl.label_id !== null ? annotations.labelsById.get(hl.label_id) : null;
      (out[hl.page] ??= []).push({
        text: hl.quote,
        color: labelColor(label),
        style: hl.style,
        id: hl.id,
        label: labelName(label, lang),
        note: hl.note,
        flash: flashKey === `h-${hl.id}`,
      });
    }
    return out;
  }, [isCode, quoteMarksByPage, annotations.highlights, annotations.labelsById, lang, flashKey]);

  // Verrouillage de la lecture pendant une question automatique : on amène la
  // ZONE visée entière dans la vue (à défaut, la page-contexte), et ce cadrage
  // devient le plancher du défilement jusqu'à la bonne réponse — on peut
  // remonter relire, pas descendre. Relancé quand la zone arrive — sa
  // localisation (api.searchPage) suit la question d'un aller-retour.
  useEffect(() => {
    if (!locked) {
      lockFloorRef.current = null;
      return;
    }
    clearSelection();
    frameZone("smooth");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locked, lockedPage, zone]);

  /** Référence de page cliquée dans une réponse de Clikoda : on y amène le lecteur.
      Pendant une question verrouillée, jamais plus bas que le plancher. */
  function goToPage(page: number, behavior: ScrollBehavior = "smooth") {
    const el = scrollRef.current;
    const pageEl = el?.querySelector<HTMLElement>(`[data-page="${page}"]`);
    const floor = lockFloorRef.current;
    if (!el || !pageEl || (locked && floor === null)) return;
    const top = pageEl.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop;
    scrollViewTo(floor === null ? top : Math.min(top, floor), behavior);
  }

  /**
   * Le carnet amène le lecteur sur un élément : sa boîte cadrée comme une
   * occurrence de recherche (frameRect), sous le plancher d'une question
   * bloquante jamais, et il clignote. Fichier de code : la page, puis
   * l'élément une fois ses blocs rendus (au plus 1 s). Un signet, le
   * marque-page : le haut de leur page.
   */
  function goToAnnotation(target: NotebookTarget) {
    if (target.kind === "page") {
      goToPage(target.page);
      return;
    }
    const key = target.kind === "highlight" ? `h-${target.id}` : `n-${target.id}`;
    setFlash({ page: target.page, key });
    const floor = lockFloorRef.current;
    if (locked && floor === null) return;
    const land = (top: number) => scrollViewTo(floor === null ? top : Math.min(top, floor), "smooth");
    let box: number[] | null = null;
    if (target.kind === "highlight") {
      const rects = annotations.highlights.find((h) => h.id === target.id)?.rects ?? [];
      box = rects.length ? boundsOf(rects) : null;
    } else {
      const note = annotations.notes.find((n) => n.id === target.id);
      if (note?.x != null && note.y != null) box = [note.x, note.y, note.x + 12, note.y + 12];
    }
    const geo = !isCode && box ? pageGeometry(target.page) : null;
    if (geo && box) {
      const frame = frameRect(geo, box, frameOptions());
      land(frame.top);
      if (frame.dx) setPanX((p) => clampPanX(p + frame.dx));
      return;
    }
    goToPage(target.page);
    if (!isCode) return;
    const deadline = performance.now() + 1000;
    const seek = () => {
      const el = scrollRef.current;
      const found = el?.querySelector<HTMLElement>(`[data-page="${target.page}"] ${annotationSelector(target.kind, target.id)}`);
      if (el && found) {
        const r = found.getBoundingClientRect();
        land(clamp(r.top - el.getBoundingClientRect().top + el.scrollTop - ZONE_TOP_INSET, 0, el.scrollHeight));
        return;
      }
      if (performance.now() < deadline) requestAnimationFrame(seek);
    };
    requestAnimationFrame(seek);
  }

  // Pose d'un post-it : un seul gestionnaire de clic, en CAPTURE sur la
  // colonne — aucune page n'est re-rendue pour l'occasion. Sur un PDF, la
  // position est celle du clic, en points PDF ; sur un fichier de code, il n'y
  // en a pas (le post-it s'empile dans la marge). Échap annule.
  const placeSticky = useStableCallback((e: MouseEvent) => {
    if (!canAnnotate) {
      setPlacing(false);
      return;
    }
    const pageEl = e.target instanceof Element ? e.target.closest<HTMLElement>("[data-page]") : null;
    if (!pageEl) return;
    e.preventDefault();
    e.stopPropagation();
    const page = Number(pageEl.dataset.page);
    let x: number | null = null;
    let y: number | null = null;
    if (!isCode) {
      const rect = pageEl.getBoundingClientRect();
      const [w] = sizes[page - 1] ?? [595, 842];
      const scale = rect.width / w;
      x = Math.max(0, (e.clientX - rect.left) / scale);
      y = Math.max(0, (e.clientY - rect.top) / scale);
    }
    setPlacing(false);
    void annotations
      .createNote({ kind: "sticky", page, x, y, labelId: toolLabel })
      .then((note) => note && setEditing({ kind: "note", id: note.id, focusNote: true }));
  });
  useEffect(() => {
    const col = columnRef.current;
    if (!placing || !col) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPlacing(false);
    };
    col.addEventListener("click", placeSticky, true);
    window.addEventListener("keydown", onKey);
    return () => {
      col.removeEventListener("click", placeSticky, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [placing, placeSticky]);

  // ── Recherche dans le document (Ctrl/Cmd+F) ──────────────────────────────
  //
  // Elle ne s'ouvre qu'en lecture : ni dans le sas d'entrée, ni dans celui de
  // sortie, ni en pause ou pendant la visite (vue figée). Le raccourci est
  // ⌘F sur macOS, Ctrl+F ailleurs — jamais Ctrl+F sur macOS, qui déplace le
  // curseur d'un champ de texte, ni ⌘+Ctrl+F, le plein écran. Il est capté
  // partout dans le lecteur : en mode navigateur, la recherche du navigateur
  // ne voit que les pages rendues en images, et ne trouverait rien.
  const find = useReaderFind(id, currentPage);
  const canFind = Boolean(data) && entered && exit === null && !showPostExitRest && !frozen;
  const findVisible = find.open && canFind;
  // Carnet et post-it : en lecture, comme la recherche, et jamais pendant la visite.
  const canAnnotate = canFind && !demo;
  const notebookVisible = notebookOpen && canAnnotate;
  const placingVisible = placing && canAnnotate;
  // L'occurrence courante est sous le plancher d'une question bloquante :
  // comptée, mais le lecteur ne descend pas jusqu'à elle.
  const [findLocked, setFindLocked] = useState(false);
  const onFindKey = useStableCallback((e: KeyboardEvent) => {
    if (e.isComposing || e.altKey) return;
    const mod = isMacPlatform() ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
    const key = e.key.toLowerCase();
    if (mod && key === "f") {
      e.preventDefault();
      if (canFind) find.openBar();
      return;
    }
    if (!findVisible || !((mod && key === "g") || e.key === "F3")) return;
    e.preventDefault();
    if (e.shiftKey) find.prev();
    else find.next();
  });
  useEffect(() => {
    window.addEventListener("keydown", onFindKey);
    return () => window.removeEventListener("keydown", onFindKey);
  }, [onFindKey]);

  // Occurrences à dessiner, par page : les listes viennent telles quelles des
  // réponses du serveur, donc stables d'un rendu à l'autre (pages mémoïsées).
  const findHitsByPage = useMemo(() => {
    const out: Record<number, number[][][]> = {};
    for (const [page, hits] of Object.entries(find.pageHits)) if (hits.rects?.length) out[Number(page)] = hits.rects;
    return out;
  }, [find.pageHits]);
  const findRangesByPage = useMemo(() => {
    const out: Record<number, [number, number][]> = {};
    for (const [page, hits] of Object.entries(find.pageHits)) if (hits.ranges?.length) out[Number(page)] = hits.ranges;
    return out;
  }, [find.pageHits]);

  // Aller à l'occurrence courante, UNE fois par occurrence (« 3 / 17 » → « 4 /
  // 17 »), dès que ses boîtes sont arrivées. Le défilement est instantané : on
  // enchaîne les Entrée. Dans une image (requestAnimationFrame) : la page vient
  // peut-être d'être re-rendue avec ses occurrences.
  const findNavRef = useRef<string | null>(null);
  const findQuery = find.summary?.query ?? null;
  const findPage = find.hit?.page ?? null;
  const findIndex = find.hit?.index ?? -1;
  const findPageLoaded = findPage !== null && find.pageHits[findPage] !== undefined;
  const findHitRects = findPage !== null && !isCode ? find.pageHits[findPage]?.rects?.[findIndex] ?? null : null;
  useEffect(() => {
    if (!findVisible || findPage === null || findQuery === null) return;
    const key = `${findQuery}:${find.ordinal}`;
    if (findNavRef.current === key) return;
    if (!isCode && !findHitRects) {
      // Page arrivée sans les boîtes de cette occurrence (au-delà du plafond
      // par page, READER_FIND_MAX_PAGE_HITS) : son haut, à défaut. Sinon on
      // attend les boîtes.
      if (findPageLoaded) {
        findNavRef.current = key;
        goToPage(findPage, "auto");
      }
      return;
    }
    let raf = 0;
    const land = (top: number) => {
      findNavRef.current = key;
      const floor = lockFloorRef.current;
      setFindLocked(floor !== null && top > floor + 1);
      if (locked && floor === null) return;
      scrollViewTo(floor === null ? top : Math.min(top, floor), "auto");
    };
    if (!isCode) {
      raf = requestAnimationFrame(() => {
        const geo = pageGeometry(findPage);
        if (!geo || !findHitRects?.length) return;
        const frame = frameRect(geo, boundsOf(findHitRects), frameOptions());
        land(frame.top);
        if (frame.dx) setPanX((p) => clampPanX(p + frame.dx));
      });
    } else {
      // Fichier de code : pas de géométrie. La page d'abord, puis la marque
      // `data-find-current`, une fois ses blocs chargés et rendus (au plus 1 s).
      findNavRef.current = key;
      goToPage(findPage, "auto");
      const deadline = performance.now() + 1000;
      const seek = () => {
        const el = scrollRef.current;
        const mark = el?.querySelector<HTMLElement>(`[data-page="${findPage}"] mark[data-find-current]`);
        if (el && mark) {
          const r = mark.getBoundingClientRect();
          const top = r.top - el.getBoundingClientRect().top + el.scrollTop;
          const avail = el.clientHeight - ZONE_TOP_INSET - ZONE_BOTTOM_INSET;
          land(clamp(top - ZONE_TOP_INSET - Math.max(0, (avail - r.height) / 2), 0, el.scrollHeight));
          return;
        }
        if (performance.now() < deadline) raf = requestAnimationFrame(seek);
      };
      raf = requestAnimationFrame(seek);
    }
    return () => cancelAnimationFrame(raf);
    // `pageGeometry`, `frameOptions`, `goToPage` lisent l'état du rendu courant.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [findVisible, findQuery, find.ordinal, findPage, findIndex, findHitRects, findPageLoaded, isCode]);

  function closeFind() {
    setFindLocked(false);
    find.close();
  }

  function handleGatedChange(active: boolean, page?: number) {
    if (active && page) setLockedPage(page);
    setLocked(active);
  }

  /** Sortie du sas d'entrée : on lit. */
  function startReading(timings: WarmUpTiming[]) {
    setWarmup(timings);
    setEntered(true);
    // Et le sas rend la main à la visite : la dernière carte du warm-up franchie
    // fait entrer dans la lecture, donc l'étape qui expliquait les cartes n'a
    // plus de cible. Sans ça, sa bulle attendait cinq secondes dans le vide
    // avant que la visite ne renonce à trouver son ancre.
    const tour = useTour.getState();
    if (currentStep(tour)?.id === "warmup") tour.next();
  }

  /**
   * « ← Bibliothèque » depuis le sas d'entrée : mauvais document. Rien n'a été
   * lu, donc la session est EFFACÉE, pas close — close, elle compterait (durée,
   * frise de progression). Clikoda est coupée TOUT DE SUITE : l'accroche de
   * curiosité et la fiche du document sont peut-être en vol, et tant qu'Ollama
   * génère, toute la machine rame. La fermeture du WebSocket coupe aussi, mais
   * seulement quand le serveur constate la déconnexion, après la navigation —
   * l'appel explicite part avant, sans attendre sa réponse.
   */
  function handleLeave() {
    leftRef.current = true;
    api.cancelGenerations().catch(() => {});
    if (sessionId != null) api.abandonSession(sessionId).catch(() => {});
    // L'accroche du sas est peut-être en vol : coupée côté serveur, elle
    // reviendrait vide et resterait en cache (staleTime infini) — le prochain
    // passage sur ce document n'aurait plus d'accroche.
    queryClient.removeQueries({ queryKey: ["hook", id] });
    navigate("/");
  }

  /**
   * « Terminer » : le sas de sortie s'ouvre TOUT DE SUITE et Clikoda passe en
   * fond. Deux choses partent en parallèle sans qu'on les attende : le
   * WebSocket du lecteur se ferme (`ended` -> plus d'intervention, plus de
   * dérive d'attention pendant les réflexions) et la clôture côté serveur, qui
   * coupe la génération en vol et purge la file LLM avant d'écrire la session
   * (cf. services.session.end_session). Le bilan ne se demande qu'à sa
   * réponse : il trouve alors un worker libre.
   */
  function handleEnd() {
    // Démonstration : le bilan est écrit d'avance, il n'y a pas de session à
    // clore. C'est aussi le chemin qu'emprunte la visite pour faire apparaître
    // le sas de sortie au moment où elle l'explique.
    if (demo) {
      setPause(null);
      setExit({ sessionId: DEMO_METRICS.session_id, metrics: demoMetricsRef.current });
      return;
    }
    if (sessionId == null) {
      navigate("/");
      return;
    }
    if (exit) return;
    // Durée de LECTURE : les pauses en sont retirées, y compris celle en cours
    // quand la séance se termine depuis l'écran de pause.
    const now = Date.now();
    const pausedMs = pausedMsRef.current + (pause ? now - pause.startedAt : 0);
    const duration = Math.max(0, Math.round((now - startTimeRef.current - pausedMs) / 1000));
    setPause(null);
    setExit({ sessionId, metrics: null });
    api
      .endSession(sessionId, duration)
      .then((metrics) => setExit((e) => (e && e.sessionId === sessionId ? { sessionId, metrics } : e)))
      .catch(() => navigate("/"));
  }

  /** Pause : la lecture s'arrête, l'élève reviendra. `plannedMin` = durée
   *  conseillée par Clikoda quand c'est sa carte qui l'a déclenchée. */
  function startPause(source: ReadingPause["source"], plannedMin: number | null = null) {
    if (!entered || exit || pause) return;
    clearSelection();
    setPause({ source, plannedMin, startedAt: Date.now() });
  }

  function resumeReading() {
    if (!pause) return;
    pausedMsRef.current += Date.now() - pause.startedAt;
    setPause(null);
  }

  function handleExitSasClose() {
    setExit(null);
    setShowPostExitRest(true);
  }

  const width = BASE_WIDTH * zoom;
  widthRef.current = width;
  const sizes = data?.page_sizes_pts ?? [];
  // Ce que le carnet (à gauche) et Clikoda ancrée (à droite) laissent au
  // document : les bandeaux du haut s'y centrent.
  const notebookInset = notebookVisible ? notebookWidth : 0;
  const topNoticeArea: React.CSSProperties = {
    position: "absolute",
    top: 64,
    left: notebookInset,
    right: clikodaDock,
    display: "flex",
    justifyContent: "center",
    padding: "0 16px",
    pointerEvents: "none",
    zIndex: 40,
  };
  const topNotice: React.CSSProperties = {
    maxWidth: "100%",
    padding: "8px 16px",
    borderRadius: 999,
    fontSize: 13,
    fontWeight: 600,
    textAlign: "center",
    boxShadow: "var(--shadow-md)",
  };

  return (
    // `overflow: hidden` : le lecteur occupe l'écran, rien ne doit en sortir.
    // La bulle de Clikoda est un enfant ABSOLU de cette racine, à une position
    // mémorisée d'une séance à l'autre ; rouverte dans une fenêtre plus petite,
    // elle se retrouvait au-delà du bord droit, allongeait le document et
    // donnait au tout une barre de défilement horizontale. Un simple geste
    // latéral décalait alors l'écran entier — barre du haut comprise, dont le
    // bouton « Terminer » sortait par la gauche.
    <div ref={rootRef} style={{ position: "relative", height: "100%", overflow: "hidden" }}>
      <div
        ref={scrollRef}
        onMouseDown={startPan}
        style={{
          height: "100%",
          // Vertical : figé en pause et pendant la visite. Sous une question
          // bloquante, il reste natif mais borné par le plancher (lockFloorRef) :
          // on remonte relire, on ne descend pas. Horizontal : jamais de scroll
          // natif, le déplacement passe par `panX` (transform) -> reste actif
          // même verrouillé.
          overflowY: frozen ? "hidden" : "auto",
          overflowX: "hidden",
          // En pause, le PDF n'est plus visible — masqué, pas démonté : la
          // position de lecture, le zoom et les pages chargées sont intacts.
          visibility: pause ? "hidden" : undefined,
          background: "var(--bg-alt)",
          cursor: panning ? "grabbing" : undefined,
        }}
      >
        {isLoading && <Centered>{t("reader.opening")}</Centered>}
        {isError && <Centered danger>{t("reader.not_found")}</Centered>}

        {data && (
          // Wrapper centré + min-content : le PDF reste centré quand il rentre.
          // Le décalage horizontal (translateX) est porté par la colonne -> on peut
          // pousser le PDF sur le côté (Clikoda à droite) même quand il rentre.
          <div style={{ display: "flex", justifyContent: "center", minWidth: "min-content", cursor: "grab" }}>
          <div
            ref={columnRef}
            // Pose d'un post-it : curseur en croix sur les pages (theme/tokens.css).
            {...(placingVisible ? { "data-placing": "" } : {})}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 18,
              padding: `${COLUMN_PAD_TOP}px 0 40px`,
              cursor: "grab",
              // Pendant un geste de zoom, l'échelle s'ajoute ici, posée
              // directement sur l'élément (cf. gestureRef) : sans rendu React.
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
                lastPositionPage={bookmark === null ? lastPositionPage : null}
                bookmarkPage={bookmark}
                onToggleBookmark={onToggleBookmark}
                locked={locked}
                lockedPage={lockedPage}
                marksByPage={marksByPage}
                onEditHighlight={editHighlight}
                notesByPage={notesByPage}
                labelsById={annotations.labelsById}
                onEditNote={demo ? undefined : editNote}
                flash={flashKey}
                findRangesByPage={findVisible ? findRangesByPage : undefined}
                findCurrent={findVisible ? find.hit : null}
              />
            ) : (
            Array.from({ length: data.page_count }, (_, i) => i + 1).map((n) => {
              const [w, h] = sizes[n - 1] ?? [595, 842];
              return (
                <PdfPage
                  key={n}
                  docId={id}
                  page={n}
                  width={width}
                  widthPts={w}
                  heightPts={h}
                  renderZoom={renderZoom}
                  contentHash={data.content_hash}
                  // Sous une question bloquante, seules les pages qu'on ne peut pas
                  // encore atteindre sont atténuées : celles du dessus se relisent.
                  dimmed={locked && n > lockedPage}
                  lastPosition={bookmark === null && n === lastPositionPage}
                  bookmarked={n === bookmark}
                  highlights={highlightsByPage[n]}
                  zoneRect={zone && zone.page === n ? zone.rect : null}
                  mask={maskByPage[n]}
                  words={wordsByPage[n]}
                  saved={savedByPage[n] ?? NO_SAVED}
                  findHits={findVisible ? findHitsByPage[n] ?? NO_HITS : NO_HITS}
                  findCurrent={findVisible && findPage === n ? findIndex : -1}
                  demo={demo}
                  onEditHighlight={editHighlight}
                  notes={notesByPage[n] ?? NO_NOTES}
                  labelsById={annotations.labelsById}
                  onEditNote={demo ? undefined : editNote}
                  flash={flash?.page === n ? flash.key : null}
                  onToggleBookmark={onToggleBookmark}
                />
              );
            })
            )}
          </div>
          </div>
        )}
      </div>

      {/* Barre supérieure flottante */}
      <ReaderToolbar
        title={data?.title ?? ""}
        onEnd={handleEnd}
        onPause={() => startPause("manual")}
        pauseDisabled={!entered || exit !== null}
        page={data ? { current: currentPage, total: data.page_count } : null}
      >
        {demo ? null : (
          <>
            <ToolbarIconButton
              label={t("reader.notebook_open", { n: annotations.highlights.length + annotations.notes.length })}
              hint={t("reader.notebook_hint")}
              disabled={!canAnnotate}
              pressed={notebookVisible}
              onClick={() => setNotebookOpen((open) => !open)}
            >
              <NotebookPen className="size-3.5" aria-hidden />
              <span style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                {annotations.highlights.length + annotations.notes.length}
              </span>
            </ToolbarIconButton>
            <ToolbarIconButton
              label={t("reader.sticky_tool")}
              hint={t("reader.sticky_tool_hint")}
              disabled={!canAnnotate}
              pressed={placingVisible}
              onClick={() => setPlacing((on) => !on)}
            >
              <StickyNote className="size-3.5" aria-hidden />
            </ToolbarIconButton>
          </>
        )}
        {findVisible ? (
          <FindBar
            query={find.query}
            onQuery={find.setQuery}
            summary={find.summary}
            searching={find.searching}
            ordinal={find.ordinal}
            locked={findLocked}
            onNext={find.next}
            onPrev={find.prev}
            onClose={closeFind}
            focusToken={find.focusToken}
          />
        ) : (
          <ToolbarIconButton
            label={t("reader.find_open")}
            hint={t("reader.find_hint", { keys: isMacPlatform() ? "⌘F" : "Ctrl+F" })}
            disabled={!canFind}
            onClick={find.openBar}
          >
            <Search className="size-3.5" aria-hidden />
          </ToolbarIconButton>
        )}
      </ReaderToolbar>

      {/* Le carnet du document : à gauche, sous la barre. */}
      {notebookVisible && data ? (
        <NotebookDrawer
          docId={id}
          pageCount={data.page_count}
          currentPage={currentPage}
          bookmark={bookmark}
          annotations={annotations}
          width={notebookWidth}
          onResize={resizeNotebook}
          onClose={() => setNotebookOpen(false)}
          onGoTo={goToAnnotation}
          onAddToContext={addToContext}
        />
      ) : null}

      {/* L'élément cliqué sur la page : son édition, qui suit le défilement. */}
      <AnnotationPopover target={editing} annotations={annotations} onClose={closeEditing} onAddToContext={addToContext} />

      {/* Contrôles de zoom — décalés quand le carnet occupe la gauche. */}
      <ZoomControls
        left={notebookInset + 18}
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

      {/* Barre flottante au-dessus d'une sélection de texte.

          `AnimatePresence` et non un simple montage : ces trois éléments (barre
          de sélection, bandeau de blocage, panneau Clikoda) apparaissaient et
          disparaissaient d'un coup, en plein milieu d'un écran de lecture par
          ailleurs entièrement animé. `motion` est déjà une dépendance de l'app :
          le coût est de six lignes.

          Motion réécrit `transform` dès qu'il anime `y` : un centrage en
          `translateX(-50%)` inline disparaissait. La barre se centre par la
          valeur `x` de Motion, les bandeaux par un conteneur flex. */}
      <AnimatePresence>
        {selection && (
          <SelectionToolbar
            x={selection.x}
            y={selection.y}
            rootWidth={rootRef.current?.clientWidth ?? 800}
            reduceMotion={Boolean(reduceMotion)}
            toolbarRef={toolbarRef}
            onContext={addSelectionToContext}
            annotate={
              demo
                ? undefined
                : {
                    labels: annotations.labels,
                    style: tool.style,
                    labelId: toolLabel,
                    onStyle: (style) => chooseTool({ ...tool, style }),
                    onHighlight: (labelId) => {
                      chooseTool({ ...tool, labelId });
                      void highlightSelection(labelId);
                    },
                    onNote: () => void highlightSelection(toolLabel, true),
                  }
            }
          />
        )}
      </AnimatePresence>

      {/* Pose d'un post-it : ce qu'il faut faire, et comment renoncer. */}
      {placingVisible ? (
        <div style={topNoticeArea}>
          <div
            role="status"
            style={{ ...topNotice, background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border)" }}
          >
            {t("annotations.sticky_place_hint")}
          </div>
        </div>
      ) : null}

      {/* Bannière de question bloquante. Elle DESCEND dans l'écran : le blocage
          vient d'en haut, comme la barre d'outils à laquelle elle s'accroche.
          Centrée par son conteneur : un `translateX(-50%)` inline était écrasé
          par Motion, et le bandeau partait du milieu de l'écran vers la droite,
          sous Clikoda. */}
      <div style={topNoticeArea}>
        <AnimatePresence>
          {locked && (
            <motion.div
              data-testid="gated-banner"
              initial={reduceMotion ? false : { opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: -8 }}
              transition={{ duration: 0.2, ease: [0.33, 1, 0.68, 1] }}
              style={{ ...topNotice, background: "var(--accent)", color: "var(--on-accent)" }}
            >
              {t("reader.gated_banner")}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Assistant déplaçable connecté à Clikoda */}
      <ClikodaPanel
        docId={id}
        currentPage={currentPage}
        sessionId={sessionId}
        onHighlights={handleHighlights}
        contextChips={contextChips}
        onRemoveContextChip={removeContextChip}
        onContextConsumed={() => setContextChips([])}
        onGatedChange={handleGatedChange}
        onMask={handleMask}
        onZone={handleZone}
        onGoToPage={goToPage}
        pageCount={data?.page_count}
        demo={demo}
        reading={entered}
        warmup={warmup}
        // Une séance close le reste : refermer le sas de sortie (`exit` repasse
        // à null) ouvre le sas de repos, et un `ended` revenu à false rouvrait
        // un socket qui, à sa fermeture, écrasait côté serveur le temps par
        // page de la séance (« Où tu as ralenti »).
        ended={exit !== null || showPostExitRest}
        paused={pause}
        onPauseRequest={(minutes) => startPause("suggested", minutes)}
        onDemoReady={handleDemoReady}
        onDockChange={setClikodaDock}
      />

      {data && !entered && (
        <EntrySas
          source={{ kind: "document", docId: id, page: openPage ?? 1 }}
          title={data.title}
          onStart={startReading}
          onLeave={handleLeave}
          demo={demo}
        />
      )}

      {pause && !exit && <PauseSas pause={pause} onResume={resumeReading} onEnd={handleEnd} />}

      {exit && (
        <ExitSas sessionId={exit.sessionId} metrics={exit.metrics} onClose={handleExitSasClose} demo={demo} />
      )}

      {/* En démonstration, le repos est raccourci et la visite reprend la main
          à sa fin — on ne renvoie pas vers l'accueil au milieu d'un tutoriel. */}
      {showPostExitRest && (
        <PostExitRestSas
          onDone={() => {
            if (!demo) navigate("/");
          }}
          totalSeconds={demo ? 10 : undefined}
          unlockAfterSeconds={demo ? 0 : undefined}
        />
      )}
    </div>
  );
}

function ZoomControls({
  left,
  zoom,
  onChange,
  onReset,
}: {
  left: number;
  zoom: number;
  onChange: (z: number) => void;
  onReset: () => void;
}) {
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
        left,
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
