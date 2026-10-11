// useRunTracker — Événements d'une séance, temps réellement actif (E5, T2) et
// intervalles où se lit l'attention.
//
// Les événements (taps, réponses, auto-évaluations, cartes) s'accumulent et
// partent en UN lot à chaque changement d'étape : pas un appel par tap. Le
// temps d'une étape ne compte que tant que l'apprenant interagit ; au-delà du
// seuil d'inactivité fourni par le plan (`idle_cutoff_s`, config serveur), les
// secondes ne sont plus « effectives ». Le serveur recorrige tout et renvoie
// si le plafond de durée est atteint (R24) : c'est lui qui décide.
//
// Interagir, c'est faire un GESTE : cliquer, taper, faire défiler — ou bouger
// la souris, car on lit aussi en suivant le texte du pointeur, comme d'autres
// font défiler pour garder la ligne à hauteur d'yeux. Un mouvement isolé n'en
// est pas un : les mouvements sont échantillonnés et comptés sur une fenêtre
// glissante, et ne valent un geste qu'à partir d'un certain nombre
// (`plan.activity`, config serveur LANG_ACTIVITY_*).
//
// L'attention se lit dans les INTERVALLES d'une page : de son ouverture à la
// première réponse (ou à la page suivante), d'une réponse à la suivante, de la
// dernière à la page suivante. Chacun part au serveur avec sa durée et sa part
// passée sans un geste (fenêtre masquée comprise) : c'est lui qui juge s'il
// était trop long. Quitter la séance n'est pas tourner la page — un intervalle
// interrompu ne part pas.
import { useCallback, useEffect, useRef } from "react";

import { api } from "../../../api/client";
import type { ActivityConfig, EventsResult, RunEvent } from "../../../api/feuilleton";

/** Les événements qui sont des RÉPONSES : chacun ferme un intervalle et en ouvre un autre. */
const ANSWERS: ReadonlySet<RunEvent["type"]> = new Set(["answer", "rating", "card"]);

const GESTURES = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

interface Interval {
  step: string;
  origin: "open" | "answer";
  startedMs: number;
  /** Secondes sans geste dans la fenêtre glissante, ou fenêtre masquée. */
  idleS: number;
}

export interface RunTracker {
  push: (event: RunEvent) => void;
  /** Ferme l'étape courante, ouvre la suivante et envoie le lot. */
  advance: (from: string | null, to: string | null, extra?: { signal?: string | null; skipped?: boolean }) => Promise<EventsResult | null>;
  /** Envoie ce qui attend sans changer d'étape (sortie de la séance). */
  flush: (current: string | null) => Promise<EventsResult | null>;
  activeSeconds: () => number;
}

const tenths = (seconds: number) => Math.round(seconds * 10) / 10;

