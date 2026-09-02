// routes/LangLesson.tsx — Page SÉANCE plein écran (méthode Assimil).
//
// Une séance = 10 exercices joués en séquence, structurés en arc à 4 temps
// (ancrage → exposition → manipulation → clôture) autour d'un thème central.
// Chaque exercice est généré juste-à-temps côté serveur (le suivant préchargé en
// fond) et rendu via le dispatch KindBody partagé avec l'ancienne SessionView.
// Au premier accès à une langue, un test de niveau est proposé (PlacementFlow).
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { LangExercise, LangLessonSlot, LangSessionContent } from "../api/client";
import { KindBody } from "../features/lang/SessionView";
import { LangEntrySas } from "../features/lang/LangEntrySas";
import { LangExitSas } from "../features/lang/LangExitSas";
import { PlacementFlow } from "../features/lang/PlacementFlow";
import { PostExitRestSas } from "../features/session/PostExitRestSas";
import { useT } from "../i18n";

// Le SAS d'entrée s'affiche d'emblée pendant que la séance se génère en fond ;
// "preparing" (préparation de la séance) n'est qu'un dernier recours, affiché
// seulement si l'utilisateur a franchi les deux SAS avant la fin de la génération.
type Phase = "entry" | "placement" | "preparing" | "lesson" | "error";

interface LessonState {
  lessonId: number;
  theme: string;
  level: string;
  difficulty?: number;
  size: number;
  plan: LangLessonSlot[];
}

// Les quatre temps de l'arc, colorés par des JETONS et non par des littéraux :
// ces pastilles vivent dans la même barre que le reste de l'UI, elles doivent
// suivre le thème. `--hl-explain` est le seul bleu du système ; il sert ici de
// couleur d'exposition, ce qui est exactement son rôle ailleurs.
const TEMPS_COLOR: Record<string, string> = {
  ancrage: "var(--accent)",
  exposition: "var(--hl-explain)",
  manipulation: "var(--warning)",
  cloture: "var(--success)",
};

