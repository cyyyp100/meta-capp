// client.ts — Appels typés à l'API locale. Chemins /api relatifs : fonctionnent
// en dev (proxy Vite) comme en prod (FastAPI sert le bundle, même origine).
import type {
  DiffOp,
  EpisodeNote,
  EpisodeView,
  EventsResult,
  FeuilletonStatus,
  LibraryEntry,
  PlacementItemView,
  PlacementOutcome,
  PointView,
  RunCompletion,
  RunEvent,
  RunPlan,
} from "./feuilleton";
import { extraTokenParam } from "./security";
import type { PickedDocument } from "./platform";
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
  QuizSessionRecord,
  QuizSessionSettings,
  QuizSubject,
  ReaderBlock,
  RelinkResult,
  SavedHighlight,
  SessionAnalysis,
  SessionMetrics,
} from "./types";

/** Erreur d'un appel d'API. `message` est le `detail` du serveur, `code` l'état
 *  qu'il nomme quand l'interface doit y réagir autrement qu'en l'affichant
 *  (`different_file` : proposer de relier quand même). */
export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

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
    throw await apiError(res);
  }
  return (await res.json()) as T;
}

/** Mode navigateur : le CONTENU du fichier, copié côté serveur (services/uploads)
 *  — un navigateur ne donne jamais de chemin. Corps brut, comme `importDb`. */
async function uploadFile<T>(url: string, file: File): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: file,
  });
  if (!res.ok) {
    throw await apiError(res);
  }
  return (await res.json()) as T;
}

/** Erreur lisible : le `detail` de FastAPI est déjà traduit côté serveur (le
 *  garde-fou de cycle, par exemple) — bien plus utile qu'un « 400 ». */
