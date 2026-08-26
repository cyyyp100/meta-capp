// AnswerInput.tsx — Le widget de réponse, choisi par le type de question.
//
// Point de partage entre la carte Q&R du lecteur et la carte du quiz : les deux
// écrans réimplémentaient leurs propres boutons de choix et leur propre champ
// texte, avec des états de survol et des icônes de verdict divergents. Le quiz
// injecte sa notation « je savais / révéler » via `textFallback` ; tout le reste
// est commun.

import { Check, X } from "lucide-react";
import { type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import { renderMathToHtml } from "../reader/renderMath";
import { OrderingAnswer } from "./OrderingAnswer";
import { answerWidget, questionTypeMeta, toQuestionType } from "./registry";

/** Sérialisation d'une remise en ordre : ce qui part au serveur et à l'évaluation. */
export function serializeOrder(steps: string[]): string {
  return steps.map((step, i) => `${i + 1}. ${step}`).join("\n");
}

export function AnswerInput({
  type,
  choices,
  seed,
  draft,
  setDraft,
  busy = false,
  picked = null,
  expectedChoice,
  correctOrder,
  textFallback,
  onSubmit,
}: {
  type: string | undefined;
  choices: string[] | null | undefined;
  /** Graine du mélange des étapes (id de question) : stable entre deux rendus. */
  seed: number | string;
  draft?: string;
  setDraft?: (value: string) => void;
  busy?: boolean;
  /** Choix retenu (quiz) : déclenche l'affichage des verdicts. */
  picked?: string | null;
  /** Bonne réponse d'un QCM (quiz), pour colorer les choix après le clic. */
  expectedChoice?: string;
  /** Ordre attendu (quiz), pour marquer chaque étape après validation. */
  correctOrder?: string[] | null;
  /** Remplace la zone de texte (quiz : auto-évaluation au lieu d'une saisie). */
  textFallback?: ReactNode;
  onSubmit: (answer: string) => void;
}) {
  const t = useT();
  const key = toQuestionType(type);
  const widget = answerWidget(key, choices);
  const items = choices ?? [];

  if (widget === "ordering") {
    return (
      <OrderingAnswer
        // Les étapes sont stockées DANS L'ORDRE CORRECT : les afficher telles
        // quelles donnerait la réponse. Le mélange est déterministe (semé par
        // l'id de la question), donc identique à chaque rendu — pas de mémo.
        items={shuffleSteps(items, String(seed))}
        busy={busy}
        correctOrder={correctOrder}
        onSubmit={(ordered) => onSubmit(serializeOrder(ordered))}
      />
    );
  }

  if (widget === "choices") {
    return (
      <ChoiceList
        choices={items}
        picked={picked}
        expected={expectedChoice}
        busy={busy}
        onPick={onSubmit}
      />
    );
  }

  if (textFallback) return <>{textFallback}</>;

  return (
    <div className="flex items-end gap-1.5">
      <AutoGrowTextarea
        value={draft ?? ""}
        onChange={(e) => setDraft?.(e.target.value)}
        onSubmit={() => onSubmit(draft ?? "")}
        placeholder={t(questionTypeMeta(key).hintKey)}
        aria-label={t("gemma.your_answer")}
        style={textareaStyle}
      />
      <Button onClick={() => onSubmit(draft ?? "")} pending={busy} className="shrink-0">
        OK
      </Button>
    </div>
  );
}

/**
 * Liste de choix — QCM et ordres de grandeur. Le verdict est doublé d'une icône :
 * la couleur seule est illisible pour un daltonien.
 */
export function ChoiceList({
  choices,
  picked = null,
  expected,
  busy = false,
  onPick,
}: {
  choices: string[];
  picked?: string | null;
  expected?: string;
  busy?: boolean;
  onPick: (choice: string) => void;
}) {
  const t = useT();
  const settled = picked !== null && picked !== undefined;
  return (
    <div className="grid gap-1.5">
      {choices.map((choice) => {
        const isCorrect = settled && expected !== undefined && same(choice, expected);
        const isPicked = picked === choice;
        return (
          <button
            key={choice}
            type="button"
            disabled={settled || busy}
            onClick={() => onPick(choice)}
            className={cn(
              "flex items-center justify-between gap-3 rounded-sm border px-3.5 py-2.5 text-left text-sm",
              "transition-[background-color,border-color,transform] duration-fast ease-brand",
              "enabled:cursor-pointer enabled:hover:border-border-strong enabled:active:scale-[0.995]",
              "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
              "disabled:cursor-default",
              isCorrect
                ? "border-success bg-success-soft text-foreground"
                : isPicked
                  ? "border-danger bg-danger-soft text-foreground"
                  : "border-border bg-surface-soft text-foreground",
            )}
          >
            <span dangerouslySetInnerHTML={{ __html: renderMathToHtml(choice) }} />
            {isCorrect && <Check className="size-4 shrink-0 text-success" aria-label={t("verdict.correct")} />}
            {isPicked && !isCorrect && (
              <X className="size-4 shrink-0 text-danger" aria-label={t("verdict.incorrect")} />
            )}
          </button>
        );
      })}
    </div>
  );
}

function same(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/**
 * Mélange déterministe (générateur congruentiel semé par l'id de la question) :
 * un `Math.random()` reclasserait les étapes à chaque rendu, sous les doigts de
 * l'utilisateur. Garantit aussi de ne pas rendre l'ordre correct tel quel.
 */
export function shuffleSteps(items: string[], seed: string): string[] {
  if (items.length < 2) return items;
  let state = 0;
  for (const char of seed) state = (state * 31 + char.charCodeAt(0)) >>> 0;
  const next = () => (state = (state * 1664525 + 1013904223) >>> 0) / 4294967296;

  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  if (out.every((value, i) => value === items[i])) out.push(out.shift()!);
  return out;
}

const textareaStyle = {
  flex: 1,
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  background: "var(--bg)",
  color: "var(--text)",
  fontSize: 13,
} as const;
