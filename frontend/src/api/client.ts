// client.ts — Appels typés à l'API locale. Chemins /api relatifs : fonctionnent
// en dev (proxy Vite) comme en prod (FastAPI sert le bundle, même origine).
import { extraTokenParam } from "./security";
import type {
  DocumentDetail,
  DocumentSummary,
  Flashcard,
  FolderNode,
  Health,
  HighlightAnchor,
  MetacogOverview,
  PageWord,
  QuizAnalysis,
  QuizAnswerRecord,
  QuizEvaluation,
  QuizOptions,
  QuizQuestion,
  QuizSubject,
  ReaderBlock,
  SavedHighlight,
  SessionMetrics,
} from "./types";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await errorMessage(res));
  }
  return (await res.json()) as T;
}

/** Message d'erreur lisible : le `detail` de FastAPI est déjà traduit côté
 *  serveur (le garde-fou de cycle, par exemple) — bien plus utile qu'un « 400 ». */
async function errorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (data && typeof data.detail === "string") return data.detail;
  } catch {
    // Réponse non-JSON : on retombe sur le statut.
  }
  return `${res.status} ${res.statusText}`;
}

export const api = {
  health: () => getJSON<Health>("/api/health"),
  statsOverview: () => getJSON<MetacogOverview>("/api/stats/overview"),
  recentDocuments: (limit = 12) => getJSON<DocumentSummary[]>(`/api/library/recent?limit=${limit}`),
  document: (id: number) => getJSON<DocumentDetail>(`/api/library/doc/${id}`),

  // ── Bibliothèque : catalogue, recherche et dossiers ──────────────────────
  // Le catalogue est servi d'un bloc et le rail filtre côté client : un
  // glisser-déposer doit être instantané, sans aller-retour réseau.
  libraryDocuments: () => getJSON<DocumentSummary[]>("/api/library/documents"),
  searchDocuments: (q: string) => {
    const p = new URLSearchParams({ q });
    return getJSON<DocumentSummary[]>(`/api/library/search?${p.toString()}`);
  },
  folders: () => getJSON<FolderNode[]>("/api/library/folders"),
  createFolder: (name: string, parentId: number | null = null) =>
    postJSON<FolderNode>("/api/library/folders", { name, parent_id: parentId }),
  renameFolder: (id: number, name: string) =>
    postJSON<FolderNode>(`/api/library/folders/${id}/rename`, { name }),
  moveFolder: (id: number, parentId: number | null) =>
    postJSON<FolderNode>(`/api/library/folders/${id}/move`, { parent_id: parentId }),
  deleteFolder: (id: number) =>
    fetch(`/api/library/folders/${id}`, { method: "DELETE" }).then(async (r) => {
      if (!r.ok) throw new Error(await errorMessage(r));
      return r.json() as Promise<{ deleted_folders: number; detached_documents: number }>;
    }),
  moveDocument: (docId: number, folderId: number | null) =>
    postJSON<{ ok: boolean; document: DocumentSummary }>(
      `/api/library/doc/${docId}/folder`,
      { folder_id: folderId },
    ),
  flashcards: (filters?: { difficulty?: number; tags?: string }) => {
    const p = new URLSearchParams();
    if (filters?.difficulty) p.set("difficulty", String(filters.difficulty));
    if (filters?.tags) p.set("tags", filters.tags);
    const qs = p.toString();
    return getJSON<Flashcard[]>(`/api/flashcards${qs ? `?${qs}` : ""}`);
  },
  reviewFlashcard: (id: number, verdict: string) =>
    postJSON<{ ok: boolean }>(`/api/flashcards/${id}/review`, { verdict }),
  createFlashcard: (front: string, back: string, source = "manual") =>
    postJSON<{ id: number }>("/api/flashcards", { front, back, source }),
  // Flashcard intelligente (autoportante) : le LLM réécrit recto/verso côté serveur.
  createFlashcardFromExchange: (front: string, back: string, docId?: number, page?: number) =>
    postJSON<{ id: number; front: string; back: string }>("/api/flashcards/from-exchange", {
      front,
      back,
      doc_id: docId ?? null,
      page: page ?? null,
    }),
  deleteFlashcard: (id: number) =>
    fetch(`/api/flashcards/${id}`, { method: "DELETE" }).then((r) => {
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json();
    }),
  importPdf: (path: string) => postJSON<DocumentDetail>("/api/library/import", { path }),
  quizSubjects: () => getJSON<QuizSubject[]>("/api/quiz/subjects"),
  quizOptions: () => getJSON<QuizOptions>("/api/quiz/options"),
  // `topic` : sujet libre de la session (« capitales », « révolution française »).
  // `n` omis = longueur par défaut du serveur (cf. /api/quiz/options) : l'UI ne
  // recopie pas une valeur que `config/settings.py` déclare déjà.
  quizQuestions: (n?: number, subject?: string, topic?: string) => {
    const params = new URLSearchParams();
    if (n) params.set("n", String(n));
    if (subject) params.set("subject", subject);
    if (topic?.trim()) params.set("topic", topic.trim());
    return getJSON<QuizQuestion[]>(`/api/quiz/questions?${params}`);
  },
  submitQuizAnswer: (category: string | null, correct: boolean, verdict?: string) =>
    postJSON<{ updated: boolean; level?: number; retention: number; verdict: string }>(
      "/api/quiz/answer", { category, correct, verdict },
    ),
  // Correction d'une réponse rédigée (ou d'une remise en ordre) : c'est elle qui
  // permet au quiz de rejouer autre chose que des QCM.
  quizEvaluate: (body: {
    question_id: number;
    question: string;
    user_answer: string;
    question_type?: string;
    answer?: string;
    choices?: string[] | null;
  }) => postJSON<QuizEvaluation>("/api/quiz/evaluate", body),
  // Langue du backend : pilote les prompts LLM, pas seulement les libellés.
  setBackendLang: (lang: string) =>
    postJSON<{ lang: string; supported: string[] }>("/api/preferences/lang", { lang }),
  // Analyse LLM de fin de session de quiz + conseils de cours à renforcer.
  quizAnalysis: (answers: QuizAnswerRecord[]) =>
    postJSON<QuizAnalysis>("/api/quiz/analysis", { answers }),
  // Sas de sortie du quiz : réflexions de métacognition + nudge du profil.
  quizFinalize: (body: {
    responses: string[];
    score: number;
    questions_answered: number;
    correct: number;
    duration_s: number;
    subject?: string | null;
    topic?: string | null;
  }) => postJSON<{ ok: boolean; score: number }>("/api/quiz/finalize", body),
  searchPage: (docId: number, page: number, q: string) =>
    getJSON<{ rects_pts: number[][] }>(`/api/library/doc/${docId}/page/${page}/search?q=${encodeURIComponent(q)}`),
  pageBlocks: (docId: number, page: number) =>
    getJSON<{ blocks: ReaderBlock[] | null }>(`/api/library/doc/${docId}/page/${page}/blocks`),
  pageWords: (docId: number, page: number) =>
    getJSON<{ words: PageWord[] }>(`/api/library/doc/${docId}/page/${page}/words`),
  listHighlights: (docId: number) =>
    getJSON<SavedHighlight[]>(`/api/library/doc/${docId}/highlights`),
  createHighlight: (
    docId: number,
    body: {
      page: number;
      quote: string;
      rects: number[][];
      color?: string;
      anchor?: HighlightAnchor | null;
    },
  ) => postJSON<{ id: number }>(`/api/library/doc/${docId}/highlights`, body),
  deleteHighlight: (docId: number, highlightId: number) =>
    fetch(`/api/library/doc/${docId}/highlights/${highlightId}`, { method: "DELETE" }).then((r) => {
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json();
    }),
  startSession: (docId: number) => postJSON<{ session_id: number }>("/api/session/start", { doc_id: docId }),
  endSession: (sid: number, pagesRead: number, durationS: number) =>
    postJSON<SessionMetrics>(`/api/session/${sid}/end`, { pages_read: pagesRead, duration_s: durationS }),
  finalizeSession: (sid: number, responses: string[]) =>
    postJSON<{ ok: boolean; score: number }>(`/api/session/${sid}/finalize`, { responses }),
  streak: () => getJSON<{ streak: number }>("/api/streak"),
  languages: () =>
    getJSON<{ code: string; label: string; flag: string; script?: string; rtl?: boolean }[]>("/api/lang/languages"),
  languageProfile: (language: string) =>
    getJSON<{
      profile: Record<string, unknown>;
      progress: { total_sessions: number; total_lessons?: number; avg_score: number; skills?: LangSkills };
      script?: string;
      rtl?: boolean;
      tonal?: boolean;
      script_kind?: string;
    }>(`/api/lang/profile?language=${encodeURIComponent(language)}`),
  // Vue par langue pour la page profil (score global + niveau + compétences).
  langStats: () => getJSON<LangStatEntry[]>("/api/lang/stats"),
  languageLesson: (language: string) =>
    postJSON<LangLesson>("/api/lang/lesson", { language }),
  // Séquenceur adaptatif : décide + génère UNE session juste-à-temps.
  languageSession: (language: string) => postJSON<LangSession>("/api/lang/session", { language }),
  languageSessionComplete: (language: string, sessionType: string, score: number, durationS: number) =>
    postJSON<{ ok: boolean; total_sessions: number }>("/api/lang/session/complete", {
      language,
      session_type: sessionType,
      score,
      duration_s: durationS,
    }),
  languageCorrect: (language: string, targetPhrase: string, userAttempt: string) =>
    postJSON<LangCorrection>("/api/lang/correct", {
      language,
      target_phrase: targetPhrase,
      user_attempt: userAttempt,
    }),
  // Pont SR → séance : repousse/rapproche l'échéance d'une carte révisée en séance.
  languageReviewCard: (
    language: string,
    verdict: "correct" | "partial" | "incorrect",
    opts: { cardId?: number; word?: string },
  ) =>
    postJSON<{ ok: boolean; matched: boolean; card_id?: number }>("/api/lang/sr-review", {
      language,
      verdict,
      card_id: opts.cardId ?? null,
      word: opts.word ?? "",
    }),
  // ── Séances Assimil (10 exercices, arc 4 temps) ──────────────────────────────
  languageLessonStart: (language: string) =>
    postJSON<LangLessonStart>("/api/lang/lesson/start", { language }),
  languageLessonExercise: (lessonId: number, index: number) =>
    getJSON<LangLessonExerciseResp>(`/api/lang/lesson/${lessonId}/exercise/${index}`),
  languageLessonComplete: (lessonId: number, exerciseScores: number[], durationS: number) =>
    postJSON<{ ok: boolean; total_lessons: number }>(`/api/lang/lesson/${lessonId}/complete`, {
      exercise_scores: exerciseScores,
      duration_s: durationS,
    }),
  // Warm-up du SAS d'entrée d'une séance : cartes filtrées par langue (dues + récentes).
  langWarmupCards: (language: string) =>
    getJSON<Flashcard[]>(`/api/lang/warmup-cards?language=${encodeURIComponent(language)}`),
  // Bilan LLM de la séance (best-effort) + décomposition par compétence.
  langLessonAnalysis: (lessonId: number) =>
    getJSON<LangLessonAnalysis>(`/api/lang/lesson/${lessonId}/analysis`),
  // Finalisation métacognitive : réflexions + nudge du profil global.
  langLessonFinalize: (lessonId: number, responses: string[]) =>
    postJSON<{ ok: boolean; score: number }>(`/api/lang/lesson/${lessonId}/finalize`, { responses }),
  languagePlacementStart: (language: string) =>
    postJSON<LangPlacementTest>("/api/lang/placement/start", { language }),
  languagePlacementSubmit: (language: string, answers: Record<string, string>) =>
    postJSON<LangPlacementResult>("/api/lang/placement/submit", { language, answers }),
  languagePlacementSkip: (language: string) =>
    postJSON<LangPlacementResult>("/api/lang/placement/skip", { language }),
  docHook: (docId: number, page = 1) =>
    getJSON<{ hook: string }>(`/api/library/doc/${docId}/hook?page=${page}`),
  dueFlashcards: (docId: number) => getJSON<Flashcard[]>(`/api/flashcards/due?doc_id=${docId}`),
  // Warm-up du SAS d'entrée : 5 cartes sélectionnées par pertinence (dues + récence/matière).
  sessionStartCards: (docId: number, limit = 5) =>
    getJSON<Flashcard[]>(`/api/flashcards/session-start?doc_id=${docId}&limit=${limit}`),
  // Analyse LLM de la session (best-effort, "" si indisponible).
  sessionAnalysis: (sid: number) => getJSON<{ analysis: string }>(`/api/session/${sid}/analysis`),
  // ── Brainstorming (chat libre + RAG sur la base utilisateur) ─────────────────
  brainstormDiscussions: () => getJSON<BrainstormDiscussion[]>("/api/brainstorming/discussions"),
  createDiscussion: (title?: string) =>
    postJSON<BrainstormDiscussion>("/api/brainstorming", { title: title ?? null }),
  discussionMessages: (id: number) => getJSON<BrainstormDetail>(`/api/brainstorming/${id}/messages`),
  deleteDiscussion: (id: number) =>
    fetch(`/api/brainstorming/${id}`, { method: "DELETE" }).then((r) => {
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json();
    }),
  // ── Sauvegarde / restauration des données ────────────────────────────────────
  importDb: (content: ArrayBuffer) =>
    fetch("/api/data/import", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: content,
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json())?.detail ?? `${r.status}`);
      return r.json() as Promise<{ restored: boolean }>;
    }),
  // Effacement total (S10/RGPD) : le serveur exige la confirmation exacte.
  purgeData: () => postJSON<{ purged: boolean }>("/api/data/purge", { confirm: "EFFACER" }),
};

