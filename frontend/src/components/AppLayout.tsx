import {
  BarChart3,
  Globe,
  HelpCircle,
  Home,
  Layers,
  MessageSquare,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Suspense, useCallback } from "react";
import { NavLink, useLocation, useNavigate, useOutlet } from "react-router-dom";

import { api } from "@/api/client";
import { pickFilePath } from "@/api/platform";
import { RouteFallback } from "@/components/RouteFallback";
import { cn } from "@/lib/utils";

import { useT } from "../i18n";
import { useAppShortcuts } from "../features/shell/useAppShortcuts";
import { usePreferences, useThemeFromServer } from "../features/shell/usePreferences";
import { UserMenu } from "../features/shell/UserMenu";
import { useDisplayPreferences } from "@/theme/useDisplayPreferences";

import { TourHost } from "../features/tour/TourHost";
import { useTourHydration } from "../features/tour/useTourHydration";

const NAV = [
  { to: "/", labelKey: "nav.home", Icon: Home, end: true },
  // Pas d'entrée « Progression » ici : elle vit sous /stats/progress, et on y
  // entre par le bas du profil. Deux destinations pour un même sujet — l'état
  // courant et son histoire — auraient forcé à choisir laquelle ouvrir sans
  // qu'aucune des deux ne se suffise.
  { to: "/stats", labelKey: "nav.profile", Icon: BarChart3, end: false },
  { to: "/flashcards", labelKey: "nav.flashcards", Icon: Layers, end: false },
  { to: "/quiz", labelKey: "nav.quiz", Icon: HelpCircle, end: false },
  { to: "/lang", labelKey: "nav.lang", Icon: Globe, end: false },
  { to: "/brainstorming", labelKey: "nav.brainstorming", Icon: MessageSquare, end: false },
];

export function AppLayout() {
  const t = useT();
  const location = useLocation();
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const { data: preferences } = usePreferences();
  const { data: streak } = useQuery({ queryKey: ["streak"], queryFn: api.streak });

  // Le thème stocké côté serveur fait autorité : `localStorage` n'est qu'un
  // cache d'amorçage, il ne survit pas à une restauration de sauvegarde.
  useThemeFromServer(preferences);
  // Densité et taille du texte : deux attributs sur <html>, toute la
  // conséquence visuelle dans tokens.css.
  useDisplayPreferences(preferences);
  // La visite ne peut rien afficher tant qu'on ignore si elle a déjà eu lieu.
  useTourHydration(preferences);

  // ⌘O : le même chemin que « Fichier ▸ Ouvrir un document… » du menu natif.
  const openDocument = useCallback(async () => {
    const path = await pickFilePath();
    if (!path) return;
    try {
      const doc = await api.importPdf(path);
      navigate(`/reader/${doc.id}`);
    } catch {
      // L'accueil porte déjà le message d'erreur d'import détaillé ; ici on ne
      // fait qu'y ramener plutôt que d'échouer en silence sur un raccourci.
      navigate("/");
    }
  }, [navigate]);
  useAppShortcuts({ onOpenDocument: () => void openDocument() });
  // `useOutlet()` plutôt que `<Outlet />` : il FIGE l'élément de la route
  // courante. Un `<Outlet />` rendu dans l'enveloppe sortante lirait le contexte
  // de routage à jour et afficherait déjà l'écran ENTRANT — le fondu de sortie
  // porterait sur le mauvais contenu.
  const outlet = useOutlet();

  return (
    <div className="flex h-full">
      {/* Monté une seule fois, hors des routes : les bulles traversent la
          navigation (import sur l'accueil, Gemma dans le lecteur). */}
      <TourHost />
      <aside className="flex w-58 shrink-0 flex-col border-r border-border bg-surface px-3.5 py-5.5">
        <div className="px-2.5 pb-4.5 font-serif text-h2 font-bold tracking-tight">
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

        {/* Le pied portait deux contrôles nus (segmenté FR/EN + bouton thème) :
            deux réglages exposés à plat, et aucune trace de la personne qui
            utilise le logiciel. Les réglages sont passés dans /settings ; ce qui
            reste ici, c'est QUI est là et depuis combien de jours. */}
        <div className="mt-auto pt-2">
          <UserMenu name={preferences?.user.name ?? "…"} streak={streak} />
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
