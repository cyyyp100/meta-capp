// Lecon — L'étape « leçon » : observer, comprendre, s'entraîner.
//
// 1. Observer : la question du point, les seules répliques d'exemple
//    surlignées (le texte complet se déplie), l'explication de l'épisode.
// 2. La leçon : règle, tableau de formes, emplois, pièges, exemples (pinyin ou
//    translittération calculés par le serveur), « à retenir ». Écrite une fois
//    par point ; si elle ne l'était pas encore à l'assemblage de la séance
//    (`lesson_pending`), elle est redemandée en entrant dans l'étape — sans
//    attendre : sinon, l'étape garde son repli (titre, but, explication).
// 3. S'entraîner : trois micro-items tirés du texte, trois de la leçon.
// En séance courte (`compact`), la règle et « à retenir » seulement ; la leçon
// complète reste repliée.
import { useEffect, useState } from "react";

import { api } from "../../../api/client";
import type { GameItem, Lesson, PointView } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { EpisodeText } from "./EpisodeText";
import { GameItemView } from "./Games";
import { answerFor, episodeOf, NextButton, type StepProps } from "./Steps";
import { Card, StepTitle, Target } from "./ui";

export function LeconStep({ step, plan, tracker, onNext }: StepProps) {
  const t = useT();
  const episode = episodeOf(plan, step.episode_ref)!;
  const point = step.point as PointView;
  const compact = !!step.compact;
  const [lesson, setLesson] = useState<Lesson | null>((step.lesson as Lesson | null) ?? null);
  const [lessonItems, setLessonItems] = useState<GameItem[]>((step.lesson_items as GameItem[]) ?? []);
  const [phase, setPhase] = useState<"observe" | "lesson" | "practice">("observe");

  // Leçon pas encore écrite à l'assemblage : relue une fois, sans attendre.
  useEffect(() => {
    if (!step.lesson_pending) return;
    let alive = true;
    api
      .feuilletonLesson(plan.run_id)
      .then((state) => {
        if (alive && state.lesson) {
          setLesson(state.lesson);
          setLessonItems(state.lesson_items);
        }
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [plan.run_id, step.lesson_pending]);

  const items = [...((step.items as GameItem[]) ?? []), ...lessonItems];
  const exampleLines = point.highlights.map((h) => h.line);
  const practice = (
    <div style={{ display: "grid", gap: 16, marginTop: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", color: "var(--accent-ink)" }}>
        {t("feuil.lecon.practice")}
      </div>
      {items.map((item) => (
        <GameItemView key={item.ref} item={item} episodes={plan.episodes} rtl={plan.rtl} onAnswer={answerFor(tracker)} />
      ))}
    </div>
  );

  return (
    <Card>
      <StepTitle hint={point.learner_goal}>{`${t("feuil.lecon.title")} : ${point.title}`}</StepTitle>
      {(phase === "observe" || compact) && (
        <>
          {point.observation && <p style={{ fontWeight: 600 }}>{point.observation}</p>}
          <EpisodeText
            episode={episode}
            highlights={point.highlights}
            onlyLines={exampleLines.length ? exampleLines : undefined}
          />
          {exampleLines.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: "pointer", color: "var(--muted)" }}>{t("feuil.lecon.full_text")}</summary>
              <div style={{ marginTop: 8 }}>
                <EpisodeText episode={episode} highlights={point.highlights} />
              </div>
            </details>
          )}
          {point.explanation && <p style={{ marginTop: 12, lineHeight: 1.6 }}>{point.explanation}</p>}
        </>
      )}
      {compact && (
        <>
          {lesson ? <RuleAndRemember lesson={lesson} /> : <p style={{ color: "var(--muted)" }}>{t("feuil.lecon.pending")}</p>}
          {lesson && (
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: "pointer", color: "var(--muted)" }}>{t("feuil.lecon.full_lesson")}</summary>
              <LessonBody lesson={lesson} rtl={plan.rtl} />
            </details>
          )}
          {items.length > 0 && practice}
          <NextButton onClick={() => onNext()} />
        </>
      )}
      {!compact && phase === "observe" && (
        <NextButton label={t("feuil.lecon.show_lesson")} onClick={() => setPhase("lesson")} />
      )}
      {!compact && phase === "lesson" && (
        <>
          {lesson ? <LessonBody lesson={lesson} rtl={plan.rtl} /> : <p style={{ color: "var(--muted)" }}>{t("feuil.lecon.pending")}</p>}
          <NextButton label={items.length ? t("feuil.lecon.go_practice") : undefined} onClick={() => (items.length ? setPhase("practice") : onNext())} />
        </>
      )}
      {!compact && phase === "practice" && (
        <>
          {/* La leçon reste à portée, repliée : revenir en arrière remonterait les
              items, et une réponse déjà donnée pourrait être redonnée. */}
          {lesson && (
            <details>
              <summary style={{ cursor: "pointer", color: "var(--muted)" }}>{t("feuil.lecon.back_lesson")}</summary>
              <LessonBody lesson={lesson} rtl={plan.rtl} />
            </details>
          )}
          {practice}
          <NextButton onClick={() => onNext()} />
        </>
      )}
    </Card>
  );
}