export interface BrainstormSource {
  source_type: "highlight" | "qa" | "flashcard" | "document";
  doc_id?: number | null;
  doc_title?: string | null;
  page?: number | null;
  snippet: string;
}

export interface BrainstormDiscussion {
  id: number;
  title: string;
  summary: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface BrainstormMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: BrainstormSource[];
  created_at: string;
}

export interface BrainstormDetail {
  id: number;
  title: string;
  summary: string;
  messages: BrainstormMessage[];
}

export interface LangLesson {
  lesson_n: number;
  theme: string;
  dialogue: { speaker: string; target: string; phonetic: string; translation: string }[];
  notes: { grammar?: string; pronunciation?: string; cultural?: string };
  vocabulary: { word: string; translation: string; example: string }[];
  error?: string;
}

// ── Séquenceur adaptatif : contenu discriminé par render_kind ──────────────────
export interface LangQcm {
  question: string;
  choices: string[];
  correct: string;
  explanation: string;
  depth?: "literal" | "inference";
}

// Drills de phonétique : lecture, accent tonique, graphie↔son (corrigés client).
export type LangPhoneticDrill =
  | { kind?: "read"; target: string; phonetic: string; tone?: string; translation: string }
  | { kind: "stress"; word: string; syllables: string[]; stressed_index: number; translation: string }
  | { kind: "spell_to_sound"; written: string; options: string[]; answer: number; translation: string };

