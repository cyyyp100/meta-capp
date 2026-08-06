import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { WhyButton } from "../science/WhyButton";
import { useT } from "../../i18n";
import { WarmUp } from "./WarmUp";

// SAS d'entrée : accroche de curiosité (LLM, 1 min, passable après 30 s) PUIS warm-up
// de 5 cartes sélectionnées par pertinence (clic-only), avant de démarrer la lecture.
export function EntrySas({ docId, title, onStart }: { docId: number; title: string; onStart: () => void }) {
  const t = useT();
  const [phase, setPhase] = useState<"intro" | "review">("intro");
  // SAS de 1 minute, passable seulement après 30 s écoulées.
  const [left, setLeft] = useState(60);
  const canSkip = left <= 30;

  const { data: hook } = useQuery({ queryKey: ["hook", docId], queryFn: () => api.docHook(docId, 1), staleTime: Infinity });
  // Warm-up : 5 cartes sélectionnées par pertinence (dues + récence × matière).
  const { data: cards } = useQuery({ queryKey: ["session-start", docId], queryFn: () => api.sessionStartCards(docId), staleTime: Infinity });

  // Compte à rebours (phase intro) : à 0, on passe au warm-up (pas direct à la lecture).
  useEffect(() => {
    if (phase !== "intro") return;
    if (left <= 0) {
      setPhase("review");
      return;
    }
    const id = setTimeout(() => setLeft((l) => l - 1), 1000);
    return () => clearTimeout(id);
  }, [left, phase]);

  // Warm-up sans carte disponible : on démarre la lecture directement.
  useEffect(() => {
    if (phase === "review" && cards && cards.length === 0) onStart();
  }, [phase, cards, onStart]);

  if (phase === "review") {
    if (!cards) {
      return (
        <div style={overlay}>
          <div style={{ color: "var(--muted)", fontStyle: "italic" }}>{t("common.loading")}</div>
        </div>
      );
    }
    if (cards.length > 0) return <WarmUp cards={cards} onDone={onStart} />;
    return <div style={overlay} />;
  }

  return (
    <div style={overlay}>
      <div style={{ textAlign: "center", maxWidth: 520, padding: "var(--space-xl)" }}>
        <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: 1, color: "var(--accent)", marginBottom: 12 }}>{t("entry.label")}</div>
        <h2 style={{ fontFamily: "var(--font-title)", fontSize: 24, margin: "0 0 10px", color: "var(--text)" }}>{title}</h2>
        <p style={{ color: "var(--text-soft)", lineHeight: 1.6 }}>{t("entry.text")}</p>
        <div style={{ marginTop: 12 }}>
          <WhyButton whyKey="entry" />
        </div>

        {hook?.hook && (
          <div style={{ margin: "16px auto", maxWidth: 460, background: "var(--accent-soft)", color: "var(--accent-hover)", borderRadius: "var(--radius-md)", padding: "12px 16px", fontSize: 14, lineHeight: 1.5 }}>
            💡 {hook.hook}
          </div>
        )}

        <div style={{ margin: "22px auto", width: 84, height: 84, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 30, fontWeight: 700, color: "var(--accent-hover)", background: "var(--accent-soft)", border: "2px solid var(--accent)" }}>
          {left}
        </div>

        <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
          <button
            onClick={() => setPhase("review")}
            disabled={!canSkip}
            style={{ border: "none", background: canSkip ? "var(--accent)" : "var(--muted-light)", color: "#fff", borderRadius: "var(--radius-sm)", padding: "10px 22px", fontWeight: 600, cursor: canSkip ? "pointer" : "not-allowed" }}
          >
            {canSkip ? t("entry.continue") : t("entry.skip_in", { n: left - 30 })}
          </button>
        </div>
      </div>
    </div>
  );
}

const overlay: React.CSSProperties = {
  position: "absolute",
  inset: 0,
  background: "var(--bg)",
  display: "grid",
  placeItems: "center",
  zIndex: 80,
};
