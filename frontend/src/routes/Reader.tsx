import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Highlighter, Pause as PauseIcon, Plus } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useConfirm } from "@/components/ui/confirm";

import { api, pageImageUrl } from "../api/client";
import type { Highlight, HighlightAnchor, PageWord, SavedHighlight, SessionMetrics } from "../api/types";
import type { TextMark } from "../features/reader/anchorText";
import { GemmaPanel, type QaMask } from "../features/reader/GemmaPanel";
import { DEMO_METRICS, DEMO_REFLECTION_KEYS, type DemoBeat } from "../features/reader/demoScript";
import { BlockPages } from "../features/reader/BlockPages";
import { PageTextLayer } from "../features/reader/PageTextLayer";
import { placedBoxes } from "../features/reader/textLayer";
import { EntrySas } from "../features/session/EntrySas";
import { ExitSas } from "../features/session/ExitSas";
import { PauseSas, type ReadingPause } from "../features/session/PauseSas";
import { currentStep, useTour } from "../features/tour/useTour";
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

// Cadrage de la zone d'une question : ce qu'il faut laisser libre autour pour
// qu'elle soit VISIBLE et non simplement dans le viewport — la barre d'outils
// et la bannière de blocage recouvrent le haut du cadre.
const ZONE_TOP_INSET = 112;
const ZONE_BOTTOM_INSET = 24;
const ZONE_SIDE_INSET = 24;
/** Marge (en points PDF) autour du passage cité, pour le liseré. */
// Marge du cache de rappel libre : couvre jambages et interlignes, sinon les
// hampes des lignes voisines laissent deviner le passage.
const MASK_PAD_PTS = 2.5;
const ZONE_PAD_PTS = 4;

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

/** Boîte englobante [x0, y0, x1, y1] d'une liste de rects (points PDF). */
function boundsOf(rects: number[][]): number[] {
  return [
    Math.min(...rects.map((r) => r[0])),
    Math.min(...rects.map((r) => r[1])),
    Math.max(...rects.map((r) => r[2])),
    Math.max(...rects.map((r) => r[3])),
  ];
}

/**
 * Boîte englobante des surlignages d'une page, en pixels d'écran.
 *
 * Sert d'ancre à l'étape de la visite qui explique « elle surligne le passage
 * dont elle parle » : le voile éclaire ce rectangle en même temps que la
 * réponse de Gemma. Sans lui, l'étape désignait le panneau et laissait le
 * passage cité dans le noir — exactement ce qu'elle demande de regarder.
 */
function highlightBounds(groups: { rect: number[] }[], scale: number) {
  const left = Math.min(...groups.map((g) => g.rect[0]));
  const top = Math.min(...groups.map((g) => g.rect[1]));
  const right = Math.max(...groups.map((g) => g.rect[2]));
  const bottom = Math.max(...groups.map((g) => g.rect[3]));
  return {
    left: left * scale,
    top: top * scale,
    width: (right - left) * scale,
    height: (bottom - top) * scale,
  };
}

const selBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
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
  const queryClient = useQueryClient();
  const t = useT();
  const confirm = useConfirm();
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
  // 0 = pas encore monté ; la vraie valeur est posée par l'effet de démarrage de session.
  const startTimeRef = useRef(0);
  const maxPageRef = useRef(1);
  // Pause en cours (bouton « Pause » ou carte de Gemma acceptée) : le PDF est
  // masqué, la vue figée, et le serveur ne mesure plus rien jusqu'à la reprise.
  // Le temps cumulé des pauses est retiré de la durée de la séance.
  const [pause, setPause] = useState<ReadingPause | null>(null);
  const pausedMsRef = useRef(0);

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
  // Zone précise visée par la question en cours (boîte en points PDF) : on la
  // cadre ENTIÈRE à l'écran et on l'encadre d'un liseré, jusqu'à ce que la
  // carte se referme. Elle vient d'une citation retrouvée sur la page
  // (même chemin que le masque et les surlignages : api.searchPage).
  const [zone, setZone] = useState<{ page: number; rect: number[] } | null>(null);
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
      // Le serveur ne crée pas deux fois le même passage : il rend l'id du
      // surlignage existant, qu'on remplace au lieu d'empiler une couche.
      setSavedHighlights((prev) => {
        const next = { id: hid, page, quote: text, rects, color: "key" as const, anchor };
        return prev.some((h) => h.id === hid) ? prev.map((h) => (h.id === hid ? next : h)) : [...prev, next];
      });
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
  const gemmaControls = useRef<{ openPanel: () => void; play: (beat: DemoBeat) => void } | null>(null);
  // Les métriques du sas de sortie sont inventées : elles décrivent une lecture
  // plausible, pas une mesure. Les intitulés de réflexion sont traduits ici,
  // `demoScript.ts` ne portant que leurs clés.
  //
  // Passées par une `ref` et non par une dépendance d'effet : `useT()` renvoie
  // une NOUVELLE fonction à chaque rendu, donc un `useMemo` sur `[t]` produirait
  // un objet différent à chaque fois et rebrancherait les contrôles de la visite
  // en boucle — avec, entre le nettoyage et la repose, une fenêtre où ils sont
  // nuls. Même idiome que les `onHighlightsRef` du panneau Gemma.
  const demoMetricsRef = useRef(DEMO_METRICS);
  demoMetricsRef.current = {
    ...DEMO_METRICS,
    reflection_questions: DEMO_REFLECTION_KEYS.slice(0, 2).map((k) => t(k)),
  };

  const handleDemoReady = useCallback(
    (controls: { openPanel: () => void; play: (beat: DemoBeat) => void } | null) => {
      gemmaControls.current = controls;
    },
    [],
  );

  // La visite pilote le lecteur d'ici : ouvrir Gemma, jouer une réplique, faire
  // apparaître le sas de sortie. Elle ne peut le faire que tant qu'il est monté.
  useEffect(() => {
    if (!demo) return;
    setTourControls({
      // Le sas d'entrée recouvre la page : sans ce passage explicite, l'étape
      // suivante s'ancrerait sur une page cachée derrière son voile.
      enterReading: () => setEntered(true),
      // Le bas de la première page : c'est là que vit la section que Gemma
      // cite, et donc ce que les sept étapes suivantes commentent. Aligné sur
      // le bas du cadre plutôt que centré — la page suivante n'a rien à faire
      // à l'écran pendant qu'on parle de celle-ci.
      pinPassage: () => {
        const view = scrollRef.current;
        const page = view?.querySelector<HTMLElement>('[data-page="1"]');
        if (!view || !page) return;
        view.scrollTop += page.getBoundingClientRect().bottom - view.getBoundingClientRect().bottom;
      },
      openPanel: () => gemmaControls.current?.openPanel(),
      play: (beat) => gemmaControls.current?.play(beat),
      endSession: () => setExit({ sessionId: DEMO_METRICS.session_id, metrics: demoMetricsRef.current }),
      closeExitSas: () => {
        setExit(null);
        setShowPostExitRest(true);
      },
    });
    return () => setTourControls(null);
  }, [demo, setTourControls]);

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
      // Page bloquée : la zone reste cadrée à travers le zoom ; sans zone, on
      // garde la page-contexte en haut, sans saut.
      // `fit: false` : c'est l'utilisateur qui zoome, on ne lui reprend pas
      // la main — on garde seulement la zone dans la vue.
      if (!frameZone("auto", false)) {
        el.querySelector(`[data-page="${lockedPage}"]`)?.scrollIntoView({ block: "start" });
      }
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

  /**
   * Amène la zone de la question ENTIÈRE à l'écran : centrée verticalement
   * dans la partie libre du cadre, ramenée dans la vue horizontalement (par
   * `panX`, qui reste manipulable), et — au cadrage initial seulement (`fit`) —
   * si elle ne tient pas au zoom courant, le zoom baisse juste assez pour
   * qu'elle tienne. Jamais l'inverse, et jamais contre un zoom que
   * l'utilisateur vient de choisir : zoomer et dézoomer restent à lui pendant
   * le blocage. Rend false s'il n'y a rien à cadrer (pas de zone, ou pas sur
   * la page bloquée).
   *
   * C'est ce qui remplace « page-contexte en haut » : entre la décision de
   * poser la question et son arrivée, on a pu défiler ou zoomer, et le passage
   * visé se retrouvait coupé au bord du cadre.
   */
  function frameZone(behavior: ScrollBehavior, fit = true): boolean {
    const el = scrollRef.current;
    if (!el || !zone || zone.page !== lockedPage) return false;
    const pageEl = el.querySelector<HTMLElement>(`[data-page="${zone.page}"]`);
    if (!pageEl) return false;
    const [w] = (data?.page_sizes_pts ?? [])[zone.page - 1] ?? [595, 842];
    const scale = (BASE_WIDTH * zoom) / w;
    const [x0, y0, x1, y1] = zone.rect;
    const zoneW = (x1 - x0 + 2 * ZONE_PAD_PTS) * scale;
    const zoneH = (y1 - y0 + 2 * ZONE_PAD_PTS) * scale;
    const availW = el.clientWidth - 2 * ZONE_SIDE_INSET;
    const availH = el.clientHeight - ZONE_TOP_INSET - ZONE_BOTTOM_INSET;
    if (fit && (zoneH > availH || zoneW > availW) && zoom > MIN_ZOOM) {
      const fitZoom = clamp(Math.min(availH / zoneH, availW / zoneW) * zoom * 0.96, MIN_ZOOM, MAX_ZOOM);
      if (fitZoom < zoom - 0.01) {
        setZoom(fitZoom); // l'effet de zoom rappellera frameZone une fois la mise en page refaite
        return true;
      }
    }
    const elRect = el.getBoundingClientRect();
    const pageRect = pageEl.getBoundingClientRect();
    const zoneTop = pageRect.top - elRect.top + el.scrollTop + (y0 - ZONE_PAD_PTS) * scale;
    const top = zoneTop - ZONE_TOP_INSET - Math.max(0, (availH - zoneH) / 2);
    el.scrollTo({ top: clamp(top, 0, Math.max(0, el.scrollHeight - el.clientHeight)), behavior });
    const zoneLeft = pageRect.left - elRect.left + (x0 - ZONE_PAD_PTS) * scale;
    const zoneRight = zoneLeft + zoneW;
    let dx = 0;
    if (zoneLeft < ZONE_SIDE_INSET) dx = ZONE_SIDE_INSET - zoneLeft;
    else if (zoneRight > el.clientWidth - ZONE_SIDE_INSET) dx = el.clientWidth - ZONE_SIDE_INSET - zoneRight;
    if (dx) setPanX((p) => clampPanX(p + dx));
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

  // Zoom fluide à la molette/pincement (Ctrl/Cmd) + déplacement horizontal (molette
  // horizontale du trackpad ou Maj+molette). preventDefault => pas de zoom/navigation
  // navigateur, et le déplacement reste actif même quand le scroll vertical est figé.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (frozenRef.current) return;
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
    if (e.button !== 0 || frozenRef.current) return;
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
  //
  // Sauf en démonstration : c'est LA ligne qui, sinon, créerait une
  // `reading_sessions` pour la visite guidée. `sessionId` reste alors nul, ce
  // que tout le reste du lecteur sait déjà traiter (il l'est aussi le temps de
  // l'aller-retour réseau).
  useEffect(() => {
    if (!Number.isFinite(id) || demo) return;
    startTimeRef.current = Date.now();
    maxPageRef.current = 1;
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

  // Rects d'une sélection : on relit les boîtes PLACÉES du calque (bandes de
  // ligne), pas les boîtes brutes de PDFium — le surlignage enregistré doit
  // couvrir exactement ce que l'utilisateur a vu se colorer en sélectionnant.
  function computeSelectionRects(pageEl: HTMLElement, page: number, sel: Selection): number[][] {
    const boxes = placedBoxes(wordsByPage[page] || []);
    const spans = pageEl.querySelectorAll<HTMLElement>("[data-wi]");
    const rects: number[][] = [];
    spans.forEach((span) => {
      if (!sel.containsNode(span, true)) return;
      const box = boxes.get(Number(span.dataset.wi));
      if (box) rects.push([...box]);
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
  // ZONE visée entière dans la vue (à défaut, la page-contexte) et on fige le
  // scroll jusqu'à la bonne réponse. Relancé quand la zone arrive — sa
  // localisation (api.searchPage) suit la question d'un aller-retour.
  useEffect(() => {
    if (!locked) return;
    clearSelection();
    if (frameZone("smooth")) return;
    const pageEl = scrollRef.current?.querySelector(`[data-page="${lockedPage}"]`);
    pageEl?.scrollIntoView({ behavior: "smooth", block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locked, lockedPage, zone]);

  /** Référence de page cliquée dans une réponse de Gemma : on y amène le lecteur.
      Pas pendant une question verrouillée — la page-contexte doit rester en vue. */
  function goToPage(page: number) {
    if (locked) return;
    const pageEl = scrollRef.current?.querySelector(`[data-page="${page}"]`);
    pageEl?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function handleGatedChange(active: boolean, page?: number) {
    if (active && page) setLockedPage(page);
    setLocked(active);
  }

  /** Sortie du sas d'entrée : on lit. */
  function startReading() {
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
   * frise de progression). Gemma est coupée TOUT DE SUITE : l'accroche de
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
   * « Terminer » : le sas de sortie s'ouvre TOUT DE SUITE et Gemma passe en
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
      .endSession(sessionId, maxPageRef.current, duration)
      .then((metrics) => setExit((e) => (e && e.sessionId === sessionId ? { sessionId, metrics } : e)))
      .catch(() => navigate("/"));
  }

  /** Pause : la lecture s'arrête, l'élève reviendra. `plannedMin` = durée
   *  conseillée par Gemma quand c'est sa carte qui l'a déclenchée. */
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

  return (
    // `overflow: hidden` : le lecteur occupe l'écran, rien ne doit en sortir.
    // La bulle de Gemma est un enfant ABSOLU de cette racine, à une position
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
          // Vertical : figé pendant une question bloquante. Horizontal : jamais de
          // scroll natif, le déplacement passe par `panX` (transform) -> reste actif
          // même verrouillé.
          overflowY: locked || frozen ? "hidden" : "auto",
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
                  // Ancre de la visite guidée, sur la PREMIÈRE page seulement :
                  // `querySelector` prend le premier élément trouvé, donc la
                  // poser sur toutes reviendrait au même — mais dire « la page
                  // 1 » ici évite qu'on croie l'attribut générique et qu'on
                  // s'appuie dessus ailleurs.
                  {...(n === 1 ? { "data-tour": "page" } : {})}
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
                  {/* Zone visée par la question en cours : un liseré à l'accent,
                      pour qu'on voie de quoi Gemma parle — surtout quand la
                      lecture est bloquée dessus. */}
                  {zone && zone.page === n ? (
                    <svg
                      viewBox={`0 0 ${w} ${h}`}
                      preserveAspectRatio="none"
                      aria-hidden
                      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 4 }}
                    >
                      <rect
                        data-testid="question-zone"
                        x={zone.rect[0] - ZONE_PAD_PTS}
                        y={zone.rect[1] - ZONE_PAD_PTS}
                        width={zone.rect[2] - zone.rect[0] + 2 * ZONE_PAD_PTS}
                        height={zone.rect[3] - zone.rect[1] + 2 * ZONE_PAD_PTS}
                        fill="var(--accent)"
                        fillOpacity={0.07}
                        stroke="var(--accent)"
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                        rx={3}
                      />
                    </svg>
                  ) : null}
                  {/* Ancre de la visite guidée sur le passage cité (cf.
                      `highlightBounds`). Invisible et inerte : elle ne sert
                      qu'à donner un rectangle à éclairer au voile. */}
                  {demo && highlightsByPage[n]?.length ? (
                    <div
                      aria-hidden
                      data-tour="quote"
                      style={{ position: "absolute", ...highlightBounds(highlightsByPage[n], scale), pointerEvents: "none" }}
                    />
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
                          x={rect[0] - MASK_PAD_PTS}
                          y={rect[1] - MASK_PAD_PTS}
                          width={rect[2] - rect[0] + 2 * MASK_PAD_PTS}
                          height={rect[3] - rect[1] + 2 * MASK_PAD_PTS}
                          // Opaque, explicitement : la variable de thème est
                          // pleine, mais rien ne doit pouvoir la rendre
                          // translucide (transition d'opacité, thème tiers).
                          fill="var(--surface-soft)"
                          fillOpacity={1}
                          stroke="var(--border-strong)"
                          strokeDasharray="4 3"
                          vectorEffect="non-scaling-stroke"
                          rx={3}
                        />
                      ))}
                    </svg>
                  ) : null}
                  {/* Calque de texte transparent : sélection native par-dessus l'image. */}
                  {words ? <PageTextLayer words={words} scale={scale} /> : null}
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
        data-tour="toolbar"
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
        <button
          onClick={() => startPause("manual")}
          disabled={!entered || exit !== null}
          title={t("reader.pause_hint")}
          aria-label={t("reader.pause_hint")}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            cursor: !entered || exit !== null ? "default" : "pointer",
            color: "var(--text-soft)",
            fontWeight: 600,
            fontSize: 13,
            padding: "6px 12px",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border)",
            background: "var(--surface)",
            opacity: !entered || exit !== null ? 0.5 : 1,
          }}
        >
          <PauseIcon className="size-3.5" aria-hidden />
          {t("reader.pause")}
        </button>
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

      {/* Barre flottante au-dessus d'une sélection de texte.

          `AnimatePresence` et non un simple montage : ces trois éléments (barre
          de sélection, bandeau de blocage, panneau Gemma) apparaissaient et
          disparaissaient d'un coup, en plein milieu d'un écran de lecture par
          ailleurs entièrement animé. `motion` est déjà une dépendance de l'app :
          le coût est de six lignes.

          `transform` reste dans le style inline (le centrage), Motion n'anime
          que l'opacité et un décalage vertical — mélanger les deux ferait sauter
          la barre hors de l'axe de la sélection. */}
      <AnimatePresence>
        {selection && (
          <motion.div
            ref={toolbarRef}
            initial={reduceMotion ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, y: 4 }}
            transition={{ duration: 0.14, ease: [0.33, 1, 0.68, 1] }}
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
              <Plus className="size-3.5" aria-hidden />
              {t("reader.add_context")}
            </button>
            <button style={selBtn} onClick={highlightSelection}>
              <Highlighter className="size-3.5" aria-hidden />
              {t("reader.highlight")}
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bannière de question bloquante. Elle DESCEND dans l'écran : le blocage
          vient d'en haut, comme la barre d'outils à laquelle elle s'accroche. */}
      <AnimatePresence>
        {locked && (
          <motion.div
            initial={reduceMotion ? false : { opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, y: -8 }}
            transition={{ duration: 0.2, ease: [0.33, 1, 0.68, 1] }}
            style={{
              position: "absolute",
              top: 64,
              left: "50%",
              transform: "translateX(-50%)",
              padding: "8px 16px",
              background: "var(--accent)",
              color: "var(--on-accent)",
              borderRadius: 999,
              fontSize: 13,
              fontWeight: 600,
              boxShadow: "var(--shadow-md)",
              zIndex: 40,
            }}
          >
            {t("reader.gated_banner")}
          </motion.div>
        )}
      </AnimatePresence>

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
        onZone={handleZone}
        onGoToPage={goToPage}
        pageCount={data?.page_count}
        demo={demo}
        reading={entered}
        ended={exit !== null}
        paused={pause}
        onPauseRequest={(minutes) => startPause("suggested", minutes)}
        onDemoReady={handleDemoReady}
      />

      {data && !entered && (
        <EntrySas docId={id} title={data.title} onStart={startReading} onLeave={handleLeave} demo={demo} />
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