export interface LangProductionStep {
  prompt: string;
  hint: string;
  expected?: string;   // palier guidé
  reference?: string;  // palier libre
}

export type LangSessionContent =
  | {
      kind: "dialogue";
      theme: string;
      dialogue: LangLesson["dialogue"];
      notes: LangLesson["notes"];
      vocabulary: LangLesson["vocabulary"];
    }
  | {
      kind: "reading";
      title: string;
      text_target: string;
      text_translation: string;
      glossary: { word: string; translation: string }[];
      questions: LangQcm[];
    }
  | {
      kind: "vocabulary";
      items: {
        word: string;
        translation: string;
        phonetic?: string;
        tone?: string;
        example_target: string;
        example_translation: string;
      }[];
      questions: LangQcm[];
    }
  | {
      kind: "phonetics";
      focus_sound: string;
      explanation: string;
      minimal_pairs: { a: string; b: string; note: string }[];
      drills: LangPhoneticDrill[];
    }
  | { kind: "translation"; items: { prompt_fr: string; expected: string; hint: string }[] }
  | { kind: "dictation"; segments: { target: string; phonetic: string; translation: string }[] }
  | {
      kind: "production";
      mode?: "two_step" | "tasks";
      instructions: string;
      guided?: LangProductionStep | null;
      free?: LangProductionStep | null;
      tasks?: { prompt: string; context: string; reference: string; hint: string }[];
    }
  | {
      kind: "revision";
      exercises: { type: string; prompt_fr: string; expected: string; target_word: string; hint: string; card_id?: number }[];
    }
  | {
      kind: "cloze";
      mode: "bank" | "free";
      instructions: string;
      sentences: { text: string; blanks: string[]; options?: string[]; translation: string }[];
    }
  | {
      kind: "ordering";
      task: string;
      items: { tokens: string[]; solution: string[]; translation: string }[];
    }
  | {
      kind: "matching";
      task: string;
      pairs: { left: string; right: string }[];
    }
  | {
      kind: "transform";
      task: string;
      items: { source: string; expected: string; focus: string; hint: string }[];
    }
  | {
      kind: "writing";
      intro: string;
      signs: {
        sign: string;
        name: string;
        sound: string;
        translit: string;
        tone?: string;
        example_word: string;
        example_translit: string;
        example_translation: string;
      }[];
      reading: { target: string; translit: string; translation: string }[];
      drill: LangQcm[];
    };

