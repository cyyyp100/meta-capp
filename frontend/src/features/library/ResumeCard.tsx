// ResumeCard.tsx — La carte « Reprendre », en tête de bibliothèque.
//
// Le rituel de retour tient à une chose : qu'il n'y ait rien à décider en
// arrivant. La bibliothèque affichait une grille de cartes toutes égales — il
// fallait se souvenir de ce qu'on lisait, le retrouver, viser la bonne page.
// Ici : un document, une page, un clic.
//
// La durée annoncée n'est pas un chiffre rond inventé : c'est la MÉDIANE des
// sessions déjà terminées par cette personne. Promettre « 20 min » à quelqu'un
// qui lit par tranches de 8 est la meilleure façon de ne pas être cru.
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Flame, Layers } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import type { DocumentSummary } from "@/api/types";
import { Button } from "@/components/ui/button";

import { useT } from "../../i18n";

/** Repli quand personne n'a encore terminé de session : une durée de séance
 *  plausible, annoncée comme une estimation et non comme une mesure. */
const DEFAULT_MINUTES = 20;

export function ResumeCard({ documents }: { documents: DocumentSummary[] }) {
  const t = useT();
  const navigate = useNavigate();

  // `last_opened` trie déjà le catalogue côté serveur : le premier document
  // ouvert au moins une fois EST celui qu'on était en train de lire.
  const doc = documents.find((d) => (d.last_page ?? 0) > 0) ?? documents[0];

  const { data: due } = useQuery({
    queryKey: ["flashcards", "due", doc?.id],
    queryFn: () => api.dueFlashcards(doc!.id),
    enabled: Boolean(doc),
  });
  const { data: streak } = useQuery({ queryKey: ["streak"], queryFn: api.streak });
  const { data: history } = useQuery({
    queryKey: ["progress", "sessions"],
    queryFn: () => api.progressSessions(),
  });

  if (!doc) return null;

  const minutes = medianMinutes(history?.sessions ?? []);
  const dueCount = due?.length ?? 0;

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
          <span>{t("resume.page", { page: Math.max(1, doc.last_page || 1) })}</span>
          <span aria-hidden>·</span>
          <span className="flex items-center gap-1.5">
            <Layers className="size-3.5" aria-hidden />
            {dueCount > 0 ? t("resume.cards_due", { n: dueCount }) : t("resume.no_cards")}
          </span>
          <span aria-hidden>·</span>
          <span>{t("resume.estimate", { n: minutes })}</span>
        </p>
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

      <Button size="lg" onClick={() => navigate(`/reader/${doc.id}`)}>
        {t("resume.action")}
      </Button>
    </section>
  );
}

/** Médiane (et non moyenne) des durées : une session oubliée ouverte trois
 *  heures fausserait une moyenne, pas une médiane. */
function medianMinutes(sessions: { completed: boolean; duration_s: number }[]): number {
  const durations = sessions
    .filter((s) => s.completed && s.duration_s > 60)
    .map((s) => s.duration_s)
    .sort((a, b) => a - b);
  if (durations.length === 0) return DEFAULT_MINUTES;
  const middle = durations[Math.floor(durations.length / 2)];
  return Math.max(1, Math.round(middle / 60));
}
