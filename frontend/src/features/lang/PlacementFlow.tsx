// features/lang/PlacementFlow.tsx — Test de niveau de la première séance.
//
// Gate « as-tu déjà étudié ? » : si non, on saute le test (point d'entrée débutant) ;
// si oui, on génère un test complet (~15-20 items) corrigé côté serveur, qui fixe le
// niveau CEFR d'entrée. `onDone` est appelé une fois le point d'entrée fixé : le parent
// relance alors le démarrage de la séance (qui passe désormais le gate).
import { useState } from "react";

import { api } from "../../api/client";
import type { LangPlacementItem, LangPlacementResult } from "../../api/client";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";

type Step = "gate" | "generating" | "test" | "grading" | "result";

export function PlacementFlow({
  language,
  label,
  onDone,
}: {
  language: string;
  label: string;
  onDone: () => void;
}) {
  const t = useT();
  const [step, setStep] = useState<Step>("gate");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [items, setItems] = useState<LangPlacementItem[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<LangPlacementResult | null>(null);

  async function skip() {
    if (busy) return;
    setBusy(true);
    try {
      await api.languagePlacementSkip(language);
      onDone();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  async function startTest() {
    if (busy) return;
    setBusy(true);
    setError(false);
    setStep("generating");
    try {
      const res = await api.languagePlacementStart(language);
      if (res.error || !res.items?.length) {
        setError(true);
        setStep("gate");
      } else {
        setItems(res.items);
        setStep("test");
      }
    } catch {
      setError(true);
      setStep("gate");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (busy) return;
    setBusy(true);
    setStep("grading");
    try {
      const res = await api.languagePlacementSubmit(language, answers);
      setResult(res);
      setStep("result");
    } catch {
      setError(true);
      setStep("test");
    } finally {
      setBusy(false);
    }
  }

  const card: React.CSSProperties = {
    maxWidth: 720,
    margin: "0 auto",
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-lg)",
    boxShadow: "var(--shadow-sm)",
    padding: "var(--space-xl)",
  };

  if (step === "gate") {
    return (
      <div style={card}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--accent-ink)" }}>
          {t("lang.placement_title")}
        </div>
        <h2 style={{ fontSize: "var(--text-h2)", margin: "8px 0 4px" }}>{t("lang.placement_gate", { language: label })}</h2>
        <p style={{ color: "var(--muted)", marginTop: 0 }}>{t("lang.placement_gate_sub")}</p>
        {error && <p style={{ color: "var(--danger)" }}>{t("lang.placement_error")}</p>}
        <div style={{ display: "flex", gap: 12, marginTop: 18, flexWrap: "wrap" }}>
          <button onClick={skip} disabled={busy} style={btn("var(--surface)", "var(--text)")}>
            {t("lang.placement_never")}
          </button>
          <button onClick={startTest} disabled={busy} style={btn("var(--accent)", "var(--on-accent)")}>
            {busy ? "…" : t("lang.placement_yes")}
          </button>
        </div>
      </div>
    );
  }

  if (step === "generating") {
    return (
      <div style={card}>
        <p style={{ color: "var(--muted)", fontStyle: "italic" }}>{t("lang.placement_generating")}</p>
      </div>
    );
  }

  if (step === "grading") {
    return (
      <div style={card}>
        <p style={{ color: "var(--muted)", fontStyle: "italic" }}>{t("lang.placement_grading")}</p>
      </div>
    );
  }

  if (step === "result" && result) {
    return (
      <div style={card}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--accent-ink)" }}>
          {t("lang.placement_result")}
        </div>
        <div style={{ fontSize: 40, fontWeight: 800, margin: "6px 0" }}>{result.level ?? "A1"}</div>
        {result.comment && <p style={{ color: "var(--text-soft)" }}>{result.comment}</p>}
        <button onClick={onDone} style={{ ...btn("var(--success)", "var(--on-status)"), marginTop: 16 }}>
          {t("lang.placement_start_lesson")}
        </button>
      </div>
    );
  }

  // step === "test"
  const allAnswered = items.every((it) => (answers[String(it.id)] ?? "").trim().length > 0);
  return (
    <div style={card}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--accent-ink)" }}>
        {t("lang.placement_title")}
      </div>
      <h2 style={{ fontSize: "var(--text-h3)", margin: "8px 0 16px" }}>{label}</h2>
      {error && <p style={{ color: "var(--danger)" }}>{t("lang.placement_error")}</p>}
      <div style={{ display: "grid", gap: 14 }}>
        {items.map((it, i) => (
          <PlacementItem
            key={String(it.id)}
            index={i}
            item={it}
            value={answers[String(it.id)] ?? ""}
            onAnswer={(v) => setAnswers((a) => ({ ...a, [String(it.id)]: v }))}
          />
        ))}
      </div>
      <button onClick={submit} disabled={busy || !allAnswered} style={{ ...btn("var(--accent)", "var(--on-accent)"), marginTop: 18, opacity: allAnswered ? 1 : 0.5 }}>
        {t("lang.placement_submit")}
      </button>
    </div>
  );
}

function PlacementItem({
  index,
  item,
  value,
  onAnswer,
}: {
  index: number;
  item: LangPlacementItem;
  value: string;
  onAnswer: (v: string) => void;
}) {
  const t = useT();
  const letters = ["A", "B", "C", "D"];
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>
        {index + 1}. {item.question}
      </div>
      {item.format === "qcm" ? (
        <div style={{ display: "grid", gap: 6 }}>
          {(item.choices ?? []).map((choice, i) => {
            const letter = letters[i];
            const picked = value === letter;
            return (
              <button
                key={i}
                onClick={() => onAnswer(letter)}
                dir="auto"
                style={{
                  textAlign: "left",
                  padding: "8px 10px",
                  borderRadius: "var(--radius-sm)",
                  border: `1px solid ${picked ? "var(--accent)" : "var(--border)"}`,
                  background: picked ? "var(--accent-soft)" : "var(--surface)",
                  color: "var(--text)",
                  cursor: "pointer",
                }}
              >
                {choice}
              </button>
            );
          })}
        </div>
      ) : (
        <AutoGrowTextarea
          value={value}
          onChange={(e) => onAnswer(e.target.value)}
          placeholder={t("lang.your_answer")}
          dir="auto"
          style={{ width: "100%", padding: "8px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }}
        />
      )}
    </div>
  );
}

function btn(bg: string, color: string): React.CSSProperties {
  return {
    border: "1px solid var(--border)",
    background: bg,
    color,
    borderRadius: "var(--radius-sm)",
    padding: "10px 18px",
    fontWeight: 600,
    cursor: "pointer",
  };
}
