// TourHost.tsx — Monte la bulle courante, où qu'on soit dans l'application.
//
// Monté une fois, en haut de l'arbre : les étapes traversent les routes (la
// bulle d'import est sur l'accueil, celle de Gemma dans le lecteur), et un hôte
// par écran les ferait disparaître à chaque navigation.
import { Coachmark } from "./Coachmark";
import { useTour } from "./useTour";

export function TourHost() {
  const active = useTour((s) => s.active);
  if (!active) return null;
  return <Coachmark step={active} />;
}

/** Signale qu'un contexte d'étape vient d'apparaître. À appeler depuis l'écran
 *  concerné — c'est lui qui sait quand son moment arrive. */
export { useTour };
