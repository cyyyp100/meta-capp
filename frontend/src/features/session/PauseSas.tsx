// PauseSas — L'écran de pause de la lecture.
//
// L'élève s'arrête (bouton « Pause » du lecteur) ou prend la pause que Gemma
// conseille : le PDF disparaît derrière un voile, et tant qu'il n'a pas repris,
// plus rien n'est mesuré — le serveur fige attention, dwell, interventions et
// horloges (services/pause.py). Seules la durée de la pause et ce qui l'a
// précédée sont enregistrées.
//
// La pause est OUVERTE : c'est l'élève qui revient, pas un décompte qui le
// ramène. Une pause conseillée affiche le temps restant sur la durée proposée,
// puis dit qu'elle est écoulée — sans jamais rendre le lecteur tout seul à
// quelqu'un qui n'est peut-être plus devant l'écran.

import { Coffee } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

import { useT } from "../../i18n";
import { formatDuration } from "./duration";
import { SasCard, SasOverlay } from "./SasOverlay";

/** Une pause en cours. */
export interface ReadingPause {
  /** `manual` : bouton du lecteur ; `suggested` : carte de Gemma acceptée. */
  source: "manual" | "suggested";
  /** Durée conseillée par Gemma, en minutes ; null pour une pause manuelle. */
  plannedMin: number | null;
  /** `Date.now()` au début de la pause. */
  startedAt: number;
}

function elapsedSeconds(startedAt: number): number {
  return Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
}

export function PauseSas({
  pause,
  onResume,
  onEnd,
}: {
  pause: ReadingPause;
  onResume: () => void;
  /** « Terminer la séance » : l'élève ne reviendra pas lire aujourd'hui. */
  onEnd: () => void;
}) {
  const t = useT();
  const [elapsed, setElapsed] = useState(() => elapsedSeconds(pause.startedAt));

  useEffect(() => {
    // Recalculé depuis l'horloge, jamais incrémenté : un onglet mis en
    // arrière-plan ralentit les intervalles, et la pause affichée mentirait.
    const id = window.setInterval(() => setElapsed(elapsedSeconds(pause.startedAt)), 1000);
    return () => window.clearInterval(id);
  }, [pause.startedAt]);

  const plannedS = pause.plannedMin ? pause.plannedMin * 60 : null;
  const left = plannedS === null ? null : Math.max(0, plannedS - elapsed);
  const caption =
    left === null
      ? t("pause.elapsed")
      : left > 0
        ? t("pause.suggested_left", { n: pause.plannedMin ?? 0 })
        : t("pause.suggested_done", { n: pause.plannedMin ?? 0 });

  return (
    <SasOverlay variant="scrim">
      <SasCard className="text-center">
        <div className="mb-3 flex items-center justify-center gap-1.5 text-[11px] font-bold tracking-wide text-accent-foreground uppercase">
          <Coffee className="size-3.5" aria-hidden />
          {pause.source === "suggested" ? t("pause.label_suggested") : t("pause.label")}
        </div>
        <h2 className="m-0 font-serif text-h2 font-bold">{t("pause.title")}</h2>

        <div role="timer" className="mt-5 text-5xl font-bold text-accent-foreground tabular-nums">
          {formatDuration(left === null ? elapsed : left)}
        </div>
        <p className="mt-1.5 mb-0 text-sm text-muted-foreground">{caption}</p>

        <p className="mx-auto mt-5 mb-7 max-w-[420px] text-sm leading-relaxed text-muted-foreground">
          {t("pause.note")}
        </p>

        <div className="flex flex-wrap justify-center gap-2.5">
          {/* Premier geste attendu au retour : le focus y est déjà. */}
          <Button size="lg" onClick={onResume} autoFocus>
            {t("pause.resume")}
          </Button>
          <Button size="lg" variant="ghost" onClick={onEnd}>
            {t("pause.end")}
          </Button>
        </div>
      </SasCard>
    </SasOverlay>
  );
}
