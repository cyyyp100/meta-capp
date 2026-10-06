import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { RouteFallback } from "./components/RouteFallback";
import { BrowserShellHost } from "./features/shell/BrowserShellHost";
import { TourHost } from "./features/tour/TourHost";
import { Home } from "./routes/Home";

// Code-splitting par route : recharts (Stats) et react-rnd (Reader) ne sont
// chargés qu'à l'ouverture de l'écran concerné -> bundle initial plus léger.
const Stats = lazy(() => import("./routes/Stats").then((m) => ({ default: m.Stats })));
const ScienceSources = lazy(() => import("./routes/ScienceSources").then((m) => ({ default: m.ScienceSources })));
const Flashcards = lazy(() => import("./routes/Flashcards").then((m) => ({ default: m.Flashcards })));
const Quiz = lazy(() => import("./routes/Quiz").then((m) => ({ default: m.Quiz })));
const Lang = lazy(() => import("./routes/Lang").then((m) => ({ default: m.Lang })));
const LangLesson = lazy(() => import("./routes/LangLesson").then((m) => ({ default: m.LangLesson })));
const LangEpisode = lazy(() => import("./routes/LangEpisode").then((m) => ({ default: m.LangEpisode })));
const Brainstorming = lazy(() => import("./routes/Brainstorming").then((m) => ({ default: m.Brainstorming })));
// La porte du lecteur : elle ne monte `Reader` que sur un document lisible
// (un fichier introuvable n'ouvre ni session ni WebSocket).
const Reader = lazy(() => import("./routes/ReaderRoute").then((m) => ({ default: m.ReaderRoute })));
const Progress = lazy(() => import("./routes/Progress").then((m) => ({ default: m.Progress })));
const Settings = lazy(() => import("./routes/Settings").then((m) => ({ default: m.Settings })));

/**
 * Aucune animation à ce niveau : elle emporterait la barre latérale avec elle,
 * alors que seule la moitié droite de l'écran change. La transition de page vit
 * donc dans `AppLayout`, autour du seul `<Outlet />` (cf. le commentaire là-bas).
 *
 * Ce `Suspense` ne sert plus qu'aux routes PLEIN ÉCRAN (Reader, séance de
 * langue), qui n'ont pas de barre latérale et sortent donc du layout ; celles du
 * layout ont le leur, à l'intérieur du panneau de droite.
 */
export function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
      {/* La visite guidée est montée ICI, au-dessus des routes, et non dans
          `AppLayout` : la moitié de ce qu'elle montre (le lecteur, les sas) est
          plein écran, donc hors du layout. Tant qu'elle y vivait, ses étapes de
          lecture devenaient actives sans que rien ne les peigne. */}
      <TourHost />
      {/* Mode navigateur : présence de l'onglet et écran « arrêté ». Au-dessus
          des routes pour la même raison : le lecteur est hors du layout. */}
      <BrowserShellHost />
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Home />} />
          <Route path="/stats" element={<Stats />} />
          {/* La progression est une EXTENSION du profil, pas une destination
              autonome : le radar dit où on en est, elle dit comment on y est
              arrivé. Son adresse le dit aussi — et c'est le bas de /stats qui y
              mène, là où traînait autrefois l'export de données. */}
          <Route path="/stats/progress" element={<Progress />} />
          <Route path="/stats/science" element={<ScienceSources />} />
          <Route path="/flashcards" element={<Flashcards />} />
          <Route path="/quiz" element={<Quiz />} />
          <Route path="/lang" element={<Lang />} />
          <Route path="/brainstorming" element={<Brainstorming />} />
          {/* La SECTION vit dans l'URL : la barre de menu native ouvre
              directement /settings/updates ou /settings/about, ce qu'un
              dialogue — sans adresse — ne saurait pas faire. */}
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/:section" element={<Settings />} />
        </Route>
        {/* Le Reader et la séance de langue sont plein écran (pas de barre latérale). */}
        <Route path="/reader/:docId" element={<Reader />} />
        <Route path="/lang/lesson" element={<LangLesson />} />
        {/* Méthode « feuilleton » : langues du pilote (plan de refonte, § 15.2). */}
        <Route path="/lang/episode" element={<LangEpisode />} />
      </Routes>
    </Suspense>
  );
}
