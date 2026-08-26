// QuestionTypeBadge.tsx — Ce que l'apprenant doit faire, en un coup d'œil.
//
// Le type de question voyageait déjà du LLM jusqu'à l'UI, sans jamais être
// affiché : « remets dans l'ordre » et « explique à un débutant » avaient la
// même tête qu'un QCM. Le badge annonce l'effort attendu ; il reste discret
// (une pastille, pas un titre) pour ne pas transformer la carte en tableau de bord.

import { cn } from "@/lib/utils";

import { useT } from "../../i18n";
import { questionTypeMeta, TONE_CLASS, type QuestionType } from "./registry";

export function QuestionTypeBadge({
  type,
  className,
}: {
  type: QuestionType | string | undefined;
  className?: string;
}) {
  const t = useT();
  const meta = questionTypeMeta(type);
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5",
        "text-[11px] font-semibold tracking-[0.02em]",
        TONE_CLASS[meta.tone],
        className,
      )}
    >
      <Icon className="size-3 shrink-0" aria-hidden />
      {t(meta.labelKey)}
    </span>
  );
}
