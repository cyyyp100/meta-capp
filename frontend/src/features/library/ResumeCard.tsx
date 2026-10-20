// ResumeCard.tsx — La carte « Reprendre », en tête de bibliothèque.
//
// Le rituel de retour tient à une chose : qu'il n'y ait rien à décider en
// arrivant. La bibliothèque affichait une grille de cartes toutes égales — il
// fallait se souvenir de ce qu'on lisait, le retrouver, viser la bonne page.
// Ici : un document, une page, un clic.
//
// Le document et la durée viennent du serveur (services/library.resume) : la
// dernière séance qui a LU quelque chose, et le temps qu'il reste au document à
// l'allure mesurée de cette personne. Une durée de séance générique (la médiane
// de toutes les séances, quiz compris) promettait la même chose pour un
// chapitre et pour un manuel ; une allure qui n'est pas encore mesurée est
// annoncée comme une estimation.
import { useQuery } from "@tanstack/react-query";
import { BookOpen, FileQuestionMark, Flame } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import type { DocumentSummary, ReadingRemaining } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import { useT } from "../../i18n";
import { remainingParts } from "./remaining";

export function ResumeCard({
  onRelink,
  relinkingId = null,
}: {
  /** Le document à reprendre est introuvable : son bouton devient « Localiser
   *  le fichier… » (le dialogue est celui de `useRelinkDocument`, dans Home). */
  onRelink: (doc: DocumentSummary) => void;
  /** Document dont la re-liaison est en cours (bouton en attente). */
  relinkingId?: number | null;
}) {
  const t = useT();
  const navigate = useNavigate();

  // Sous `["library", …]` : `refreshLibrary()` (Home) l'invalide avec le reste.
  const { data: resume } = useQuery({ queryKey: ["library", "resume"], queryFn: api.libraryResume });
  const { data: streak } = useQuery({ queryKey: ["streak"], queryFn: api.streak });

  const doc = resume?.document;
  if (!doc) return null;

  return (
    <section
      className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-4 rounded-lg border border-border
                 bg-surface p-5 shadow-e1"
    >
      <div className="min-w-56 flex-1">
        <div className="flex items-center gap-2 text-[11px] font-bold tracking-wide text-brand-ink uppercase">
          <BookOpen className="size-3.5" aria-hidden />
          {t("resume.title")}
        </div>
        <h2 className="mt-1.5 mb-0 truncate font-serif text-h3 font-bold">{doc.title}</h2>
        <p className="mt-1 mb-0 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
          {/* Le marque-page, posé par l'élève, prime : le lecteur s'y ouvre, et le
              temps restant en part (services/reading_pace.remaining). */}
          <span>
            {doc.bookmark_page
              ? t("resume.bookmark", { page: doc.bookmark_page })
              : t("resume.page", { page: Math.max(1, doc.last_page || 1) })}
          </span>
          {resume.remaining && (
            <>
              <span aria-hidden>·</span>
              <Remaining remaining={resume.remaining} />
            </>
          )}
        </p>
        {doc.file_missing && (
          <p className="mt-1.5 mb-0 flex items-center gap-1.5 text-[13px] text-warning">
            <FileQuestionMark className="size-3.5 shrink-0" aria-hidden />
            {t("resume.file_missing")}
          </p>
        )}
      </div>

      {/* La série est affichée là où elle a du sens — à côté du geste qui la
          fait avancer — et sans compte à rebours : « X jours », et le rappel
          qu'un jour manqué ne la casse pas. */}
      {(streak?.streak ?? 0) > 0 && (
        <div className="text-right">
          <div className="flex items-center justify-end gap-1.5 text-h3 font-bold text-brand-ink tabular-nums">
            <Flame className="size-4.5" aria-hidden />
            {streak!.streak}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {t("streak.record", { n: streak!.longest_streak })}
          </div>
        </div>
      )}

      {/* Reprendre un fichier introuvable mènerait à l'écran qui demande de le
          localiser : autant proposer ce geste-là directement. */}
      {doc.file_missing ? (
        <Button size="lg" pending={relinkingId === doc.id} onClick={() => onRelink(doc)}>
          {t("library.locate_file")}
        </Button>
      ) : (
        <Button size="lg" onClick={() => navigate(`/reader/${doc.id}`)}>
          {t("resume.action")}
        </Button>
      )}
    </section>
  );
}

/** « ≈ 2 h 10 pour finir », l'allure en infobulle, et « estimation » quand
 *  rien n'est encore mesuré. */
function Remaining({ remaining }: { remaining: ReadingRemaining }) {
  const t = useT();
  const parts = remainingParts(remaining.minutes);
  const label =
    parts.kind === "min"
      ? t("resume.remaining_min", { n: parts.min })
      : parts.kind === "h"
        ? t("resume.remaining_h", { h: parts.h })
        : t("resume.remaining_h_min", { h: parts.h, min: parts.min });
  const pace = Math.round(remaining.seconds_per_page);
  const hint = remaining.measured
    ? t("resume.remaining_measured_hint", { s: pace, n: remaining.samples })
    : t("resume.remaining_default_hint", { s: pace });
  return (
    <span className="inline-flex items-center gap-2">
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0} className="cursor-help rounded-sm underline decoration-dotted underline-offset-2">
            {label}
          </span>
        </TooltipTrigger>
        <TooltipContent>{hint}</TooltipContent>
      </Tooltip>
      {!remaining.measured && <Badge variant="outline">{t("resume.remaining_estimate")}</Badge>}
    </span>
  );
}
