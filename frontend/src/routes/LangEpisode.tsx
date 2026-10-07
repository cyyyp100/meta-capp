// routes/LangEpisode.tsx — Séance plein écran de la méthode « feuilleton » (F2).
//
// Machine à étapes pilotée par le plan que renvoie le serveur : rien ne
// s'improvise ici, et rien n'attend Clikoda — l'épisode du jour existe déjà, le
// suivant s'écrit pendant qu'on lit celui-ci. La barre de progression compte
// des étapes, jamais des secondes (pas de compte à rebours). Si le serveur
// signale le plafond de durée, on saute directement à l'au revoir (R24).
//
// Rituels : le sas d'entrée — le même qu'avant un PDF, avec les cartes de la
// langue pour révision éclair — précède chaque séance, AVANT que son plan ne soit construit — les
// cartes qu'il fait réviser ne sont plus dues, et la séance ne les ressert pas.
// Il n'y en a pas au premier accès : l'onboarding (et son test de niveau) en
// tient lieu, et une langue neuve n'a encore aucune carte. Le rappel reste la
// première étape du plan, l'au revoir et son bilan font le sas de sortie, le
// sas de repos suit.
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { RunCompletion, RunPlan } from "../api/feuilleton";
import { EndScreen } from "../features/lang/feuilleton/EndScreen";
import { Onboarding } from "../features/lang/feuilleton/Onboarding";
import {
  AccueilStep,
  AuRevoirStep,
  CartesStep,
  ControleStep,
  EcritureStep,
  EpisodePassStep,
  JalonStep,
  JeuxStep,
  NotesStep,
  PhrasesStep,
  PointStep,
  RappelStep,
  RecapStep,
  RelectureStep,
  SecondWaveStep,
  type StepProps,
} from "../features/lang/feuilleton/Steps";
import { ghostBtn } from "../features/lang/feuilleton/ui";
import { useRunTracker } from "../features/lang/feuilleton/useRunTracker";
import { EntrySas } from "../features/session/EntrySas";
import { PostExitRestSas } from "../features/session/PostExitRestSas";
import { useT } from "../i18n";

type Phase = "onboarding" | "entry" | "loading" | "run" | "end" | "rest" | "error";

const VIEWS: Record<string, (p: StepProps) => JSX.Element> = {
  accueil: AccueilStep,
  phrases: PhrasesStep,
  ecriture: EcritureStep,
  rappel: RappelStep,
  episode_p1: EpisodePassStep,
  episode_p2: EpisodePassStep,
  notes: NotesStep,
  point: PointStep,
  jeux: JeuxStep,
  deuxieme_vague: SecondWaveStep,
  jalon: JalonStep,
  relecture: RelectureStep,
  cartes: CartesStep,
  recap: RecapStep,
  controle: ControleStep,
  au_revoir: AuRevoirStep,
};

