import { useQuery } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

import { api } from "../../api/client";
import type { Flashcard } from "../../api/types";
import { DEMO_CARDS } from "../reader/demoScript";
import { currentStep, useTour } from "../tour/useTour";
import { useT } from "../../i18n";
import { WhyButton } from "../science/WhyButton";
import { SasOverlay } from "./SasOverlay";
import { WarmUp } from "./WarmUp";

// SAS d'entrée : accroche de curiosité (LLM, 1 min, passable après 30 s) PUIS warm-up
// de 5 cartes sélectionnées par pertinence (clic-only), avant de démarrer la lecture.
//
// C'est un moment RITUEL, pas un écran d'attente : sa raison d'être est de faire
// ralentir avant de lire. D'où le cercle qui respire à la cadence d'une
// inspiration lente (≈5,5 s) et l'anneau qui se remplit — la durée devient
// perceptible au lieu d'être un simple chiffre qui décrémente.

const TOTAL_SECONDS = 60;
/** En dessous de ce reliquat, on peut passer à la suite. */
const SKIP_AT = 30;
/** Visite guidée : on montre le rituel, on ne l'impose pas. */
const DEMO_SECONDS = 8;

const RING_RADIUS = 46;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

export function EntrySas({
  docId,
  title,
  onStart,
  onLeave,
  demo = false,
}: {
  docId: number;
  title: string;
  onStart: () => void;
  /**
   * « ← Bibliothèque » : on a ouvert le mauvais document. Le sas est le SEUL
   * moment où ce retour a un sens — rien n'a encore été lu, rien ne doit être
   * compté. Absent en démonstration : la visite tient le fil.
   */
  onLeave?: () => void;
  /**
   * Séance de démonstration de la visite guidée. Trois différences, toutes
   * pour la même raison — le sas est un rituel de RALENTISSEMENT, et on ne
   * ralentit pas quelqu'un qui découvre le produit :
   *   * le compte à rebours passe de 60 s à quelques secondes, et ne franchit
   *     plus le sas de lui-même : c'est la visite qui le fait, au clic ;
   *   * l'accroche de curiosité est écrite d'avance (pas d'appel LLM, donc pas
   *     d'attente ni de dépendance à Ollama au premier lancement) ;
   *   * le warm-up joue DEUX cartes écrites d'avance (`DEMO_CARDS`) au lieu de
   *     celles de la répétition espacée : l'utilisateur n'en a encore aucune, et
   *     réviser le document qu'on s'apprête à découvrir n'aurait aucun sens.
   *     Elles portent sur de la connaissance générale, se répondent sans rien
   *     avoir lu, et rien n'est écrit quand on les franchit.
   */
  demo?: boolean;
}) {
  const t = useT();
  const reduce = useReducedMotion();
  const [phase, setPhase] = useState<"intro" | "review">("intro");
  const totalSeconds = demo ? DEMO_SECONDS : TOTAL_SECONDS;
  // SAS de 1 minute, passable seulement après 30 s écoulées.
  const [left, setLeft] = useState(totalSeconds);
  const canSkip = demo || left <= SKIP_AT;

  const { data: hook } = useQuery({
    queryKey: ["hook", docId],
    queryFn: () => api.docHook(docId, 1),
    staleTime: Infinity,
    enabled: !demo,
  });
  // Warm-up : 5 cartes sélectionnées par pertinence (dues + récence × matière).
  const { data: cards } = useQuery({
    queryKey: ["session-start", docId],
    queryFn: () => api.sessionStartCards(docId),
    staleTime: Infinity,
    enabled: !demo,
  });
  const hookText = demo ? t("demo.entry_hook") : hook?.hook;

  // Les cartes du warm-up : celles de la répétition espacée, ou les deux cartes
  // écrites d'avance de la visite.
  const demoCards: Flashcard[] = DEMO_CARDS.map((c) => ({
    id: c.id,
    front: t(c.frontKey),
    back: t(c.backKey),
    tags: [],
    difficulty: 0,
    source: "demo",
    document_title: null,
    chapter_title: null,
  }));

  // C'est la VISITE qui fait passer aux cartes, à l'étape qui les explique, et
  // non le compte à rebours : il ne franchit plus rien de lui-même (cf. juste
  // au-dessus), pour qu'aucun écran ne change au milieu d'une bulle.
  const atWarmUpStep = useTour((s) => currentStep(s)?.id === "warmup");
  useEffect(() => {
    if (demo && atWarmUpStep) setPhase("review");
  }, [demo, atWarmUpStep]);

  // Compte à rebours (phase intro) : à 0, on passe au warm-up (pas direct à la lecture).
  useEffect(() => {
    if (phase !== "intro") return;
    if (left <= 0) {
      // En démonstration, le compte à rebours MONTRE le rituel, il ne le
      // franchit pas : il s'arrête à 0 et le sas reste à l'écran. Il appelait
      // `onStart()`, et l'écran changeait donc de lui-même au milieu de la
      // bulle qui explique le sas — la seule étape de la visite qu'on ne
      // pouvait pas lire à son rythme. Ce qui fait entrer dans la lecture est
      // un clic : « Suivant » dans la visite, ou « Continuer » ici.
      if (!demo) setPhase("review");
      return;
    }
    const id = setTimeout(() => setLeft((l) => l - 1), 1000);
    return () => clearTimeout(id);
  }, [left, phase, demo, onStart]);

  // Warm-up sans carte disponible : on démarre la lecture directement.
  useEffect(() => {
    if (phase === "review" && cards && cards.length === 0) onStart();
  }, [phase, cards, onStart]);

  if (phase === "review") {
    if (demo) return <WarmUp cards={demoCards} onDone={onStart} demo />;
    if (!cards) {
      return (
        <SasOverlay contained>
          {onLeave && !demo && <LeaveButton onLeave={onLeave} />}
          <div className="text-muted-foreground italic">{t("common.loading")}</div>
        </SasOverlay>
      );
    }
    if (cards.length > 0) return <WarmUp cards={cards} onDone={onStart} />;
    return <SasOverlay contained />;
  }

  const elapsed = totalSeconds - left;

  return (
    <SasOverlay contained>
      {/* Le retour n'attend pas les 30 s : se tromper de document est
          précisément le cas où l'on ne veut pas ralentir. */}
      {onLeave && !demo && <LeaveButton onLeave={onLeave} />}
      <motion.div
        // La visite éclaire ce panneau ENTIER. L'ancre était sur le titre :
        // la découpe ne montrait que deux lignes, et le rituel qu'on venait
        // d'expliquer — l'accroche, l'anneau qui se remplit, le bouton —
        // restait dans le noir avec le reste de l'écran.
        data-tour="entry"
        className="max-w-[520px] px-8.5 text-center"
        initial={reduce ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.33, 1, 0.68, 1] }}
      >
        <div className="mb-3 text-[13px] font-bold tracking-[1px] text-brand-ink uppercase">
          {t("entry.label")}
        </div>
        <h2 className="m-0 mb-2.5 font-serif text-2xl font-bold text-foreground">{title}</h2>
        <p className="leading-relaxed text-text-soft">{t("entry.text")}</p>
        <div className="mt-3">
          <WhyButton whyKey="entry" />
        </div>

        {hookText && (
          <motion.div
            className="mx-auto my-4 flex max-w-[460px] items-start gap-2.5 rounded-md bg-brand-soft px-4 py-3 text-left text-sm leading-relaxed text-accent-foreground"
            initial={reduce ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.15, ease: [0.33, 1, 0.68, 1] }}
          >
            <Lightbulb className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>{hookText}</span>
          </motion.div>
        )}

        {/* Le compte à rebours n'était qu'un nombre dans un rond. L'anneau rend la
            durée visible d'un coup d'œil, et la respiration donne le tempo. */}
        <div className="relative mx-auto my-5.5 grid size-28 place-items-center">
          <motion.span
            aria-hidden
            className="absolute inset-0 rounded-full bg-brand-soft"
            animate={reduce ? undefined : { scale: [1, 1.08, 1], opacity: [0.5, 0.85, 0.5] }}
            transition={{ duration: 5.5, repeat: Infinity, ease: "easeInOut" }}
          />
          <svg className="absolute inset-0 size-28 -rotate-90" viewBox="0 0 100 100" aria-hidden>
            <circle
              cx="50"
              cy="50"
              r={RING_RADIUS}
              fill="none"
              stroke="var(--border)"
              strokeWidth="3"
            />
            <circle
              cx="50"
              cy="50"
              r={RING_RADIUS}
              fill="none"
              stroke="var(--accent)"
              strokeWidth="3"
              strokeLinecap="round"
              strokeDasharray={RING_CIRCUMFERENCE}
              strokeDashoffset={RING_CIRCUMFERENCE * (1 - elapsed / totalSeconds)}
              // Une seconde pile : l'anneau glisse au lieu de sauter par crans.
              style={{ transition: "stroke-dashoffset 1s linear" }}
            />
          </svg>
          <span
            role="timer"
            aria-live="off"
            className="relative text-3xl font-bold text-accent-foreground tabular-nums"
          >
            {left}
          </span>
        </div>

        <div className="flex flex-wrap justify-center gap-2.5">
          <Button size="lg" onClick={() => (demo ? onStart() : setPhase("review"))} disabled={!canSkip}>
            {canSkip ? t("entry.continue") : t("entry.skip_in", { n: left - SKIP_AT })}
          </Button>
        </div>
      </motion.div>
    </SasOverlay>
  );
}

/**
 * « ← Bibliothèque », en HAUT À GAUCHE du sas — là où l'on attend un retour
 * (barre du lecteur, navigateur), et hors du panneau central, qui ne parle
 * que du rituel. Posé sous le bouton « Continuer », il se lisait comme une
 * seconde issue du sas ; ici c'est une sortie, à sa place de sortie.
 */
function LeaveButton({ onLeave }: { onLeave: () => void }) {
  const t = useT();
  return (
    <div className="absolute top-4 left-4 z-10">
      <Button variant="ghost" size="sm" onClick={onLeave} title={t("entry.back_library_hint")}>
        {t("entry.back_library")}
      </Button>
    </div>
  );
}
