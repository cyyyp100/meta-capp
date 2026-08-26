// OrderingAnswer.tsx — Remise en ordre : on attrape une étape et on la déplace.
//
// `Reorder` vient de motion/react, déjà utilisé ailleurs dans l'app : aucune
// dépendance ajoutée. Le glisser-déposer part de la poignée seule
// (`dragListener={false}` + `dragControls`), sinon un appui sur les flèches
// démarrerait un drag au lieu de cliquer.
//
// Les flèches ↑/↓ ne sont pas une redondance décorative : un glisser-déposer
// seul est inutilisable au clavier, et la position atteinte est annoncée dans
// une région `aria-live` — sans quoi le déplacement resterait muet.

import { Check, ChevronDown, ChevronUp, GripVertical, X } from "lucide-react";
import { Reorder, useDragControls, useReducedMotion } from "motion/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useT } from "../../i18n";
import { renderMathToHtml } from "../reader/renderMath";

interface Step {
  id: number;
  text: string;
}

export function OrderingAnswer({
  items,
  busy = false,
  /** Ordre attendu. Fourni après validation : chaque ligne affiche son verdict. */
  correctOrder,
  onSubmit,
}: {
  items: string[];
  busy?: boolean;
  correctOrder?: string[] | null;
  onSubmit: (ordered: string[]) => void;
}) {
  const t = useT();
  const reduceMotion = useReducedMotion();
  const [steps, setSteps] = useState<Step[]>(() => items.map((text, id) => ({ id, text })));
  const [announcement, setAnnouncement] = useState("");
  const settled = Boolean(correctOrder && correctOrder.length);

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    setSteps(next);
    setAnnouncement(
      t("qa.ordering.moved", { step: next[target].text, n: target + 1, total: next.length }),
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="m-0 text-xs text-muted-foreground">{t("qa.ordering.help")}</p>

      <Reorder.Group
        axis="y"
        as="ol"
        values={steps}
        onReorder={setSteps}
        className="m-0 flex list-none flex-col gap-1.5 p-0"
      >
        {steps.map((step, index) => (
          <OrderingRow
            key={step.id}
            step={step}
            index={index}
            total={steps.length}
            locked={settled || busy}
            reduceMotion={Boolean(reduceMotion)}
            expectedIndex={correctOrder ? correctOrder.indexOf(step.text) : -1}
            settled={settled}
            onMove={move}
          />
        ))}
      </Reorder.Group>

      {/* Le déplacement au clavier doit s'entendre : sans cette région, la
          flèche ↑ ne produit aucun retour pour un lecteur d'écran. */}
      <span className="sr-only" role="status" aria-live="polite">
        {announcement}
      </span>

      {!settled && (
        <Button size="sm" className="w-fit" pending={busy} onClick={() => onSubmit(steps.map((s) => s.text))}>
          {t("qa.ordering.validate")}
        </Button>
      )}
    </div>
  );
}

function OrderingRow({
  step,
  index,
  total,
  locked,
  reduceMotion,
  expectedIndex,
  settled,
  onMove,
}: {
  step: Step;
  index: number;
  total: number;
  locked: boolean;
  reduceMotion: boolean;
  expectedIndex: number;
  settled: boolean;
  onMove: (index: number, delta: number) => void;
}) {
  const t = useT();
  const controls = useDragControls();
  const correct = settled && expectedIndex === index;
  const wrong = settled && expectedIndex !== index;

  return (
    <Reorder.Item
      value={step}
      dragListener={false}
      dragControls={controls}
      layout={reduceMotion ? undefined : "position"}
      whileDrag={{ scale: reduceMotion ? 1 : 1.02, boxShadow: "var(--shadow-md)", zIndex: 2 }}
      transition={reduceMotion ? { duration: 0 } : { type: "spring", stiffness: 520, damping: 38 }}
      className={cn(
        "flex touch-none items-center gap-2 rounded-sm border bg-surface-soft px-2 py-1.5",
        "transition-colors duration-fast ease-brand",
        !settled && "hover:border-border-strong",
        correct && "border-success bg-success-soft",
        wrong && "border-danger bg-danger-soft",
        !correct && !wrong && "border-border",
      )}
    >
      <span
        className={cn(
          "grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-bold",
          settled ? "bg-surface text-muted-foreground" : "bg-brand-soft text-accent-foreground",
        )}
        aria-hidden
      >
        {index + 1}
      </span>

      <span
        className="min-w-0 flex-1 text-xs leading-snug text-foreground"
        dangerouslySetInnerHTML={{ __html: renderMathToHtml(step.text) }}
      />

      {settled ? (
        correct ? (
          <Check className="size-4 shrink-0 text-success" aria-label={t("verdict.correct")} />
        ) : (
          <span className="flex shrink-0 items-center gap-1 text-[11px] font-semibold text-danger">
            <X className="size-4" aria-hidden />
            {t("qa.ordering.expected_at", { n: expectedIndex + 1 })}
          </span>
        )
      ) : (
        <span className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            disabled={locked || index === 0}
            onClick={() => onMove(index, -1)}
            aria-label={t("qa.ordering.move_up", { step: step.text })}
            className={arrowClass}
          >
            <ChevronUp className="size-3.5" aria-hidden />
          </button>
          <button
            type="button"
            disabled={locked || index === total - 1}
            onClick={() => onMove(index, 1)}
            aria-label={t("qa.ordering.move_down", { step: step.text })}
            className={arrowClass}
          >
            <ChevronDown className="size-3.5" aria-hidden />
          </button>
          {/* La poignée est le seul point de départ du drag : le reste de la
              ligne reste sélectionnable et les flèches restent cliquables. */}
          <span
            role="presentation"
            onPointerDown={(e) => !locked && controls.start(e)}
            className={cn(
              "ml-0.5 grid size-6 cursor-grab place-items-center rounded-[4px] text-muted-light",
              "transition-colors duration-fast ease-brand hover:text-muted-foreground active:cursor-grabbing",
              locked && "pointer-events-none opacity-40",
            )}
          >
            <GripVertical className="size-3.5" aria-hidden />
          </span>
        </span>
      )}
    </Reorder.Item>
  );
}

const arrowClass = cn(
  "grid size-6 place-items-center rounded-[4px] border-none bg-transparent text-muted-foreground",
  "transition-colors duration-fast ease-brand",
  "enabled:cursor-pointer enabled:hover:bg-accent enabled:hover:text-accent-foreground",
  "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
  "disabled:opacity-30",
);