async function apiError(res: Response): Promise<ApiError> {
  let message = `${res.status} ${res.statusText}`;
  let code: string | undefined;
  try {
    const data = await res.json();
    if (data && typeof data.detail === "string") message = data.detail;
    if (data && typeof data.code === "string") code = data.code;
  } catch {
    // Réponse non-JSON : on retombe sur le statut.
  }
  return new ApiError(message, res.status, code);
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
      if (!r.ok) throw await apiError(r);
      return r.json() as Promise<{ deleted_folders: number; detached_documents: number }>;
    }),
  moveDocument: (docId: number, folderId: number | null) =>
    postJSON<{ ok: boolean; document: DocumentSummary }>(
      `/api/library/doc/${docId}/folder`,
      { folder_id: folderId },
    ),
  // Renomme le TITRE du document (clic droit → Renommer) — jamais le fichier.
  renameDocument: (docId: number, title: string) =>
    postJSON<{ ok: boolean; document: DocumentSummary }>(
      `/api/library/doc/${docId}/rename`,
      { title },
    ),
  // Retire le document de la bibliothèque — jamais le fichier de l'utilisateur.
  deleteDocument: (docId: number) =>
    fetch(`/api/library/doc/${docId}`, { method: "DELETE" }).then(async (r) => {
      if (!r.ok) throw await apiError(r);
      return r.json() as Promise<{ deleted: boolean; id: number }>;
    }),
  flashcards: (filters?: { difficulty?: number; tags?: string }) => {
    const p = new URLSearchParams();
    if (filters?.difficulty) p.set("difficulty", String(filters.difficulty));
    if (filters?.tags) p.set("tags", filters.tags);
    const qs = p.toString();
    return getJSON<Flashcard[]>(`/api/flashcards${qs ? `?${qs}` : ""}`);
  },
  reviewFlashcard: (id: number, verdict: string) =>
    postJSON<{ ok: boolean }>(`/api/flashcards/${id}/review`, { verdict }),
  // `created: false` = la carte existait déjà (même recto/verso) : rien d'écrit.
  createFlashcard: (front: string, back: string, source = "manual") =>
    postJSON<{ id: number; created: boolean }>("/api/flashcards", { front, back, source }),
  // Flashcard intelligente (autoportante) : le LLM réécrit recto/verso côté serveur.
  // Le serveur reconnaît un échange déjà transformé et rend la carte existante.
  createFlashcardFromExchange: (front: string, back: string, docId?: number, page?: number) =>
    postJSON<{ id: number; front: string; back: string; created: boolean }>("/api/flashcards/from-exchange", {
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
  /** Le choix de `pickDocument()`, quelle que soit la coque : un chemin lu sur
   *  place (fenêtre native) ou un fichier envoyé (navigateur). */
  importDocument: (picked: PickedDocument) =>
    "path" in picked
      ? postJSON<DocumentDetail>("/api/library/import", { path: picked.path })
      : uploadFile<DocumentDetail>(`/api/library/upload?filename=${encodeURIComponent(picked.file.name)}`, picked.file),
  /** « Localiser le fichier… » : le même document, relié au fichier choisi.
   *  `force` relie un contenu différent (nouvelle version) — seulement après la
   *  confirmation que demande l'erreur `different_file`. */
  relinkDocument: (docId: number, picked: PickedDocument, force = false) =>
    "path" in picked
      ? postJSON<RelinkResult>(`/api/library/doc/${docId}/relink`, { path: picked.path, force })
      : uploadFile<RelinkResult>(
          `/api/library/doc/${docId}/relink/upload?filename=${encodeURIComponent(picked.file.name)}&force=${force}`,
          picked.file,
        ),
  quizSubjects: () => getJSON<QuizSubject[]>("/api/quiz/subjects"),
  quizOptions: () => getJSON<QuizOptions>("/api/quiz/options"),
  // `topic` : précision libre DANS la matière (« révolution française »), ou dans
  // toute la base si aucune matière n'est choisie.
  // `n` omis = longueur par défaut du serveur (cf. /api/quiz/options) : l'UI ne
  // recopie pas une valeur que `config/settings.py` déclare déjà.
  // `interleaved` : le mode « multi-apprentissage » (pratique entrelacée). Le
  // serveur ignore alors `subject` et `topic` — l'UI ne les envoie pas, mais
  // l'exclusivité est sa règle à lui.
  quizQuestions: (n?: number, subject?: string, topic?: string, interleaved?: boolean) => {
    const params = new URLSearchParams();
    if (n) params.set("n", String(n));
    if (subject) params.set("subject", subject);
    if (topic?.trim()) params.set("topic", topic.trim());
    if (interleaved) params.set("interleaved", "true");
    return getJSON<QuizQuestion[]>(`/api/quiz/questions?${params}`);
  },
  // Maîtrise de la matière, réponse par réponse. Le profil, lui, glisse à la
  // clôture de la séance, vers sa courbe de jauges (`quizRecordSession`).
  submitQuizAnswer: (category: string | null, correct: boolean, verdict?: string) =>
    postJSON<{ updated: boolean; level?: number; verdict: string }>(
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
  // Séance jouée, enregistrée d'un bloc à la fin (ou quand on la quitte) : ses
  // réponses deviennent une courbe de jauges. `session_id` rattache ensuite le
  // bilan et la clôture ; nul s'il n'y avait aucune réponse.
  quizRecordSession: (body: {
    settings: QuizSessionSettings;
    answers: QuizAnswerRecord[];
    duration_s: number;
  }) => postJSON<QuizSessionRecord>("/api/quiz/session", body),
  // Analyse LLM de fin de session de quiz (dans le cadre choisi) + cours à
  // renforcer. Avec `sessionId`, le bilan est gardé avec la séance.
  quizAnalysis: (answers: QuizAnswerRecord[], settings: QuizSessionSettings, sessionId?: number | null) =>
    postJSON<QuizAnalysis>("/api/quiz/analysis", { answers, settings, session_id: sessionId ?? null }),
  // Clôture : le profil glisse vers la courbe de jauges de la séance (une fois).
  quizFinalize: (sessionId: number) =>
    postJSON<{ ok: boolean; score: number; session_id: number }>("/api/quiz/finalize", {
      session_id: sessionId,
      responses: [],
    }),
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
  // Retour à la bibliothèque depuis le sas d'entrée : la session n'a pas eu
  // lieu, elle est effacée plutôt que close (409 si elle a déjà été jouée).
  abandonSession: (sid: number) => postJSON<{ abandoned: boolean }>(`/api/session/${sid}/abandon`, {}),
  // Coupe toute génération LLM en cours (file + en vol). Sans entrée.
  cancelGenerations: () => postJSON<{ cancelled: boolean }>("/api/reader/cancel", {}),
  endSession: (sid: number, pagesRead: number, durationS: number) =>
    postJSON<SessionMetrics>(`/api/session/${sid}/end`, { pages_read: pagesRead, duration_s: durationS }),
  // `questions` = les intitulés réellement affichés (2 fixes + celle générée) :
  // sans eux, la 3e réflexion serait persistée sous un libellé générique.
  finalizeSession: (sid: number, responses: string[], questions: string[]) =>
    postJSON<{ ok: boolean; score: number }>(`/api/session/${sid}/finalize`, { responses, questions }),
  // Série d'ÉTUDE : ce GET est une lecture pure — la série avance à la fin
  // d'une session, plus à l'ouverture de l'app (cf. nwol/db/user.py).
  streak: () => getJSON<StudyStreak>("/api/streak"),
  languages: () =>
    getJSON<{ code: string; label: string; flag: string; script?: string; rtl?: boolean; flow?: "feuilleton" | "legacy" }[]>(
      "/api/lang/languages",
    ),
  // ── Méthode « feuilleton » (langues du pilote) ─────────────────────────────
  // Aucun de ces appels n'attend Clikoda : le serveur répond tout de suite, la
  // génération des épisodes tourne en tâche de fond.
  feuilletonStatus: (language: string) =>
    getJSON<FeuilletonStatus>(`/api/lang/${encodeURIComponent(language)}/status`),
  feuilletonOnboarding: (language: string, interests: string[], hasStudied: boolean) =>
    postJSON<{ ok: boolean; next: "zero" | "placement" | "home" }>(`/api/lang/${encodeURIComponent(language)}/onboarding`, {
      interests,
      has_studied: hasStudied,
    }),
  feuilletonPlacement: (language: string) =>
    getJSON<{ items: PlacementItemView[] }>(`/api/lang/${encodeURIComponent(language)}/placement`),
  feuilletonPlacementSubmit: (language: string, answers: Record<string, number>) =>
    postJSON<PlacementOutcome>(`/api/lang/${encodeURIComponent(language)}/placement/submit`, { answers }),
  // `warmup` : cartes révisées au sas d'entrée, décomptées du plafond de cartes de la séance.
  feuilletonRunStart: (language: string, mode?: "court" | "relecture", warmup = 0) =>
    postJSON<RunPlan>(`/api/lang/${encodeURIComponent(language)}/run/start`, { ...(mode ? { mode } : {}), warmup }),
  feuilletonRun: (runId: number) => getJSON<RunPlan>(`/api/lang/run/${runId}`),
  feuilletonEvents: (runId: number, events: RunEvent[], currentStep: string | null) =>
    postJSON<EventsResult>(`/api/lang/run/${runId}/events`, { events, current_step: currentStep }),
  feuilletonComplete: (runId: number, endReason: "fini" | "plafond" | "quitte", feeling: string | null) =>
    postJSON<RunCompletion>(`/api/lang/run/${runId}/complete`, { end_reason: endReason, feeling }),
  feuilletonLibrary: (language: string) =>
    getJSON<LibraryEntry[]>(`/api/lang/${encodeURIComponent(language)}/library`),
  feuilletonEpisode: (episodeId: number) =>
    getJSON<EpisodeView & { notes: EpisodeNote[]; point: PointView }>(`/api/lang/episode/${episodeId}`),
  feuilletonReport: (episodeId: number, line: number | null, token: number | null, kind: string, comment = "") =>
    postJSON<{ ok: boolean }>("/api/lang/report", { episode_id: episodeId, line, token, kind, comment }),
  feuilletonCompare: (original: string, typed: string) =>
    postJSON<{ ops: DiffOp[] }>("/api/lang/compare", { original, typed }),
  feuilletonRewind: (language: string) =>
    postJSON<{ ok: boolean; queued: number }>(`/api/lang/${encodeURIComponent(language)}/rewind`, {}),
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
  // `null` = exercice sans item noté : il ne compte pas dans la moyenne.
  languageLessonComplete: (lessonId: number, exerciseScores: (number | null)[], durationS: number) =>
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
  langLessonFinalize: (lessonId: number, responses: string[], questions: string[]) =>
    postJSON<{ ok: boolean; score: number }>(`/api/lang/lesson/${lessonId}/finalize`, {
      responses,
      questions,
    }),
  languagePlacementStart: (language: string) =>
    postJSON<LangPlacementTest>("/api/lang/placement/start", { language }),
  languagePlacementSubmit: (language: string, answers: Record<string, string>) =>
    postJSON<LangPlacementResult>("/api/lang/placement/submit", { language, answers }),
  languagePlacementSkip: (language: string) =>
    postJSON<LangPlacementResult>("/api/lang/placement/skip", { language }),
  docHook: (docId: number, page = 1) =>
    getJSON<{ hook: string }>(`/api/library/doc/${docId}/hook?page=${page}`),
  // Warm-up du SAS d'entrée : 5 cartes sélectionnées par pertinence (dues + récence/matière).
  sessionStartCards: (docId: number, limit = 5) =>
    getJSON<Flashcard[]>(`/api/flashcards/session-start?doc_id=${docId}&limit=${limit}`),
  // Analyse LLM de la session + LA 3e question de réflexion, générée pour cette
  // session. Les deux arrivent ensemble parce qu'ils s'affichent ensemble.
  // Best-effort : analyse "" si indisponible, question toujours renseignée.
  sessionAnalysis: (sid: number) =>
    getJSON<SessionAnalysis>(`/api/session/${sid}/analysis`),
  // ── Brainstorming (chat libre + RAG sur la base utilisateur) ─────────────────
  brainstormDiscussions: () => getJSON<BrainstormDiscussion[]>("/api/brainstorming/discussions"),
  // Sans titre, le serveur rouvre la discussion vierge existante au lieu d'en créer une autre.
  createDiscussion: (title?: string, folderId: number | null = null) =>
    postJSON<BrainstormDiscussion>("/api/brainstorming", { title: title ?? null, folder_id: folderId }),
  // Au-delà de 5 épinglées, le serveur répond 400 (message traduit dans l'Error).
  pinDiscussion: (id: number, pinned: boolean) =>
    postJSON<BrainstormDiscussion>(`/api/brainstorming/${id}/pin`, { pinned }),
  // Lie la discussion à un dossier de la bibliothèque (null = toute la base).
  setDiscussionFolder: (id: number, folderId: number | null) =>
    postJSON<BrainstormDiscussion>(`/api/brainstorming/${id}/folder`, { folder_id: folderId }),
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

  // ── Réglages d'application (app_settings) ────────────────────────────────
  // Persistés côté serveur et NON dans le localStorage : ils doivent survivre à
  // « Restaurer une sauvegarde », ce que le stockage du webview ne fait pas.
  preferences: () => getJSON<PreferencesPayload>("/api/preferences"),
  setPreferences: (patch: Partial<Record<PreferenceKey, string | boolean>>) =>
    postJSON<{ preferences: Preferences }>("/api/preferences", patch),
  setUserName: (name: string) =>
    postJSON<{ user: { id: number; name: string } }>("/api/preferences/name", { name }),

  // ── Mises à jour ─────────────────────────────────────────────────────────
  // Opt-in strict : tant que `updates_check` est faux, cet appel ne déclenche
  // AUCUNE requête sortante côté serveur (cf. nwol/services/updates.py).
  checkUpdates: () => getJSON<UpdateStatus>("/api/updates/check"),

  // ── Coque : mode navigateur ──────────────────────────────────────────────
  // `browser_mode` est faux en fenêtre native et en dev : ni « Quitter », ni
  // présence (cf. nwol/services/lifecycle.py, features/shell/BrowserShellHost).
  shell: () => getJSON<{ browser_mode: boolean }>("/api/shell"),
  quitApp: () => postJSON<{ stopping: boolean }>("/api/shell/quit", {}),

  // ── Visite guidée : le document emprunté ─────────────────────────────────
  // Aucun paramètre, ni ici ni côté serveur : ces deux routes n'agissent que
  // sur le document que le service a lui-même créé, jamais sur un document de
  // l'utilisateur (cf. nwol/services/onboarding.py).
  //
  // `document: null` n'est pas une erreur — c'est « ressource absente », et la
  // visite saute alors son chapitre lecture.
  borrowDemoDocument: () =>
    postJSON<{ document: DocumentSummary | null }>("/api/onboarding/demo", {}),
  returnDemoDocument: () =>
    fetch("/api/onboarding/demo", { method: "DELETE" }).then((r) => {
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json() as Promise<{ ok: boolean }>;
    }),

  // ── Ma progression (historique longitudinal) ─────────────────────────────
  // `kind` omis : toutes catégories mêlées. Filtré côté serveur, et non dans la
  // frise : sinon une rafale de quiz évinçait les lectures des 40 lignes servies.
  progressSessions: (limit = 40, kind?: ProgressKind) =>
    getJSON<ProgressTimeline>(`/api/progress/sessions?limit=${limit}${kind ? `&kind=${kind}` : ""}`),
  progressSession: (sessionId: number) =>
    getJSON<ProgressSession>(`/api/progress/session/${sessionId}`),
  // Détail d'une séance de quiz ou de langue (ids propres aux séances de pratique).
  progressPractice: (sessionId: number) =>
    getJSON<PracticeProgress>(`/api/progress/practice/${sessionId}`),
  // Bilan de la semaine — le rendez-vous récurrent, pas un cumul depuis toujours.
  weeklyRecap: () => getJSON<WeeklyRecap>("/api/progress/weekly"),
};

// ── Réglages ──────────────────────────────────────────────────────────────────
export type PreferenceKey =
  | "theme"
  | "density"
  | "text_size"
  | "updates_check"
  | "tour_done"
  | "entry_sas_s";
export type Preferences = Record<PreferenceKey, string>;

export interface PreferencesPayload {
  preferences: Preferences;
  choices: Record<PreferenceKey, string[]>;
  lang: string;
  supported_langs: string[];
  user: { id: number; name: string };
}

/** `checked: false` = la vérification n'a rien donné (hors ligne, panne, option
 *  coupée). L'interface n'affiche alors rien : un échec de vérification n'est
 *  pas un événement pour l'utilisateur. */
export interface UpdateStatus {
  enabled: boolean;
  current: string;
  latest: string | null;
  update_available: boolean;
  url: string;
  checked: boolean;
}

// ── Progression ───────────────────────────────────────────────────────────────
/** Les catégories de « Ma progression ». */
export type ProgressKind = "reading" | "quiz" | "lang";

/** Langue d'une séance, telle que la page Langues l'affiche. */
export interface LanguageView {
  language: string;
  language_label: string;
  flag: string;
}

/**
 * Une ligne de la frise. `session_id` n'est unique qu'au sein d'une famille :
 * la clé d'une ligne est (`kind`, `session_id`). Les champs propres à chaque
 * catégorie sont dans la ligne (lecture) ou sous `quiz` / `lang`.
 */
export interface ProgressSessionRow {
  kind: ProgressKind;
  session_id: number;
  started_at: string;
  ended_at: string;
  duration_s: number;
  completed: boolean;
  criteria_moved: number;
  profile_delta: number;
  has_reflections: boolean;
  // Lecture
  document_id?: number | null;
  document_title?: string;
  /** « Lecture n » de ce document (0 : session sans document). */
  reading_index?: number;
  pages_read?: number;
  quiz?: {
    mode: "subject" | "multi";
    subject: string | null;
    topic: string | null;
    questions_answered: number;
    success_rate: number;
  };
  lang?: LanguageView & {
    flow: "feuilleton" | "lecons";
    mode: string | null;
    theme: string;
    episode: { n: number; title: string } | null;
  };
}

export interface ProgressTimeline {
  sessions: ProgressSessionRow[];
  total: number;
  /** Effectif de chaque catégorie, toutes séances confondues. */
  counts: Record<ProgressKind, number>;
  criteria: string[];
}

export interface WeeklyRecap {
  since: string;
  sessions: number;
  by_kind?: Record<ProgressKind, number>;
  duration_s: number;
  pages_read: number;
  documents: string[];
  movers: { criterion: string; delta: number }[];
  /** Le texte que Clikoda réécrit à chaque finalisation — jamais régénéré ici. */
  analysis: string;
  analysis_updated_at: string;
  cards: { id: number; front: string; back: string }[];
}

export interface ProgressChange {
  criterion: string;
  before: number;
  after: number;
  delta: number;
  recorded_at: string;
}

export interface GaugePoint {
  t: number;
  value: number;
}

/** La courbe des jauges pendant une séance — le point commun des trois catégories. */
export interface GaugeSeries {
  /** Ce que porte `t` : des secondes (lecture, épisode de langue), un numéro de
   *  question (quiz) ou d'exercice (leçon de langue). */
  axis: "time" | "question" | "exercise";
  seed: Record<string, number>;
  series: Record<string, GaugePoint[]>;
  /** Jauges que la séance a réellement exercées — les autres sont restées à
   *  leur amorce et ne veulent rien dire. */
  measured: string[];
}

export interface Reflection {
  question: string;
  answer: string;
  created_at: string;
}

export interface ProgressSession {
  kind: "reading";
  session_id: number;
  document: { id: number | null; title: string; subject: string };
  /** « Lecture n » de ce document (0 : session sans document). */
  reading_index: number;
  started_at: string;
  ended_at: string;
  completed: boolean;
  metrics: SessionMetrics;
  gauges: GaugeSeries;
  profile_changes: ProgressChange[];
  reflections: Reflection[];
  page_dwell: { page: number; dwell_s: number; visits: number }[];
  pauses?: SessionPause[];
}

/** Une réponse d'une séance de quiz, telle qu'elle a été jouée. */
export interface QuizPlayedAnswer {
  position: number;
  question: string;
  question_type: string;
  category: string;
  source: string;
  user_answer: string;
  verdict: "correct" | "partial" | "incorrect";
  /** false : verdict de l'apprenant (auto-évaluation, « je ne sais pas »). */
  graded: boolean;
  response_time_ms: number | null;
  document_id: number | null;
  document_title: string;
  chapter_title: string;
}

interface PracticeProgressBase {
  session_id: number;
  started_at: string;
  ended_at: string;
  completed: boolean;
  gauges: GaugeSeries;
  profile_changes: ProgressChange[];
  reflections: Reflection[];
  /** Ce que Clikoda a écrit à la fin de la séance — relu, jamais régénéré. */
  analysis: string;
}

export interface QuizProgress extends PracticeProgressBase {
  kind: "quiz";
  metrics: {
    duration_s: number;
    questions_answered: number;
    correct: number;
    partial: number;
    points: number;
    success_rate: number;
  };
  quiz: {
    mode: "subject" | "multi";
    subject: string | null;
    topic: string | null;
    answers: QuizPlayedAnswer[];
    by_category: { category: string; points: number; total: number }[];
    courses_to_review: {
      document_id: number;
      title: string;
      chapters: string[];
      answered: number;
      missed: number;
    }[];
    weak_subjects: string[];
  };
}

export interface LangProgress extends PracticeProgressBase {
  kind: "lang";
  metrics: { duration_s: number; answered: number };
  lang: LanguageView & {
    flow: "feuilleton" | "lecons";
    mode: string | null;
    theme: string;
    level: string;
    episode: { n: number; title: string } | null;
    point: string | null;
    new_words: string[];
    cards_created: number;
    acquired_today: number;
    units_acquired_today: number;
    words_seen: number | null;
    words_acquired: number | null;
    signals: {
      understood: "compris" | "a_peu_pres" | "pas_compris" | null;
      reveal_rate: number | null;
      games_rate: number | null;
      second_wave_rate: number | null;
      answered: number | null;
    };
    exercises: { label: string; skill: string; score: number | null }[];
  };
}

export type PracticeProgress = QuizProgress | LangProgress;

/** Une pause prise pendant la lecture, et ce qui l'a précédée. */
export interface SessionPause {
  started_at: string;
  page: number | null;
  duration_s: number;
  /** Durée conseillée par Clikoda (secondes), null pour une pause manuelle. */
  planned_s: number | null;
  source: "manual" | "suggested";
  /** Une recommandation du LLM était arrivée juste avant (ou la carte a été acceptée). */
  after_recommendation: boolean;
  recommendation_kind: string | null;
  recommendation_delay_s: number | null;
  attention_at_start: number | null;
  ended_by: "resume" | "disconnect";
}

export interface StudyStreak {
  streak: number;
  longest_streak: number;
  last_study_day: string | null;
  active: boolean;
}

export interface BrainstormSource {
  source_type: "highlight" | "qa" | "flashcard" | "document" | "mistake";
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
  /** Non null = épinglée (en tête de liste, dans l'ordre d'épinglage). */
  pinned_at: string | null;
  /** Dossier lié : Clikoda ne puise que dans ses documents (sous-dossiers compris). */
  folder_id: number | null;
  folder_name: string | null;
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
  pinned_at: string | null;
  folder_id: number | null;
  folder_name: string | null;
  messages: BrainstormMessage[];
  /** Une question de la discussion est en cours côté serveur (partie d'un autre canal). */
  answering: boolean;
}

export interface LangLesson {
  lesson_n: number;
  theme: string;
  dialogue: { speaker: string; target: string; phonetic: string; translation: string }[];
  notes: { grammar?: string; pronunciation?: string; cultural?: string };
  vocabulary: { word: string; phonetic?: string; translation: string; example: string }[];
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
      glossary: { word: string; phonetic?: string; translation: string }[];
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
// `rev` est l'empreinte du contenu (`content_hash`) : le PNG est servi
// `immutable`, et un document relié à une AUTRE version de son fichier
// (« Localiser… », puis « Relier quand même ») ne doit pas garder l'ancienne
// image dans le cache du navigateur.
export function pageImageUrl(docId: number, page: number, zoom = 0.4, rev?: string | null): string {
  const version = rev ? `&v=${encodeURIComponent(rev)}` : "";
  return `/api/library/doc/${docId}/page/${page}.png?zoom=${zoom}${version}${extraTokenParam()}`;
}