export function LangLesson() {
  const t = useT();
  const navigate = useNavigate();
  const { state } = useLocation();
  const navState = state as { language?: string; label?: string; needsPlacement?: boolean; rtl?: boolean } | null;
  const language = navState?.language;
  const label = navState?.label ?? language ?? "";
  // Sens d'écriture (arabe/hébreu) transmis par /lang : pilote le rendu droite-à-gauche
  // du texte cible dans les exercices.
  const rtl = !!navState?.rtl;
  // Indice de placement transmis par /lang (profil déjà chargé) : évite d'afficher le
  // SAS d'entrée pour rebondir ensuite sur le test de niveau. La réponse serveur reste
  // l'autorité (cf. generate()).
  const needsPlacement = !!navState?.needsPlacement;

  const [phase, setPhase] = useState<Phase>(needsPlacement ? "placement" : "entry");
  const [lesson, setLesson] = useState<LessonState | null>(null);
  const [exercises, setExercises] = useState<Record<number, LangExercise | null>>({});
  const [index, setIndex] = useState(0);
  const [loadingEx, setLoadingEx] = useState(false);
  // Rituel SAS (calqué sur le flux PDF) : entrée → séance → sortie → repos.
  const [sasDone, setSasDone] = useState(false);    // SAS d'entrée (mise en condition + warm-up) franchi
  const [genStatus, setGenStatus] = useState<"pending" | "ready" | "error">("pending"); // génération en fond
  const [done, setDone] = useState(false);          // séance terminée → SAS de sortie
  const [showRest, setShowRest] = useState(false);  // SAS de repos (étude d'Édimbourg)
  const [finalScore, setFinalScore] = useState(0);
  const [finalDuration, setFinalDuration] = useState(0);

  const scores = useRef<number[]>([]);   // score final par exercice
  const curAcc = useRef<number[]>([]);   // scores ponctuels de l'exercice courant
  const startedAt = useRef<number>(Date.now());

  useEffect(() => {
    if (!language) {
      navigate("/lang");
      return;
    }
    if (needsPlacement) {
      setPhase("placement");
      return;
    }
    startEntry();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language]);

  // Résolution du SAS d'entrée : une fois les deux SAS franchis, on entre dans la
  // séance si elle est prête, sinon on affiche "preparing" (dernier recours) le temps
  // que la génération se termine, puis on bascule automatiquement.
  useEffect(() => {
    if (!sasDone) return;
    if (genStatus === "ready") {
      startedAt.current = Date.now();
      setPhase("lesson");
    } else if (genStatus === "error") {
      setPhase("error");
    } else {
      setPhase("preparing");
    }
  }, [sasDone, genStatus]);

  // Lance le SAS d'entrée immédiatement ET la génération de la séance en parallèle.
  function startEntry() {
    setPhase("entry");
    setDone(false);
    setSasDone(false);
    setShowRest(false);
    setLesson(null);
    setExercises({});
    setIndex(0);
    scores.current = [];
    curAcc.current = [];
    setGenStatus("pending");
    void generate();
  }

  // Génération de la séance (LLM, lente) en tâche de fond pendant le SAS d'entrée.
  async function generate() {
    try {
      const res = await api.languageLessonStart(language!);
      if (res.needs_placement) {
        setPhase("placement");
        return;
      }
      if (res.error && !res.exercise) {
        setGenStatus("error");
        return;
      }
      setLesson({ lessonId: res.lesson_id, theme: res.theme, level: res.level, difficulty: res.difficulty_target, size: res.size, plan: res.plan });
      setExercises({ 0: res.exercise });
      setIndex(0);
      setGenStatus("ready");
    } catch {
      setGenStatus("error");
    }
  }

  function onScore(s: number) {
    curAcc.current.push(Math.max(0, Math.min(1, s)));
  }

  async function fetchExercise(idx: number) {
    setLoadingEx(true);
    try {
      const r = await api.languageLessonExercise(lesson!.lessonId, idx);
      setExercises((m) => ({ ...m, [idx]: r.exercise }));
    } catch {
      setExercises((m) => ({ ...m, [idx]: { error: t("lang.exercise_error") } as LangExercise }));
    } finally {
      setLoadingEx(false);
    }
  }

  async function next() {
    if (!lesson || loadingEx) return;
    // Fige le score de l'exercice courant (1 par défaut si aucun item noté).
    const acc = curAcc.current;
    scores.current[index] = acc.length ? acc.reduce((a, b) => a + b, 0) / acc.length : 1;
    curAcc.current = [];

    if (index >= lesson.size - 1) {
      await finish();
      return;
    }
    const nextIdx = index + 1;
    if (exercises[nextIdx] === undefined) {
      await fetchExercise(nextIdx);
    }
    setIndex(nextIdx);
  }

  async function finish() {
    if (!lesson) return;
    const arr: number[] = [];
    for (let i = 0; i < lesson.size; i++) arr.push(scores.current[i] ?? 1);
    const avg = arr.reduce((a, b) => a + b, 0) / (arr.length || 1);
    setFinalScore(avg);
    const durationS = Math.round((Date.now() - startedAt.current) / 1000);
    setFinalDuration(durationS);
    try {
      await api.languageLessonComplete(lesson.lessonId, arr, durationS);
    } catch {
      /* best-effort : la clôture ne doit pas casser l'UI */
    }
    setDone(true);
  }

  // ── Rendus d'état ────────────────────────────────────────────────────────────

  // Fin de séance → SAS de sortie (métacognition + analyse) → SAS de repos (Édimbourg).
  if (done && lesson) {
    if (showRest) {
      return <PostExitRestSas onDone={() => navigate("/lang")} />;
    }
    return (
      <div style={{ position: "fixed", inset: 0, background: "var(--bg)" }}>
        <LangExitSas
          lessonId={lesson.lessonId}
          durationS={finalDuration}
          exerciseCount={lesson.size}
          score={finalScore}
          onClose={() => setShowRest(true)}
        />
      </div>
    );
  }

  if (phase === "placement") {
    return (
      <Shell onExit={() => navigate("/lang")} exitLabel={t("lang.back_to_lang")}>
        <PlacementFlow language={language!} label={label} onDone={startEntry} />
      </Shell>
    );
  }
  if (phase === "error") {
    return (
      <Centered>
        <p style={{ color: "var(--danger)" }}>{t("lang.exercise_error")}</p>
        <button onClick={() => navigate("/lang")} style={ghostBtn}>{t("lang.back_to_lang")}</button>
      </Centered>
    );
  }

  // SAS d'entrée (mise en condition + warm-up flashcards de la langue) : affiché
  // immédiatement pendant que la séance se génère en fond. Le thème, dispo plus tard,
  // apparaît dès que la génération aboutit (accroche optionnelle).
  if (phase === "entry") {
    return (
      <div style={{ position: "fixed", inset: 0, background: "var(--bg)" }}>
        <LangEntrySas language={language!} label={label} theme={lesson?.theme ?? ""} onStart={() => setSasDone(true)} />
      </div>
    );
  }

  // Dernier recours : les deux SAS sont franchis mais la génération n'a pas fini.
  if (phase === "preparing") {
    return <Centered>{t("lang.preparing_lesson")}</Centered>;
  }

  // phase === "lesson"
  const ex = lesson ? exercises[index] : null;
  const isError = !ex || !!ex.error || !("kind" in (ex as object));
  const currentTemps = lesson?.plan[index]?.temps ?? "";
  const isLast = lesson ? index === lesson.size - 1 : false;

  return (
    <Shell onExit={() => navigate("/lang")} exitLabel={t("lang.exit_lesson")}>
      {lesson && (
        <div style={{ maxWidth: 820, margin: "0 auto", width: "100%" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <h1 style={{ fontFamily: "var(--font-title)", fontSize: "var(--text-h2)", margin: 0 }}>{lesson.theme}</h1>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {typeof lesson.difficulty === "number" && <DifficultyGauge value={lesson.difficulty} />}
              <span style={{ fontSize: 13, color: "var(--muted)" }}>{lesson.level}</span>
            </div>
          </div>

          <TempsBar plan={lesson.plan} index={index} />
          <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "6px 0 18px" }}>
            <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, color: TEMPS_COLOR[currentTemps] ?? "var(--accent)" }}>
              {t(`lang.temps_${currentTemps}`)}
            </span>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>
              {t("lang.exercise_n", { n: index + 1, total: lesson.size })}
            </span>
          </div>

          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-sm)", padding: "var(--space-lg)", minHeight: 180 }}>
            {loadingEx ? (
              <p style={{ color: "var(--muted)", fontStyle: "italic" }}>{t("lang.preparing_exercise")}</p>
            ) : isError ? (
              <div>
                <p style={{ color: "var(--danger)" }}>{(ex && ex.error) || t("lang.exercise_error")}</p>
                <button onClick={() => fetchExercise(index)} style={ghostBtn}>{t("lang.retry")}</button>
              </div>
            ) : (
              <KindBody content={ex as unknown as LangSessionContent} language={language!} rtl={rtl} onScore={onScore} />
            )}
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
            <button onClick={next} disabled={loadingEx} style={primaryBtn}>
              {isLast ? t("lang.finish_lesson") : t("lang.next_exercise")}
            </button>
          </div>
        </div>
      )}
    </Shell>
  );
}

