// routes/Settings.tsx — La surface de réglages.
//
// Une ROUTE et non un dialogue : elle doit être adressable depuis la barre de
// menu native (« Fichier ▸ Réglages… », « Aide ▸ Vérifier les mises à jour… »)
// et depuis ⌘,. Un dialogue n'a pas d'adresse, donc rien d'extérieur à React ne
// peut l'ouvrir sur la bonne section.
//
// La section vit dans l'URL (`/settings/updates`) pour la même raison.
import { useQuery } from "@tanstack/react-query";
import {
  Database,
  Download,
  Globe,
  LifeBuoy,
  Palette,
  User,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "@/api/client";
import { DataSection } from "@/components/DataSection";
import { cn } from "@/lib/utils";

import { useT } from "../i18n";
import { AppearanceSection } from "../features/settings/AppearanceSection";
import { HelpSection } from "../features/settings/HelpSection";
import { LanguageSection } from "../features/settings/LanguageSection";
import { ProfileSection } from "../features/settings/ProfileSection";
import { UpdatesSection } from "../features/settings/UpdatesSection";
import { usePreferences } from "../features/shell/usePreferences";

/** Sections adressables. « about » n'a pas d'entrée de rail : c'est une vue de
 *  la section Aide, ouverte directement par le menu natif. */
const SECTIONS = [
  { id: "profile", labelKey: "settings.section.profile", Icon: User },
  { id: "appearance", labelKey: "settings.section.appearance", Icon: Palette },
  { id: "language", labelKey: "settings.section.language", Icon: Globe },
  { id: "data", labelKey: "settings.section.data", Icon: Database },
  { id: "updates", labelKey: "settings.section.updates", Icon: Download },
  { id: "help", labelKey: "settings.section.help", Icon: LifeBuoy },
] as const;

export function Settings() {
  const t = useT();
  const navigate = useNavigate();
  const { section } = useParams<{ section?: string }>();
  const { data, isLoading } = usePreferences();
  const { data: streak } = useQuery({ queryKey: ["streak"], queryFn: api.streak });

  // `/settings/about` est une vue de la section Aide : le rail y montre « Aide »
  // sélectionnée plutôt que rien du tout.
  const current = section === "about" ? "about" : (section ?? "profile");
  const railSelection = current === "about" ? "help" : current;

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-6 p-8.5">
      <header>
        <h1 className="m-0 font-serif text-h1 font-bold">{t("settings.title")}</h1>
        <p className="mt-1 mb-0 text-muted-foreground">{t("settings.subtitle")}</p>
      </header>

      <div className="flex min-h-0 flex-1 gap-7">
        <nav aria-label={t("settings.title")} className="flex w-48 shrink-0 flex-col gap-1">
          {SECTIONS.map(({ id, labelKey, Icon }) => (
            <button
              key={id}
              type="button"
              aria-current={railSelection === id ? "page" : undefined}
              onClick={() => navigate(id === "profile" ? "/settings" : `/settings/${id}`)}
              className={cn(
                "flex items-center gap-2.5 rounded-sm px-3 py-2 text-left text-sm font-semibold",
                "outline-none transition-colors duration-fast ease-brand",
                "focus-visible:ring-[3px] focus-visible:ring-ring/50",
                railSelection === id
                  ? "bg-accent text-accent-foreground"
                  : "text-text-soft hover:bg-accent/60 hover:text-accent-foreground",
              )}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              {t(labelKey)}
            </button>
          ))}
        </nav>

        <div className="min-w-0 flex-1 overflow-y-auto pr-1 pb-8">
          {isLoading || !data ? (
            <p className="text-muted-foreground">{t("common.loading")}</p>
          ) : (
            <>
              {current === "profile" && <ProfileSection payload={data} streak={streak} />}
              {current === "appearance" && <AppearanceSection payload={data} />}
              {current === "language" && <LanguageSection payload={data} />}
              {current === "data" && <DataSection />}
              {current === "updates" && <UpdatesSection payload={data} />}
              {(current === "help" || current === "about") && (
                <HelpSection focusAbout={current === "about"} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
