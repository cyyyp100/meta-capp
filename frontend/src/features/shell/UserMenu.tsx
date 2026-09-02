// UserMenu.tsx — Le bloc profil du pied de la barre latérale.
//
// Le pied contenait deux contrôles nus : un segmenté FR/EN et un bouton de
// thème. Deux réglages exposés à plat, et aucune trace de la personne qui
// utilise le logiciel — alors que tout le produit consiste à l'observer.
//
// Ce bloc dit d'abord QUI est là et depuis combien de jours ; les réglages
// passent derrière le menu, où on va les chercher.
import { HelpCircle, Info, Moon, Settings, Sun } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { StudyStreak } from "@/api/client";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useThemeStore } from "@/theme/useTheme";

import { useT } from "../../i18n";

/** Initiales affichées dans la pastille — deux au plus, sinon ça n'est plus lisible. */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function UserMenu({ name, streak }: { name: string; streak?: StudyStreak }) {
  const t = useT();
  const navigate = useNavigate();
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);

  const days = streak?.streak ?? 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t("user.menu")}
        className="flex w-full items-center gap-2.5 rounded-sm px-2 py-2 text-left outline-none
                   transition-colors duration-fast ease-brand
                   hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        <span
          aria-hidden
          className="grid size-8 shrink-0 place-items-center rounded-full bg-brand
                     text-xs font-bold text-primary-foreground"
        >
          {initials(name)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{name}</span>
          {/* La série est une INFORMATION, pas une menace : « X jours », et
              quand il n'y en a pas, une invitation — jamais un compte à rebours
              ni un rappel de ce qu'on est en train de perdre. */}
          <span className="block truncate text-[11px] text-muted-foreground">
            {days > 0 ? t("settings.days", { n: days }) : t("user.no_streak")}
          </span>
        </span>
      </DropdownMenuTrigger>

      <DropdownMenuContent side="top" align="start" className="w-56">
        <DropdownMenuItem onSelect={() => toggleTheme()}>
          {theme === "light" ? <Moon aria-hidden /> : <Sun aria-hidden />}
          {theme === "light" ? t("common.dark") : t("common.light")}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate("/settings")}>
          <Settings aria-hidden />
          {t("user.settings")}
          {/* Le raccourci est déclaré dans `useAppShortcuts` — le menu natif ne
              peut pas en porter (pywebview 6.2.1). */}
          <DropdownMenuShortcut>⌘,</DropdownMenuShortcut>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate("/settings/help")}>
          <HelpCircle aria-hidden />
          {t("user.help")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate("/settings/about")}>
          <Info aria-hidden />
          {t("user.about")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