function DifficultyGauge({ value }: { value: number }) {
  const t = useT();
  const v = Math.max(1, Math.min(10, value));
  return (
    <div title={`${t("lang.difficulty")} ${v}/10`} style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 11, color: "var(--muted)" }}>{t("lang.difficulty")}</span>
      <div style={{ display: "flex", gap: 2 }}>
        {Array.from({ length: 10 }, (_, i) => (
          <div
            key={i}
            style={{
              width: 5,
              height: 12,
              borderRadius: 1,
              background: i < v ? "var(--accent)" : "var(--border)",
              opacity: i < v ? 1 : 0.5,
            }}
          />
        ))}
      </div>
      <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-soft)" }}>{v}/10</span>
    </div>
  );
}

function TempsBar({ plan, index }: { plan: LangLessonSlot[]; index: number }) {
  return (
    <div style={{ display: "flex", gap: 4 }}>
      {plan.map((slot, i) => (
        <div
          key={i}
          title={slot.temps}
          style={{
            flex: 1,
            height: 6,
            borderRadius: 3,
            background: i <= index ? TEMPS_COLOR[slot.temps] ?? "var(--accent)" : "var(--border)",
            opacity: i <= index ? 1 : 0.5,
          }}
        />
      ))}
    </div>
  );
}

function Shell({ children, onExit, exitLabel }: { children: React.ReactNode; onExit: () => void; exitLabel: string }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "var(--bg)", overflowY: "auto" }}>
      <div style={{ padding: "14px 20px" }}>
        <button onClick={onExit} style={ghostBtn}>{exitLabel}</button>
      </div>
      <div style={{ padding: "0 20px 60px" }}>{children}</div>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ position: "fixed", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14, color: "var(--muted)" }}>
      {children}
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  border: "none",
  background: "var(--accent)",
  color: "var(--on-accent)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 20px",
  fontWeight: 600,
  cursor: "pointer",
};

const ghostBtn: React.CSSProperties = {
  border: "1px solid var(--border)",
  background: "var(--surface)",
  color: "var(--text)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 14px",
  fontWeight: 600,
  cursor: "pointer",
};