export function LangEpisode() {
  const t = useT();
  const navigate = useNavigate();
  const { state } = useLocation();
  const nav = (state ?? {}) as { language?: string; label?: string; rtl?: boolean; mode?: "court" | "relecture"; onboarding?: boolean };
  const language = nav.language;
  const [phase, setPhase] = useState<Phase>(nav.onboarding ? "onboarding" : "entry");
  const [plan, setPlan] = useState<RunPlan | null>(null);
  const [index, setIndex] = useState(0);
  const [result, setResult] = useState<RunCompletion | null>(null);
  const endReason = useRef<"fini" | "plafond">("fini");
  const tracker = useRunTracker(plan?.run_id ?? null, plan?.idle_cutoff_s ?? 90);
  const started = useRef(false);
  const scroller = useRef<HTMLDivElement>(null);
  // Cartes révisées au sas d'entrée : le serveur les décompte du plafond de la séance.
  const warmedUp = useRef(0);

  useEffect(() => {
    if (!language) navigate("/lang");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language]);

  // Le premier lot (ouverture de l'étape) part dès que le tracker connaît la séance.
  useEffect(() => {
    if (plan && !started.current) {
      started.current = true;
      void tracker.advance(null, plan.steps[index]?.key ?? null);
    }
  }, [plan, index, tracker]);

  async function start(mode?: "court" | "relecture") {
    setPhase("loading");
    try {
      const p = await api.feuilletonRunStart(language!, mode, warmedUp.current);
      // Séance du jour reprise à l'étape atteinte (R2).
      const resumeAt = p.resumed && p.current_step ? Math.max(0, p.steps.findIndex((s) => s.key === p.current_step)) : 0;
      started.current = false;
      setIndex(resumeAt);
      setPlan(p);
      setPhase("run");
    } catch {
      setPhase("error");
    }
  }

  async function next(extra?: { signal?: string | null; feeling?: string | null }) {
    if (!plan) return;
    const current = plan.steps[index];
    if (current.kind === "au_revoir" || index >= plan.steps.length - 1) {
      await tracker.advance(current.key, null, { signal: extra?.signal });
      try {
        setResult(await api.feuilletonComplete(plan.run_id, endReason.current, extra?.feeling ?? null));
      } catch {
        setResult(null);
      }
      setPhase("end");
      return;
    }
    let target = index + 1;
    const res = await tracker.advance(current.key, plan.steps[target].key, { signal: extra?.signal });
    if (res?.cap_reached) {
      // Plafond atteint : les étapes restantes non essentielles sont sautées,
      // l'au revoir est toujours joué.
      endReason.current = "plafond";
      const goodbye = plan.steps.findIndex((s) => s.kind === "au_revoir");
      if (goodbye > target) {
        target = goodbye;
        await tracker.advance(null, plan.steps[target].key);
      }
    }
    setIndex(target);
    scroller.current?.scrollTo({ top: 0 });
  }

  async function exit() {
    // La séance reste ouverte : elle se reprendra à cette étape aujourd'hui.
    if (plan && phase === "run") await tracker.flush(plan.steps[index]?.key ?? null);
    navigate("/lang");
  }

  if (phase === "rest") return <PostExitRestSas onDone={() => navigate("/lang")} skipKey="post_exit_rest.skip_lang" />;

  if (phase === "entry" && language) {
    return (
      <div style={{ position: "fixed", inset: 0, background: "var(--bg)" }}>
        <EntrySas
          source={{ kind: "language", language }}
          title={nav.label ?? language}
          onStart={(timings) => {
            warmedUp.current = timings.length;
            void start(nav.mode);
          }}
          onLeave={() => navigate("/lang")}
        />
      </div>
    );
  }

  return (
    <div ref={scroller} style={{ position: "fixed", inset: 0, background: "var(--bg)", overflowY: "auto" }}>
      <div style={{ padding: "14px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <button onClick={exit} style={ghostBtn}>{phase === "run" ? t("feuil.exit") : t("feuil.back")}</button>
        {plan && phase === "run" && <StepsBar total={plan.steps.length} index={index} />}
      </div>
      <div style={{ padding: "0 20px 60px", maxWidth: 820, margin: "0 auto" }}>
        {phase === "onboarding" && (
          <Onboarding language={language!} label={nav.label ?? language!} rtl={!!nav.rtl} onStart={() => void start()} />
        )}
        {phase === "loading" && <p style={{ color: "var(--muted)" }}>{t("common.loading")}</p>}
        {phase === "error" && (
          <div>
            <p style={{ color: "var(--danger)" }}>{t("feuil.error")}</p>
            <button style={ghostBtn} onClick={() => void start(nav.mode)}>{t("common.retry")}</button>
          </div>
        )}
        {phase === "run" && plan && (() => {
          const step = plan.steps[index];
          const View = VIEWS[step.kind];
          return View ? (
            <View key={step.key} step={step} plan={plan} tracker={tracker} onNext={(extra) => void next(extra)} />
          ) : (
            <button style={ghostBtn} onClick={() => void next()}>{t("feuil.next")}</button>
          );
        })()}
        {phase === "end" && (
          result ? (
            <EndScreen result={result} language={language!} onClose={() => setPhase("rest")} />
          ) : (
            <button style={ghostBtn} onClick={() => setPhase("rest")}>{t("feuil.end.close")}</button>
          )
        )}
      </div>
    </div>
  );
}

function StepsBar({ total, index }: { total: number; index: number }) {
  return (
    <div style={{ display: "flex", gap: 4, flex: 1, maxWidth: 420 }} aria-label={`${index + 1}/${total}`}>
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            height: 6,
            borderRadius: 3,
            background: i <= index ? "var(--accent)" : "var(--border)",
            opacity: i <= index ? 1 : 0.6,
          }}
        />
      ))}
    </div>
  );
}
