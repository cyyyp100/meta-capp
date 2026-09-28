// Onboarding — Première visite d'une langue du pilote (F13, R25).
//
// Le principe de la méthode, le message « un peu tous les jours », les centres
// d'intérêt (ils nourrissent la bible du feuilleton), puis le choix : jamais
// étudié -> séance zéro ; déjà étudié -> test de niveau statique, corrigé côté
// serveur contre des clés écrites à la main. Pendant ce temps, l'épisode 1
// s'écrit en tâche de fond.
//
// Après le test, l'écran de résultat attend l'épisode 1 (2 à 5 minutes) au
// lieu d'ouvrir une séance qui ne serait qu'une attente (§ 14, n° 10) : le
// bouton ne s'active que quand il est prêt, ou quand son écriture a échoué —
// la séance repliée relance alors la génération.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../../api/client";
import type { PlacementItemView, PlacementOutcome } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { Card, chipBtn, ghostBtn, primaryBtn, StepTitle, Target } from "./ui";

const INTERESTS = ["cuisine", "voyages", "cinema", "sport", "musique", "nature", "histoire", "technologie", "art", "famille"];

type Stage = "intro" | "interests" | "placement" | "result";

export function Onboarding({
  language,
  label,
  rtl,
  onStart,
}: {
  language: string;
  label: string;
  rtl: boolean;
  /** Commence la première séance (zéro, ou épisode 1 après le test). */
  onStart: () => void;
}) {
  const t = useT();
  const [stage, setStage] = useState<Stage>("intro");
  const [picked, setPicked] = useState<string[]>([]);
  const [free, setFree] = useState("");
  const [items, setItems] = useState<PlacementItemView[]>([]);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [outcome, setOutcome] = useState<PlacementOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const interests = [...picked.map((k) => t(`feuil.interest.${k}`)), ...free.split(",").map((s) => s.trim()).filter(Boolean)];

  async function choose(hasStudied: boolean) {
    setBusy(true);
    setError(false);
    try {
      const res = await api.feuilletonOnboarding(language, interests, hasStudied);
      if (res.next === "placement") {
        setItems((await api.feuilletonPlacement(language)).items);
        setStage("placement");
      } else {
        onStart();
      }
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setBusy(true);
    try {
      setOutcome(await api.feuilletonPlacementSubmit(language, answers));
      setStage("result");
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  if (stage === "intro") {
    return (
      <Card>
        <StepTitle>{t("feuil.onb.title", { lang: label })}</StepTitle>
        <p>{t("feuil.onb.method")}</p>
        <p>{t("feuil.onb.episode")}</p>
        <p style={{ fontWeight: 600 }}>{t("feuil.onb.daily")}</p>
        <p style={{ color: "var(--muted)" }}>{t("feuil.onb.no_score")}</p>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button style={primaryBtn} onClick={() => setStage("interests")}>{t("feuil.next")}</button>
        </div>
      </Card>
    );
  }

  if (stage === "interests") {
    return (
      <Card>
        <StepTitle hint={t("feuil.onb.interests_hint")}>{t("feuil.onb.interests")}</StepTitle>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {INTERESTS.map((k) => (
            <button
              key={k}
              style={chipBtn(picked.includes(k))}
              aria-pressed={picked.includes(k)}
              onClick={() => setPicked((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]))}
            >
              {t(`feuil.interest.${k}`)}
            </button>
          ))}
        </div>
        <input
          value={free}
          onChange={(e) => setFree(e.target.value)}
          placeholder={t("feuil.onb.interests_free")}
          style={{ width: "100%", marginTop: 12, padding: "8px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }}
        />
        <p style={{ fontWeight: 600, marginTop: 18 }}>{t("feuil.onb.studied_q", { lang: label })}</p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button style={primaryBtn} disabled={busy} onClick={() => choose(false)}>{t("feuil.onb.never")}</button>
          <button style={ghostBtn} disabled={busy} onClick={() => choose(true)}>{t("feuil.onb.some")}</button>
        </div>
        {error && <p style={{ color: "var(--danger)" }}>{t("feuil.error")}</p>}
      </Card>
    );
  }

  if (stage === "placement") {
    return (
      <Card>
        <StepTitle hint={t("feuil.placement.hint")}>{t("feuil.placement.title")}</StepTitle>
        <div style={{ display: "grid", gap: 18 }}>
          {items.map((it, i) => (
            <div key={it.id}>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>{`${i + 1}/${items.length} · ${it.cefr}`}</div>
              <div style={{ fontWeight: 600, margin: "4px 0 8px" }}><Target rtl={rtl && it.kind !== "lecture"}>{it.prompt}</Target></div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {it.choices.map((c, ci) => (
                  <button key={ci} style={chipBtn(answers[it.id] === ci)} onClick={() => setAnswers((a) => ({ ...a, [it.id]: ci }))}>
                    <bdi dir="auto">{c}</bdi>
                  </button>
                ))}
                <button style={chipBtn(false)} onClick={() => setAnswers((a) => { const n = { ...a }; delete n[it.id]; return n; })}>
                  {t("feuil.placement.dunno")}
                </button>
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
          <button style={primaryBtn} disabled={busy} onClick={submit}>{t("feuil.placement.submit")}</button>
        </div>
        {error && <p style={{ color: "var(--danger)" }}>{t("feuil.error")}</p>}
      </Card>
    );
  }

  return <PlacementResult language={language} outcome={outcome} onStart={onStart} />;
}

function PlacementResult({
  language,
  outcome,
  onStart,
}: {
  language: string;
  outcome: PlacementOutcome | null;
  onStart: () => void;
}) {
  const t = useT();
  const { data: status } = useQuery({
    queryKey: ["feuil", "status", language],
    queryFn: () => api.feuilletonStatus(language),
    refetchInterval: (q) => {
      const next = q.state.data?.next_status;
      return next === "ready" || next === "failed" ? false : 3000;
    },
  });
  const next = status?.next_status;
  return (
    <Card>
      <StepTitle>{t("feuil.placement.result", { level: outcome?.level ?? "A1" })}</StepTitle>
      <p>{t("feuil.placement.start", { point: outcome?.start_point ?? "" })}</p>
      <p style={{ color: next === "failed" ? "var(--warning)" : "var(--muted)" }} aria-live="polite">
        {next === "ready"
          ? t("feuil.placement.ready")
          : next === "failed"
            ? t("feuil.placement.failed")
            : t("feuil.placement.writing")}
      </p>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button style={primaryBtn} disabled={next !== "ready" && next !== "failed"} onClick={onStart}>
          {next === "failed" ? t("feuil.placement.go_anyway") : t("feuil.placement.go")}
        </button>
      </div>
    </Card>
  );
}
