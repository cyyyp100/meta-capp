// names.ts — Le nom d'une séance, par catégorie. Une seule définition pour la
// frise et pour l'en-tête du détail, sinon les deux divergent.
//
//   lecture : « <titre du document> · Lecture n »
//   quiz    : la matière (ou « Multi-apprentissage »), et la précision tapée
//   langue  : la langue, puis l'épisode du feuilleton ou le thème de la leçon
import type { LanguageView, ProgressSessionRow } from "@/api/client";

import type { useT } from "../../i18n";
import { subjectName } from "../stats/labels";

type T = ReturnType<typeof useT>;

export interface QuizNaming {
  mode: "subject" | "multi";
  subject: string | null;
  topic: string | null;
}

export interface LangNaming extends LanguageView {
  flow: "feuilleton" | "lecons";
  mode: string | null;
  theme: string;
  episode: { n: number; title: string } | null;
}

/**
 * Lecture. Sans document (session orpheline), on retombe sur le libellé
 * générique ; sans rang connu, sur le titre seul.
 */
export function sessionName(t: T, title: string, readingIndex: number): string {
  if (!title) return t("progress.detail_title");
  if (!(readingIndex > 0)) return title;
  return `${title} · ${t("progress.reading_n", { n: readingIndex })}`;
}

export function quizName(t: T, quiz: QuizNaming): string {
  const base =
    quiz.mode === "multi"
      ? t("quiz.mode_multi")
      : quiz.subject
        ? subjectName(t, quiz.subject)
        : t("subj.all");
  return quiz.topic ? t("progress.quiz_topic", { base, topic: quiz.topic }) : base;
}

export function langName(t: T, lang: LangNaming): string {
  let what: string;
  if (lang.episode) {
    what = t("feuil.episode_n", { n: lang.episode.n });
    if (lang.episode.title) what = `${what} — ${lang.episode.title}`;
  } else if (lang.flow === "lecons") {
    what = lang.theme || t("progress.lang_lesson");
  } else {
    what = t(`progress.lang_mode.${lang.mode ?? "episode"}`);
  }
  const language = lang.flag ? `${lang.flag} ${lang.language_label}` : lang.language_label;
  return `${language} · ${what}`;
}

export function rowName(t: T, row: ProgressSessionRow): string {
  if (row.kind === "quiz" && row.quiz) return quizName(t, row.quiz);
  if (row.kind === "lang" && row.lang) return langName(t, row.lang);
  return sessionName(t, row.document_title ?? "", row.reading_index ?? 0);
}
