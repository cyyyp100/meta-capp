// QuestionStem.tsx — L'énoncé, rendu de la même façon en lecture et en quiz.
//
// Le quiz passait déjà l'énoncé dans KaTeX, la carte Q&R du lecteur affichait le
// LaTeX brut ($u_n \sim n$ à l'écran). Un seul composant règle les deux, et
// porte la consigne propre au type quand elle éclaire ce qu'on attend.

import { EyeOff } from "lucide-react";

import { cn } from "@/lib/utils";

import { useT } from "../../i18n";
import { renderMathToHtml } from "../reader/renderMath";
import { questionTypeMeta, toQuestionType } from "./registry";

export function QuestionStem({
  question,
  type,
  /** Passage caché dans la page (rappel libre) : on le signale sous l'énoncé. */
  masked = false,
  /** Consigne du type sous l'énoncé. Utile en carte pleine, superflu en liste. */
  showHint = true,
  className,
}: {
  question: string;
  type: string | undefined;
  masked?: boolean;
  showHint?: boolean;
  className?: string;
}) {
  const t = useT();
  const key = toQuestionType(type);
  const meta = questionTypeMeta(key);
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {/* L'énoncé d'un repérage d'erreur CONTIENT l'affirmation fausse : on
          l'encadre pour qu'on la lise comme une pièce à examiner, pas comme
          une vérité du cours. */}
      <div
        className={cn(
          "text-sm leading-relaxed font-semibold text-foreground",
          key === "error_detection" &&
            "rounded-sm border border-warning/40 bg-warning-soft/60 p-2.5 font-normal",
        )}
        dangerouslySetInnerHTML={{ __html: renderMathToHtml(question || "…") }}
      />
      {masked && (
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <EyeOff className="size-3.5 shrink-0" aria-hidden />
          {t("qa.recall.masked")}
        </span>
      )}
      {showHint && <p className="m-0 text-xs text-muted-foreground">{t(meta.hintKey)}</p>}
    </div>
  );
}