export function useRunTracker(runId: number | null, idleCutoffS: number, activity?: ActivityConfig): RunTracker {
  const queue = useRef<RunEvent[]>([]);
  // Dernier geste ; 0 = pas encore d'interaction, posé au montage (pas pendant le rendu).
  const lastInteraction = useRef(0);
  const stepActive = useRef(0);
  const interval = useRef<Interval | null>(null);
  // Échantillons de mouvements de souris encore dans la fenêtre glissante.
  const moves = useRef<number[]>([]);
  // Lu par les écouteurs sans les réinstaller : la config arrive avec le plan.
  const config = useRef(activity);
  useEffect(() => {
    config.current = activity;
  }, [activity]);

  useEffect(() => {
    let lastTick = Date.now();
    lastInteraction.current = lastTick;
    const gesture = () => {
      lastInteraction.current = Date.now();
    };
    // Un mouvement compte s'il n'est pas isolé : assez d'échantillons dans la fenêtre.
    const move = () => {
      const cfg = config.current;
      if (!cfg) return;
      const now = Date.now();
      const samples = moves.current;
      if (samples.length && now - samples[samples.length - 1] < cfg.move_sample_ms) return;
      samples.push(now);
      while (samples.length && now - samples[0] > cfg.window_s * 1000) samples.shift();
      if (samples.length >= cfg.min_moves) lastInteraction.current = now;
    };
    GESTURES.forEach((e) => window.addEventListener(e, gesture, { passive: true }));
    // Le défilement ne remonte pas jusqu'à `window` : capté à la descente, quel que soit le conteneur.
    window.addEventListener("scroll", gesture, { passive: true, capture: true });
    window.addEventListener("pointermove", move, { passive: true });
    const timer = window.setInterval(() => {
      const now = Date.now();
      // Le temps écoulé, pas un nombre de ticks : un onglet masqué espace ses timers.
      const elapsed = Math.max(0, (now - lastTick) / 1000);
      lastTick = now;
      const visible = document.visibilityState === "visible";
      const idle = (now - lastInteraction.current) / 1000;
      if (visible && idle < idleCutoffS) stepActive.current += 1;
      const current = interval.current;
      const cfg = config.current;
      if (current && cfg && !(visible && idle < cfg.window_s)) current.idleS += elapsed;
    }, 1000);
    return () => {
      GESTURES.forEach((e) => window.removeEventListener(e, gesture));
      window.removeEventListener("scroll", gesture, { capture: true });
      window.removeEventListener("pointermove", move);
      window.clearInterval(timer);
    };
  }, [idleCutoffS]);

  const send = useCallback(
    async (current: string | null): Promise<EventsResult | null> => {
      if (runId === null) return null;
      const batch = queue.current;
      queue.current = [];
      try {
        return await api.feuilletonEvents(runId, batch, current);
      } catch {
        // Réseau local indisponible : on garde le lot pour le prochain envoi.
        queue.current = batch.concat(queue.current);
        return null;
      }
    },
    [runId],
  );

  /** Ferme l'intervalle en cours et le met dans le lot. */
  const close = useCallback(() => {
    const current = interval.current;
    interval.current = null;
    if (!current) return;
    const elapsed = Math.max(0, (Date.now() - current.startedMs) / 1000);
    queue.current.push({
      type: "pace",
      step: current.step,
      origin: current.origin,
      started_ms: current.startedMs,
      elapsed_s: tenths(elapsed),
      idle_s: tenths(Math.min(current.idleS, elapsed)),
      at_s: stepActive.current,
    });
  }, []);

  const open = (step: string, origin: Interval["origin"]) => {
    interval.current = { step, origin, startedMs: Date.now(), idleS: 0 };
  };

  const push = useCallback(
    (event: RunEvent) => {
      const step = interval.current?.step;
      if (step !== undefined && ANSWERS.has(event.type)) {
        close();
        queue.current.push(event);
        open(step, "answer");
        return;
      }
      queue.current.push(event);
    },
    [close],
  );

  const advance = useCallback<RunTracker["advance"]>(
    async (from, to, extra) => {
      if (from) {
        // La page se tourne : son dernier intervalle se ferme avec elle.
        close();
        queue.current.push({
          type: "step",
          step: from,
          ended: true,
          active_s: stepActive.current,
          signal: extra?.signal ?? null,
          skipped: extra?.skipped ?? false,
        });
      }
      // Sans `from` (ouverture, reprise, étape sautée au plafond), l'intervalle
      // en cours n'est pas jugé : on n'a pas tourné la page, on y a été mené.
      interval.current = null;
      stepActive.current = 0;
      lastInteraction.current = Date.now();
      if (to) {
        queue.current.push({ type: "step", step: to, started: true });
        open(to, "open");
      }
      return send(to);
    },
    [send, close],
  );

  const flush = useCallback<RunTracker["flush"]>(
    async (current) => {
      if (current) queue.current.push({ type: "step", step: current, active_s: stepActive.current });
      return send(current);
    },
    [send],
  );

  return { push, advance, flush, activeSeconds: () => stepActive.current };
}
