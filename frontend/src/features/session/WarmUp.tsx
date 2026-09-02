import { useState } from "react";

import { api } from "../../api/client";
import type { Flashcard } from "../../api/types";
import { useT } from "../../i18n";
import { WhyButton } from "../science/WhyButton";
import { SasOverlay } from "./SasOverlay";

// Warm-up clic-only partagé (SAS d'entrée PDF et séance de langue) : clic => retourne ;
// re-clic => revue neutre (avance la répétition espacée) + carte suivante. « Passer »
// démarre la session. Source partagée pour éviter la divergence entre les deux flux.
export function WarmUp({ cards, onDone }: { cards: Flashcard[]; onDone: () => void }) {
  const t = useT();
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const card = cards[i];

  function advance() {
    if (!flipped) {
      setFlipped(true);
      return;
    }
    api.reviewFlashcard(card.id, "partial").catch(() => {});
    if (i + 1 >= cards.length) onDone();
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
          <WhyButton whyKey="warmup" />
        </div>
        <div
          onClick={advance}
          style={{ minHeight: "min(62vh, 480px)", display: "grid", placeItems: "center", padding: 44, borderRadius: "var(--radius-lg)", border: "1px solid var(--border)", background: flipped ? "var(--warning-soft)" : "var(--surface)", boxShadow: "var(--shadow-md)", cursor: "pointer", fontSize: 24, fontFamily: "var(--font-title)" }}
        >
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", letterSpacing: 0.5, marginBottom: 16 }}>
              {flipped ? t("flash.a") : t("flash.q")}
            </div>
            {flipped ? card.back : card.front}
          </div>
        </div>
        <div style={{ marginTop: 16, display: "flex", gap: 14, justifyContent: "center", alignItems: "center" }}>
          <span style={{ color: "var(--muted)", fontSize: 13 }}>{flipped ? t("flash.tap_next") : t("flash.tap_reveal")}</span>
          <button onClick={onDone} style={{ border: "1px solid var(--border)", background: "var(--surface-soft)", color: "var(--text-soft)", borderRadius: "var(--radius-sm)", padding: "8px 16px", fontWeight: 600, cursor: "pointer" }}>{t("entry.start")}</button>
        </div>
      </div>
    </SasOverlay>
  );
}

