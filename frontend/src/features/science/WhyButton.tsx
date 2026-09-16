// WhyButton — « Pourquoi ce moment ? » : la justification scientifique d'un SAS.
//
// La modale était écrite à la main : un voile en `position: fixed`, un
// `role="dialog"` posé à la main, un écouteur `keydown` pour Échap, et c'est
// tout. Ce qui manquait — et qu'aucun de ces bouts ne fournit — c'est le PIÈGE À
// FOCUS : la tabulation sortait du dialogue et continuait dans la page en
// dessous, invisible. Radix (via shadcn) le fournit, avec le portail, le
// verrouillage du défilement et la restauration du focus à la fermeture.

import { HelpCircle } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import { useLangStore, useT } from "../../i18n";
import { whyContent, type WhyKey } from "./metacogContent";

export function WhyButton({ whyKey }: { whyKey: WhyKey }) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const content = whyContent[lang][whyKey];

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="secondary" size="sm" className="font-extrabold text-accent-foreground">
          <HelpCircle className="size-4" aria-hidden />
          {t("sas.why")}
        </Button>
      </DialogTrigger>

      {/* Le bouton vit DANS un SAS (`SasOverlay`, `z-100`) : au `z-50` par
          défaut de la Dialog, le panneau s'ouvrait DERRIÈRE le sas de sortie
          — invisible, mais avec le focus et le verrou de défilement. Il passe
          au-dessus des SAS, sous les bulles de la visite (`z-120`/`z-130`). */}
      <DialogContent
        className="z-[110] max-h-[88vh] overflow-y-auto sm:max-w-[620px]"
        overlayClassName="z-[110]"
      >
        <DialogHeader>
          <DialogTitle className="pr-8 font-serif text-h2">
            {content.title}
          </DialogTitle>
        </DialogHeader>

        <WhyBlock label={t("why.principle")} text={content.principle} />
        <WhyBlock label={t("why.conclusion")} text={content.conclusion} />
        <WhyBlock label={t("why.in_app")} text={content.inApp} />

        <div className="mt-4">
          <div className="text-xs font-extrabold tracking-wide text-muted-foreground uppercase">
            {t("why.sources")}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {content.sources.map((source) => (
              <Badge key={source} variant="secondary" className="font-bold">
                {source}
              </Badge>
            ))}
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <Link
            to="/stats/science"
            className="rounded-sm font-extrabold text-accent-foreground underline underline-offset-2
                       transition-colors duration-fast ease-brand hover:text-brand-ink
                       focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            {t("why.full_page")}
          </Link>
          <DialogClose asChild>
            <Button>{t("common.close")}</Button>
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function WhyBlock({ label, text }: { label: string; text: string }) {
  return (
    <section className="mt-3.5">
      <div className="text-xs font-extrabold tracking-wide text-accent-foreground uppercase">
        {label}
      </div>
      <p className="mt-1.5 mb-0 leading-relaxed text-text-soft">{text}</p>
    </section>
  );
}
