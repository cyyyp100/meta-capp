import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { useT } from "../../i18n";
import { WhyButton } from "../science/WhyButton";
import { WarmUp } from "../session/WarmUp";

// SAS d'entrée d'une séance de langue : même rituel qu'avant un PDF (mise en condition
// ~30 s + warm-up de flashcards), mais les cartes sont filtrées par langue (dues +
// récentes). Le thème de la séance sert d'accroche (pas d'appel LLM → robuste hors-ligne).
export function LangEntrySas({
  language,
  label,
  theme,
  onStart,
}: {
  language: string;
  label: string;
  theme: string;
  onStart: () => void;
}) {
  const t = useT();
  const [phase, setPhase] = useState<"intro" | "review">("intro");
  // Attente de 30 s, passable après 15 s écoulées.
  const [left, setLeft] = useState(30);
  const canSkip = left <= 15;

  const { data: cards } = useQuery({
    queryKey: ["lang-warmup", language],
    queryFn: () => api.langWarmupCards(language),
    staleTime: Infinity,
  });

  // Décompte (phase intro) : à 0, on passe au warm-up (pas direct à la séance).
  useEffect(() => {
    if (phase !== "intro") return;
    if (left <= 0) {
      setPhase("review");
      return;
    }
    const id = setTimeout(() => setLeft((l) => l - 1), 1000);
    return () => clearTimeout(id);
  }, [left, phase]);

  // Warm-up sans carte disponible : on démarre la séance directement.
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
        <h2 style={{ fontFamily: "var(--font-title)", fontSize: 24, margin: "0 0 10px", color: "var(--text)" }}>{label}</h2>
        <p style={{ color: "var(--text-soft)", lineHeight: 1.6 }}>{t("lang.entry_text")}</p>
        <div style={{ marginTop: 12 }}>
          <WhyButton whyKey="entry" />
        </div>

        {theme && (
          <div style={{ margin: "16px auto", maxWidth: 460, background: "var(--accent-soft)", color: "var(--accent-hover)", borderRadius: "var(--radius-md)", padding: "12px 16px", fontSize: 14, lineHeight: 1.5 }}>
            💡 {theme}
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
            {canSkip ? t("entry.continue") : t("entry.skip_in", { n: left - 15 })}
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
