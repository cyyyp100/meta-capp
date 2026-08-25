// SasOverlay — Le voile plein écran des SAS (entrée, sortie, repos, warm-up).
//
// Il était réimplémenté à l'identique dans cinq fichiers, et les copies avaient
// déjà divergé : trois valeurs de z-index (80, 100, 110) et deux fonds
// (`var(--bg)` opaque contre `rgba(0,0,0,0.4)` translucide), sans qu'aucune
// règle ne dise laquelle s'applique quand. Une seule définition ici, avec deux
// variantes explicites.
//
// Ce ne sont PAS des dialogues Radix : un SAS n'est pas une fenêtre qu'on ferme,
// c'est une étape imposée du parcours. Pas de bouton de fermeture, pas d'Échap —
// c'est voulu, et c'est pour ça qu'ils gardent leur propre coque.

import { motion, useReducedMotion } from "motion/react";

import { cn } from "@/lib/utils";

export type SasVariant =
  /** Prend toute la place : le SAS REMPLACE l'écran (entrée, warm-up, repos). */
  | "solid"
  /** Assombrit ce qu'il y a derrière : le SAS se pose SUR l'écran (bilan de fin). */
  | "scrim";

export function SasOverlay({
  children,
  variant = "solid",
  /** Ancre le voile au conteneur positionné le plus proche plutôt qu'à la fenêtre. */
  contained = false,
  className,
}: {
  children?: React.ReactNode;
  variant?: SasVariant;
  contained?: boolean;
  className?: string;
}) {
  const reduce = useReducedMotion();

  return (
    <motion.div
      className={cn(
        "inset-0 z-100 grid place-items-center overflow-hidden",
        contained ? "absolute" : "fixed",
        variant === "solid" ? "bg-background" : "bg-black/45 p-4 backdrop-blur-[2px]",
        className,
      )}
      initial={reduce ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={reduce ? undefined : { opacity: 0 }}
      transition={{ duration: 0.28, ease: [0.33, 1, 0.68, 1] }}
    >
      {/* Halo très lent : le SAS est un temps de respiration, l'écran ne doit pas
          être une page morte. Absent de la variante translucide, où le contenu
          derrière fournit déjà la texture. */}
      {variant === "solid" && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(50%_50%_at_50%_45%,var(--accent-soft),transparent_70%)] opacity-60"
        />
      )}
      <div className="relative max-h-full w-full overflow-y-auto">
        <div className="grid min-h-full place-items-center">{children}</div>
      </div>
    </motion.div>
  );
}

/** Carte centrale des SAS de bilan (variante `scrim`). */
export function SasCard({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={cn(
        "w-[min(560px,92vw)] rounded-lg border border-border bg-surface p-8.5 shadow-e3",
        className,
      )}
      initial={reduce ? false : { opacity: 0, scale: 0.98, y: 8 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.33, 1, 0.68, 1] }}
    >
      {children}
    </motion.div>
  );
}
