// Le nom d'une séance, par catégorie : la frise et l'en-tête du détail lisent
// la même définition — une lecture par son document, un quiz par sa matière,
// une séance de langue par sa langue et son épisode (ou son thème).
import { describe, expect, it } from "vitest";

import type { ProgressSessionRow } from "@/api/client";

import { rowName } from "./names";

/** Faux `t` : renvoie la clé et ses paramètres, pour lire ce qui a été demandé. */
const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key}(${Object.values(params).join("|")})` : key;

const base = {
  started_at: "2026-10-06 10:00:00",
  ended_at: "2026-10-06T10:20:00",
  duration_s: 1200,
  completed: true,
  criteria_moved: 2,
  profile_delta: 3,
  has_reflections: false,
};

describe("rowName", () => {
  it("nomme une lecture par son document et son rang", () => {
    const row: ProgressSessionRow = {
      ...base, kind: "reading", session_id: 1, document_title: "Thermo.pdf", reading_index: 2,
    };
    expect(rowName(t, row)).toBe("Thermo.pdf · progress.reading_n(2)");
  });

  it("nomme un quiz par sa matière et la précision tapée", () => {
    const row: ProgressSessionRow = {
      ...base, kind: "quiz", session_id: 1,
      quiz: { mode: "subject", subject: "géographie", topic: "capitales", questions_answered: 5, success_rate: 70 },
    };
    expect(rowName(t, row)).toBe("progress.quiz_topic(subj.geography|capitales)");
  });

  it("nomme le multi-apprentissage sans matière ni précision", () => {
    const row: ProgressSessionRow = {
      ...base, kind: "quiz", session_id: 2,
      quiz: { mode: "multi", subject: null, topic: null, questions_answered: 4, success_rate: 75 },
    };
    expect(rowName(t, row)).toBe("quiz.mode_multi");
  });

  it("nomme un épisode du feuilleton par sa langue et son numéro", () => {
    const row: ProgressSessionRow = {
      ...base, kind: "lang", session_id: 3,
      lang: {
        language: "espagnol", language_label: "Espagnol", flag: "🇪🇸", flow: "feuilleton",
        mode: "episode", theme: "", episode: { n: 4, title: "Le marché" },
      },
    };
    expect(rowName(t, row)).toBe("🇪🇸 Espagnol · feuil.episode_n(4) — Le marché");
  });

  it("nomme une séance sans épisode par son mode, une leçon par son thème", () => {
    const lang = { language: "espagnol", language_label: "Espagnol", flag: "", theme: "", episode: null };
    const relecture: ProgressSessionRow = {
      ...base, kind: "lang", session_id: 4, lang: { ...lang, flow: "feuilleton", mode: "relecture" },
    };
    expect(rowName(t, relecture)).toBe("Espagnol · progress.lang_mode.relecture");
    const lesson: ProgressSessionRow = {
      ...base, kind: "lang", session_id: 5, lang: { ...lang, flow: "lecons", mode: null, theme: "Au café" },
    };
    expect(rowName(t, lesson)).toBe("Espagnol · Au café");
  });
});
