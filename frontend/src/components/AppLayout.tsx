import {
  BarChart3,
  Globe,
  HelpCircle,
  Home,
  Layers,
  MessageSquare,
  Moon,
  Sun,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Suspense } from "react";
import { NavLink, useLocation, useOutlet } from "react-router-dom";

import { RouteFallback } from "@/components/RouteFallback";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useThemeStore } from "@/theme/useTheme";

import { useLangStore, useT } from "../i18n";

const NAV = [
  { to: "/", labelKey: "nav.home", Icon: Home, end: true },
  { to: "/stats", labelKey: "nav.profile", Icon: BarChart3, end: false },
  { to: "/flashcards", labelKey: "nav.flashcards", Icon: Layers, end: false },
  { to: "/quiz", labelKey: "nav.quiz", Icon: HelpCircle, end: false },
  { to: "/lang", labelKey: "nav.lang", Icon: Globe, end: false },
  { to: "/brainstorming", labelKey: "nav.brainstorming", Icon: MessageSquare, end: false },
];

export function AppLayout() {
  const t = useT();
  const location = useLocation();
  const reduce = useReducedMotion();
  // `useOutlet()` plutôt que `<Outlet />` : il FIGE l'élément de la route
  // courante. Un `<Outlet />` rendu dans l'enveloppe sortante lirait le contexte
  // de routage à jour et afficherait déjà l'écran ENTRANT — le fondu de sortie
  // porterait sur le mauvais contenu.
  const outlet = useOutlet();
  const { lang, setLang } = useLangStore();
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);

  return (
    <div className="flex h-full">
      <aside className="flex w-58 shrink-0 flex-col border-r border-border bg-surface px-3.5 py-5.5">
        <div className="px-2.5 pb-4.5 font-serif text-[22px] font-bold tracking-tight">
          Meta-Capp
        </div>

        <nav className="flex flex-col gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "group relative flex items-center gap-2.5 rounded-sm px-3 py-2.5",
                  "text-sm font-semibold no-underline outline-none",
                  "transition-colors duration-fast ease-brand",
                  "focus-visible:ring-[3px] focus-visible:ring-ring/50",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-text-soft hover:bg-accent/60 hover:text-accent-foreground",
                )
              }
            >
              {({ isActive }) => (
                <>
                  {/* Repère d'onglet actif : une barre verticale sur le bord
                      gauche. Le fond coloré seul ne dit pas « vous êtes ici »
                      aussi vite qu'un marqueur aligné sur le bord du rail. */}
                  <span
                    aria-hidden
                    className={cn(
                      "absolute top-1/2 left-0 h-4.5 w-[3px] -translate-y-1/2 rounded-r-full bg-brand",
                      "transition-opacity duration-fast ease-brand",
                      isActive ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <item.Icon className="size-4.5 shrink-0" aria-hidden />
                  {t(item.labelKey)}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto flex flex-col gap-2">
          {/* Sélecteur de langue en contrôle segmenté : deux boutons dont un seul
              est enfoncé — `aria-pressed` porte l'état, la couleur ne fait que
              le doubler. */}
          <div
            role="group"
            aria-label={t("common.language")}
            className="flex gap-1.5 rounded-sm bg-surface-soft p-1"
          >
            {(["fr", "en"] as const).map((l) => (
              <Button
                key={l}
                size="sm"
                variant={lang === l ? "default" : "ghost"}
                aria-pressed={lang === l}
                onClick={() => setLang(l)}
                className="h-7 flex-1 text-[11px] tracking-wide"
              >
                {l.toUpperCase()}
              </Button>
            ))}
          </div>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="secondary"
                size="sm"
                onClick={toggleTheme}
                className="w-full justify-start gap-2"
              >
                {theme === "light" ? (
                  <Moon className="size-4" aria-hidden />
                ) : (
                  <Sun className="size-4" aria-hidden />
                )}
                {theme === "light" ? t("common.dark") : t("common.light")}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">{t("common.theme_hint")}</TooltipContent>
          </Tooltip>
        </div>
      </aside>

      {/* La transition de page ne couvre QUE ce panneau : la barre latérale ne
          change pas d'une route à l'autre, la faire clignoter à chaque
          navigation faisait « tomber » tout l'écran. Fondu + 4 px, sur la durée
          et la courbe de tokens.css : assez court pour ne jamais retarder une
          navigation, assez présent pour que l'écran ne claque plus.

          `mode="wait"` : l'écran sortant s'efface avant que l'entrant
          apparaisse, sinon les deux se superposent et le fond transparaît une
          frame.

          `prefers-reduced-motion` est déjà neutralisé en CSS, mais Motion anime
          en JS : la règle CSS ne l'atteint pas, d'où `useReducedMotion`. */}
      <main className="flex-1 overflow-auto">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            className="h-full"
            initial={reduce ? false : { opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? undefined : { opacity: 0, y: -4 }}
            transition={{ duration: 0.18, ease: [0.33, 1, 0.68, 1] }}
          >
            <Suspense fallback={<RouteFallback />}>{outlet}</Suspense>
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
