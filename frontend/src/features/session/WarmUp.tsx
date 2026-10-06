import { useEffect, useRef, useState } from "react";

import { api } from "../../api/client";
import type { Flashcard } from "../../api/types";
import { useT } from "../../i18n";
import { WhyButton } from "../science/WhyButton";
import { SasOverlay } from "./SasOverlay";

/** Temps passé sur les deux faces d'une carte, jugé côté serveur (services/warmup.py). */
export interface WarmUpTiming {
  card_id: number;
  front_ms: number;
  back_ms: number;
}

// Warm-up clic-only partagé (SAS d'entrée PDF et séance de langue) : clic => retourne ;
// re-clic => revue neutre (avance la répétition espacée) + carte suivante. Source
// partagée pour éviter la divergence entre les deux flux.
//
// On ne PASSE pas la révision : il n'y a plus de bouton pour l'écourter. Ce qui
// s'y mesure, c'est son rythme — le temps sur chaque face, renvoyé à `onDone` —
// et Clikoda le lit (trop vite : on clique sans se tester ; trop lent : la trace
// est fragile ; beaucoup trop long : l'attention est ailleurs).
export function WarmUp({
  cards,
  onDone,
  demo = false,
}: {
  cards: Flashcard[];
  onDone: (timings: WarmUpTiming[]) => void;
  /** Warm-up de la visite guidée : cartes fictives, aucune révision écrite, aucun temps remonté. */
  demo?: boolean;
}) {
  const t = useT();
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const card = cards[i];

  // Chronomètre de la face affichée. Le temps passé dans « Pourquoi ? » en est
  // retiré : lire la justification n'est ni se presser ni décrocher.
  const faceStart = useRef(0);
  useEffect(() => {
    faceStart.current = performance.now(); // la première carte est à l'écran
  }, []);
  const whyOpenedAt = useRef<number | null>(null);
  const whyMs = useRef(0);
  const frontMs = useRef(0);
  const timings = useRef<WarmUpTiming[]>([]);

  function closeFace(now: number): number {
    const ms = Math.max(0, Math.round(now - faceStart.current - whyMs.current));
    faceStart.current = now;
    whyMs.current = 0;
    return ms;
  }

  function onWhyOpenChange(open: boolean) {
    const now = performance.now();
    if (open) whyOpenedAt.current = now;
    else if (whyOpenedAt.current !== null) {
      whyMs.current += now - whyOpenedAt.current;
      whyOpenedAt.current = null;
    }
  }

  function advance() {
    const now = performance.now();
    if (!flipped) {
      frontMs.current = closeFace(now);
      setFlipped(true);
      return;
    }
    timings.current.push({ card_id: card.id, front_ms: frontMs.current, back_ms: closeFace(now) });
    // La démonstration n'écrit rien : ses cartes n'existent pas en base, et une
    // révision enregistrée avancerait une répétition espacée qui n'a pas lieu.
    if (!demo) api.reviewFlashcard(card.id, "partial").catch(() => {});
    if (i + 1 >= cards.length) onDone(demo ? [] : timings.current);
    else {
      setI((v) => v + 1);
      setFlipped(false);
    }
  }

  return (
    <SasOverlay contained>
      <div style={{ textAlign: "center", width: "min(820px, 92vw)", padding: "var(--space-xl)" }}>
        <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: 1, color: "var(--accent-ink)", marginBottom: 12 }}>
          {t("entry.warmup_title")} · {i + 1}/{cards.length}
        </div>
        <div style={{ margin: "0 0 14px" }}>
          <WhyButton whyKey="warmup" onOpenChange={onWhyOpenChange} />
        </div>
        <div
          data-tour="warmup-card"
          onClick={advance}
          style={{ minHeight: "min(62vh, 480px)", display: "grid", placeItems: "center", padding: 44, borderRadius: "var(--radius-lg)", border: "1px solid var(--border)", background: flipped ? "var(--warning-soft)" : "var(--surface)", boxShadow: "var(--shadow-md)", cursor: "pointer", fontSize: 24, fontFamily: "var(--font-title)" }}
        >
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", letterSpacing: 0.5, marginBottom: 16 }}>
              {flipped ? t("flash.a") : t("flash.q")}
            </div>
            {flipped ? card.back : card.front}
            {/* Carte de langue : la prononciation accompagne le mot au verso. */}
            {flipped && card.pronunciation && (
              <div title={t("lang.phonetic")} style={{ marginTop: 10, fontSize: 18, fontStyle: "italic", color: "var(--muted)" }}>
                [{card.pronunciation}]
              </div>
            )}
          </div>
        </div>
        <div style={{ marginTop: 16, color: "var(--muted)", fontSize: 13 }}>
          {flipped ? t("flash.tap_next") : t("flash.tap_reveal")}
        </div>
      </div>
    </SasOverlay>
  );
}

