import { motion, useReducedMotion } from "motion/react";

import { useT } from "../i18n";
import { MathText } from "./MathText";

/** Ce qu'une carte montre : commun aux flashcards, au warm-up et aux cartes du feuilleton. */
export interface FlipCardFaces {
  front: string;
  back: string;
  pronunciation?: string | null;
  pronunciation_side?: "front" | "back" | null;
}

// La carte retournable, seule source de son allure : couleurs des deux faces et
// bascule. Elle existait en trois copies (flashcards, warm-up, séance de langue)
// qui avaient divergé — deux ne basculaient pas, une n'avait pas les couleurs.
//
// La carte basculait en changeant de couleur, sans mouvement : rien ne disait
// qu'on venait de la RETOURNER. D'où la rotation.
export function FlipCard({
  card,
  flipped,
  onClick,
  disabled = false,
  minHeight = "min(68vh, 560px)",
  dataTour,
}: {
  card: FlipCardFaces;
  flipped: boolean;
  onClick: () => void;
  /** Verso affiché et clic sans effet (le verdict se donne ailleurs). */
  disabled?: boolean;
  minHeight?: string;
  dataTour?: string;
}) {
  const t = useT();
  const reduce = useReducedMotion();
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-tour={dataTour}
      aria-label={flipped ? t("flash.tap_next") : t("flash.tap_reveal")}
      className="w-full cursor-pointer rounded-lg border-none bg-transparent p-0 disabled:cursor-default
                 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
      style={{ perspective: 1600 }}
    >
      <motion.div
        className="relative grid w-full place-items-center rounded-lg border border-border p-12
                   text-center font-serif text-h2 shadow-e2"
        animate={{
          rotateX: reduce ? 0 : flipped ? 180 : 0,
          backgroundColor: flipped ? "var(--warning-soft)" : "var(--surface)",
        }}
        transition={{ duration: 0.45, ease: [0.33, 1, 0.68, 1] }}
        style={{ minHeight, transformStyle: "preserve-3d" }}
      >
        {/* Le contenu se contre-tourne, sinon il s'afficherait en miroir. */}
        <div style={{ transform: reduce ? undefined : flipped ? "rotateX(180deg)" : undefined }}>
          <div className="mb-4 text-xs font-bold tracking-wide text-muted-foreground">
            {flipped ? t("flash.a") : t("flash.q")}
          </div>
          <MathText text={flipped ? card.back : card.front} dir="auto" />
          {/* Carte de langue : la prononciation accompagne la face écrite dans la langue apprise. */}
          {card.pronunciation && card.pronunciation_side === (flipped ? "back" : "front") && (
            <div title={t("lang.phonetic")} className="mt-2.5 text-lg italic text-muted-foreground">
              [{card.pronunciation}]
            </div>
          )}
        </div>
      </motion.div>
    </button>
  );
}
