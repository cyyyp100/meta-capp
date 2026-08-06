import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { Flashcard } from "../api/types";
import { AutoGrowTextarea } from "../components/AutoGrowTextarea";
import { useT } from "../i18n";

const DIFFICULTY_COLORS = ["var(--success)", "var(--accent)", "var(--warning)", "var(--danger)"];

export function Flashcards() {
  const t = useT();
  const qc = useQueryClient();
  const [reviewing, setReviewing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [front, setFront] = useState("");
  const [back, setBack] = useState("");
  const [difficulty, setDifficulty] = useState<number>(0);
  const [tag, setTag] = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["flashcards", difficulty, tag],
    queryFn: () => api.flashcards({ difficulty: difficulty || undefined, tags: tag || undefined }),
  });

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["flashcards"] });
  }

  async function create() {
    if (!front.trim() || !back.trim()) return;
    await api.createFlashcard(front.trim(), back.trim(), "manual");
    setFront("");
    setBack("");
    setCreating(false);
    invalidate();
  }

  async function remove(id: number) {
    await api.deleteFlashcard(id);
    invalidate();
  }

  if (reviewing && data && data.length > 0) {
    return <ReviewSession cards={data} onDone={() => setReviewing(false)} />;
  }

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "var(--space-xl)" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontFamily: "var(--font-title)", fontSize: 32, margin: "0 0 4px" }}>{t("flash.title")}</h1>
          <p style={{ color: "var(--muted)", marginTop: 0 }}>{data ? t("flash.count", { n: data.length }) : ""}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => setCreating((c) => !c)} style={btnSecondary}>
            {t("flash.create")}
          </button>
          {data && data.length > 0 && (
            <button onClick={() => setReviewing(true)} style={btnPrimary}>
              {t("flash.review")}
            </button>
          )}
        </div>
      </div>

      {creating && (
        <div style={{ marginTop: 16, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-lg)" }}>
          <AutoGrowTextarea value={front} onChange={(e) => setFront(e.target.value)} placeholder={t("flash.front")} style={field} />
          <AutoGrowTextarea value={back} onChange={(e) => setBack(e.target.value)} placeholder={t("flash.back")} style={{ ...field, marginTop: 8 }} />
          <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <button onClick={() => setCreating(false)} style={btnSecondary}>{t("common.cancel")}</button>
            <button onClick={create} style={btnPrimary}>{t("common.save")}</button>
          </div>
        </div>
      )}

      {/* Filtres */}
      <div style={{ display: "flex", gap: 10, marginTop: 16, alignItems: "center" }}>
        <input value={tag} onChange={(e) => setTag(e.target.value)} placeholder={t("flash.filter_tag")} style={{ ...field, maxWidth: 220 }} />
        <select value={difficulty} onChange={(e) => setDifficulty(Number(e.target.value))} style={{ ...field, maxWidth: 160 }}>
          <option value={0}>{t("flash.all_diff")}</option>
          <option value={1}>{t("flash.easy")}</option>
          <option value={2}>{t("flash.medium")}</option>
          <option value={3}>{t("flash.hard")}</option>
        </select>
      </div>

      {isLoading && <p style={{ color: "var(--muted)" }}>{t("common.loading")}</p>}
      {isError && <p style={{ color: "var(--danger)" }}>{t("flash.error")}</p>}
      {data && data.length === 0 && (
        <div style={{ marginTop: 32, color: "var(--muted)", fontStyle: "italic" }}>{t("flash.empty")}</div>
      )}

      <div style={{ display: "grid", gap: "var(--space-md)", marginTop: "var(--space-lg)" }}>
        {data?.map((card) => (
          <CardRow key={card.id} card={card} onDelete={() => remove(card.id)} />
        ))}
      </div>
    </div>
  );
}

function ReviewSession({ cards, onDone }: { cards: Flashcard[]; onDone: () => void }) {
  const t = useT();
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const card = cards[index];

  // Clic unique : recto -> verso ; verso -> revue neutre (fait avancer la répétition
  // espacée) puis carte suivante. Pas d'auto-évaluation, pas de boutons.
  function advance() {
    if (!flipped) {
      setFlipped(true);
      return;
    }
    api.reviewFlashcard(card.id, "partial").catch(() => {});
    if (index + 1 >= cards.length) onDone();
    else {
      setIndex((i) => i + 1);
      setFlipped(false);
    }
  }

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", minHeight: "100%", padding: "var(--space-xl)", display: "flex", flexDirection: "column", alignItems: "center" }}>
      <div style={{ alignSelf: "stretch", display: "flex", justifyContent: "space-between", color: "var(--muted)" }}>
        <button onClick={onDone} style={{ border: "none", background: "transparent", color: "var(--muted)", cursor: "pointer" }}>{t("common.quit")}</button>
        <span style={{ fontWeight: 600 }}>{index + 1} / {cards.length}</span>
      </div>
      <div
        onClick={advance}
        style={{
          marginTop: 24, width: "100%", minHeight: "min(68vh, 560px)", display: "grid", placeItems: "center", textAlign: "center",
          padding: 48, borderRadius: "var(--radius-lg)", border: "1px solid var(--border)",
          background: flipped ? "var(--warning-soft)" : "var(--surface)", boxShadow: "var(--shadow-md)",
          cursor: "pointer", fontSize: 26, fontFamily: "var(--font-title)",
        }}
      >
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", letterSpacing: 0.5, marginBottom: 16 }}>
            {flipped ? t("flash.a") : t("flash.q")}
          </div>
          {flipped ? card.back : card.front}
        </div>
      </div>
      <div style={{ marginTop: 16, color: "var(--muted)", fontSize: 13 }}>
        {flipped ? t("flash.tap_next") : t("flash.tap_reveal")}
      </div>
    </div>
  );
}

function CardRow({ card, onDelete }: { card: Flashcard; onDelete: () => void }) {
  const diffColor = DIFFICULTY_COLORS[Math.max(1, Math.min(3, card.difficulty))] ?? "var(--accent)";
  return (
    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderLeft: `4px solid ${diffColor}`, borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-sm)", padding: "var(--space-md) var(--space-lg)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
        <div style={{ fontWeight: 600 }}>{card.front}</div>
        <button onClick={onDelete} title="Supprimer" style={{ border: "none", background: "transparent", color: "var(--muted)", cursor: "pointer", fontSize: 16 }}>
          🗑
        </button>
      </div>
      <div style={{ color: "var(--text-soft)", marginTop: 6 }}>{card.back}</div>
      <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
        {card.document_title && <Pill>{card.document_title}</Pill>}
        {card.tags.map((tg) => (
          <Pill key={tg} accent>{tg}</Pill>
        ))}
      </div>
    </div>
  );
}

function Pill({ children, accent }: { children: React.ReactNode; accent?: boolean }) {
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 999, background: accent ? "var(--accent-soft)" : "var(--bg-alt)", color: accent ? "var(--accent-hover)" : "var(--muted)" }}>
      {children}
    </span>
  );
}

const btnPrimary: React.CSSProperties = { border: "none", background: "var(--accent)", color: "#fff", borderRadius: "var(--radius-sm)", padding: "10px 18px", fontWeight: 600, cursor: "pointer" };
const btnSecondary: React.CSSProperties = { border: "1px solid var(--border)", background: "var(--surface-soft)", color: "var(--text-soft)", borderRadius: "var(--radius-sm)", padding: "10px 16px", fontWeight: 600, cursor: "pointer" };
const field: React.CSSProperties = { width: "100%", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "9px 12px", background: "var(--bg)", color: "var(--text)", fontSize: 14, fontFamily: "var(--font-ui)" };