function RuleAndRemember({ lesson }: { lesson: Lesson }) {
  const t = useT();
  return (
    <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
      <p style={{ margin: 0, lineHeight: 1.6 }}>{lesson.rule}</p>
      {lesson.remember && <Remember text={lesson.remember} label={t("feuil.lecon.remember")} />}
    </div>
  );
}

/** « À retenir », écrit dans la langue d'explication (il peut citer la langue cible). */
function Remember({ text, label }: { text: string; label: string }) {
  return (
    <div style={{ padding: "10px 12px", borderRadius: "var(--radius-md)", background: "var(--accent-soft)" }}>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "var(--accent-ink)" }}>{label}</div>
      <bdi dir="auto">{text}</bdi>
    </div>
  );
}

function Sentence({ text, pron, translation, rtl }: { text: string; pron?: string | null; translation?: string; rtl: boolean }) {
  return (
    <div>
      <Target rtl={rtl} style={{ fontSize: rtl ? 22 : 17 }}>{text}</Target>
      {pron && <div style={{ color: "var(--muted)", fontSize: 13 }}>{pron}</div>}
      {translation && <div style={{ color: "var(--text-soft)", fontStyle: "italic", fontSize: 14 }}>{translation}</div>}
    </div>
  );
}

/** La leçon entière : réutilisée par la bibliothèque. */
export function LessonBody({ lesson, rtl }: { lesson: Lesson; rtl: boolean }) {
  const t = useT();
  const heading = { fontSize: 12, fontWeight: 700, textTransform: "uppercase" as const, color: "var(--muted)", margin: "14px 0 6px" };
  return (
    <div style={{ marginTop: 12 }}>
      <div style={heading}>{t("feuil.lecon.rule")}</div>
      <p style={{ margin: 0, lineHeight: 1.6 }}>{lesson.rule}</p>
      {lesson.forms && (
        <>
          <div style={heading}>{t("feuil.lecon.forms")}</div>
          <div style={{ overflowX: "auto" }}>
            <table dir={rtl ? "rtl" : "ltr"} style={{ borderCollapse: "collapse", fontSize: rtl ? 18 : 15 }}>
              <thead>
                <tr>
                  {lesson.forms.columns.map((c, i) => (
                    <th key={i} style={{ textAlign: "start", padding: "4px 10px", borderBottom: "1px solid var(--border-strong)" }}>
                      <bdi dir="auto">{c}</bdi>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {lesson.forms.rows.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((cell, ci) => (
                      <td key={ci} style={{ padding: "4px 10px", borderBottom: "1px solid var(--border)", fontFamily: rtl ? "var(--font-arabic)" : undefined }}>
                        <bdi dir="auto">{cell}</bdi>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {lesson.uses.length > 0 && (
        <>
          <div style={heading}>{t("feuil.lecon.uses")}</div>
          <ul style={{ margin: 0, paddingInlineStart: 20, display: "grid", gap: 8 }}>
            {lesson.uses.map((u, i) => (
              <li key={i}>
                <div style={{ fontWeight: 600 }}>{u.use}</div>
                {u.example && <Sentence text={u.example} pron={u.pron} translation={u.translation} rtl={rtl} />}
              </li>
            ))}
          </ul>
        </>
      )}
      {lesson.pitfalls.length > 0 && (
        <>
          <div style={heading}>{t("feuil.lecon.pitfalls")}</div>
          <ul style={{ margin: 0, paddingInlineStart: 20, display: "grid", gap: 8 }}>
            {lesson.pitfalls.map((p, i) => (
              <li key={i}>
                <Target rtl={rtl} style={{ textDecoration: "line-through", color: "var(--danger)" }}>{p.wrong}</Target>
                {" → "}
                <Target rtl={rtl} style={{ fontWeight: 600 }}>{p.right}</Target>
                {p.pron && <div style={{ color: "var(--muted)", fontSize: 13 }}>{p.pron}</div>}
                {p.why && <div style={{ color: "var(--text-soft)", fontSize: 14 }}>{p.why}</div>}
              </li>
            ))}
          </ul>
        </>
      )}
      {lesson.examples.length > 0 && (
        <>
          <div style={heading}>{t("feuil.lecon.examples")}</div>
          <div style={{ display: "grid", gap: 8 }}>
            {lesson.examples.map((e, i) => (
              <Sentence key={i} text={e.text} pron={e.pron} translation={e.translation} rtl={rtl} />
            ))}
          </div>
        </>
      )}
      {lesson.remember && (
        <div style={{ marginTop: 14 }}>
          <Remember text={lesson.remember} label={t("feuil.lecon.remember")} />
        </div>
      )}
    </div>
  );
}
