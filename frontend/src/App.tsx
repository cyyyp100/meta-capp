import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { Home } from "./routes/Home";

// Code-splitting par route : recharts (Stats) et react-rnd (Reader) ne sont
// chargés qu'à l'ouverture de l'écran concerné -> bundle initial plus léger.
const Stats = lazy(() => import("./routes/Stats").then((m) => ({ default: m.Stats })));
const ScienceSources = lazy(() => import("./routes/ScienceSources").then((m) => ({ default: m.ScienceSources })));
const Flashcards = lazy(() => import("./routes/Flashcards").then((m) => ({ default: m.Flashcards })));
const Quiz = lazy(() => import("./routes/Quiz").then((m) => ({ default: m.Quiz })));
const Lang = lazy(() => import("./routes/Lang").then((m) => ({ default: m.Lang })));
const LangLesson = lazy(() => import("./routes/LangLesson").then((m) => ({ default: m.LangLesson })));
const Brainstorming = lazy(() => import("./routes/Brainstorming").then((m) => ({ default: m.Brainstorming })));
const Reader = lazy(() => import("./routes/Reader").then((m) => ({ default: m.Reader })));

function Loading() {
  return <div style={{ padding: 40, color: "var(--muted)" }}>Chargement…</div>;
}

export function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Home />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/stats/science" element={<ScienceSources />} />
          <Route path="/flashcards" element={<Flashcards />} />
          <Route path="/quiz" element={<Quiz />} />
          <Route path="/lang" element={<Lang />} />
          <Route path="/brainstorming" element={<Brainstorming />} />
        </Route>
        {/* Le Reader et la séance de langue sont plein écran (pas de barre latérale). */}
        <Route path="/reader/:docId" element={<Reader />} />
        <Route path="/lang/lesson" element={<LangLesson />} />
      </Routes>
    </Suspense>
  );
}
