// useRunTracker — Événements d'une séance et temps réellement actif (E5, T2).
//
// Les événements (taps, réponses, auto-évaluations, cartes) s'accumulent et
// partent en UN lot à chaque changement d'étape : pas un appel par tap. Le
// temps d'une étape ne compte que tant que l'apprenant interagit ; au-delà du
// seuil d'inactivité fourni par le plan (`idle_cutoff_s`, config serveur), les
// secondes ne sont plus « effectives ». Le serveur recorrige tout et renvoie
// si le plafond de durée est atteint (R24) : c'est lui qui décide.
import { useCallback, useEffect, useRef } from "react";

import { api } from "../../../api/client";
import type { EventsResult, RunEvent } from "../../../api/feuilleton";

export interface RunTracker {
  push: (event: RunEvent) => void;
  /** Ferme l'étape courante, ouvre la suivante et envoie le lot. */
  advance: (from: string | null, to: string | null, extra?: { signal?: string | null; skipped?: boolean }) => Promise<EventsResult | null>;
  /** Envoie ce qui attend sans changer d'étape (sortie de la séance). */
  flush: (current: string | null) => Promise<EventsResult | null>;
  activeSeconds: () => number;
}

export function useRunTracker(runId: number | null, idleCutoffS: number): RunTracker {
  const queue = useRef<RunEvent[]>([]);
  // 0 = pas encore d'interaction ; posé au montage (pas pendant le rendu).
  const lastInteraction = useRef(0);
  const stepActive = useRef(0);

  useEffect(() => {
    lastInteraction.current = Date.now();
    const touch = () => {
      lastInteraction.current = Date.now();
    };
    const events = ["pointerdown", "keydown", "wheel", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    const timer = window.setInterval(() => {
      const idle = (Date.now() - lastInteraction.current) / 1000;
      if (document.visibilityState === "visible" && idle < idleCutoffS) stepActive.current += 1;
    }, 1000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, touch));
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

  const push = useCallback((event: RunEvent) => {
    queue.current.push(event);
  }, []);

  const advance = useCallback<RunTracker["advance"]>(
    async (from, to, extra) => {
      if (from) {
        queue.current.push({
          type: "step",
          step: from,
          ended: true,
          active_s: stepActive.current,
          signal: extra?.signal ?? null,
          skipped: extra?.skipped ?? false,
        });
      }
      stepActive.current = 0;
      lastInteraction.current = Date.now();
      if (to) queue.current.push({ type: "step", step: to, started: true });
      return send(to);
    },
    [send],
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