export interface LangSession {
  session_type: string;
  render_kind: string;
  label: string;
  reason: string;
  content: LangSessionContent;
  error?: string;
}

// Un exercice de séance = un LangSessionContent enrichi de son rôle dans l'arc.
export type LangExercise = LangSessionContent & {
  temps?: string;
  slot_index?: number;
  render_kind?: string;
  label?: string;
  error?: string;
};

export interface LangLessonSlot {
  slot_index: number;
  temps: string;
  label: string;
  render_kind: string;
}

export interface LangLessonStart {
  lesson_id: number;
  theme: string;
  level: string;
  phase: string;
  difficulty_target?: number;
  size: number;
  plan: LangLessonSlot[];
  index: number;
  exercise: LangExercise | null;
  error?: string;
  // Renvoyé à la place du reste si le test de niveau n'a pas encore été passé.
  needs_placement?: boolean;
  language?: string;
  script?: string;
}

export interface LangLessonExerciseResp {
  lesson_id: number;
  index: number;
  size: number;
  exercise: LangExercise;
  error?: string;
}

// Score moyen 0–100 + nombre d'exercices par compétence (analyse poussée).
export type LangSkills = Record<string, { score: number; count: number }>;

export interface LangStatEntry {
  language: string;
  label: string;
  flag: string;
  level: string;
  global_score: number;
  total_lessons: number;
  skills: LangSkills;
}

export interface LangLessonAnalysis {
  analysis: string;
  skills: LangSkills;
}

export interface LangPlacementItem {
  id: number | string;
  format: "qcm" | "translation";
  question: string;
  choices?: string[];
}

export interface LangPlacementTest {
  items?: LangPlacementItem[];
  error?: string;
}

export interface LangPlacementResult {
  ok?: boolean;
  level?: string;
  phase?: string;
  comment?: string;
  error?: string;
}

export interface LangCorrection {
  verdict: "correct" | "partial" | "incorrect";
  corrections: { original: string; corrected: string; reason: string; error_type?: string }[];
  feedback: string;
  score: number;
  error?: string;
}

// URL de la vignette/page d'un document (servie + cachée par le backend).
export function pageImageUrl(docId: number, page: number, zoom = 0.4): string {
  return `/api/library/doc/${docId}/page/${page}.png?zoom=${zoom}${extraTokenParam()}`;
}
