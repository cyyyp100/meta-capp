// api/feuilleton.ts — Types du module langues, méthode « feuilleton ».
//
// Miroir de ce que renvoient services/lang_runs.py et routers/lang.py. Tout ce
// qui décide (mode de séance, aides visibles, corrigés, plafond) est calculé
// côté serveur : le front rend un plan et renvoie des événements.

/** Langue dans laquelle Clikoda écrit pour ce profil (traductions, notes…). */
export type ExplainLang = "fr" | "en";

export interface FeuilletonStatus {
  language: string;
  flow: "feuilleton";
  family: "latin" | "hanzi" | "arabe";
  /** Porte V17 : la langue ne peut pas s'ouvrir sur cette installation
   * (« pinyin » : mandarin sans pypinyin). Les autres champs sont alors absents. */
  unavailable?: string;
  explain_lang?: ExplainLang;
  onboarding_done: boolean;
  episode_n: number;
  next_episode: number;
  next_status: "queued" | "generating" | "ready" | "failed" | "played" | null;
  generating: boolean;
  bilan_due: boolean;
  /** Plus de 3 jours sans séance : la prochaine est une relecture imposée, sans
   * nouvel épisode ; l'épisode prêt attend la suivante (C7). */
  relecture_due: boolean;
  level: string;
  program: { order: number; size: number; point: string };
  words_seen: number;
  words_acquired: number;
  episodes_played: number;
  open_run: number | null;
  has_placement: boolean;
  /** Le modèle local qui écrit les épisodes (config/settings.py:OLLAMA_MODEL). */
  model: string;
  /** Échecs d'écriture de l'épisode à jouer, tant qu'il n'est pas prêt. */
  generation_failures: number;
  /** Où rappeler les limites du modèle local (le service décide, le front affiche). */
  pro_hints: ProHint[];
  /** Une correction d'expression écrite arrivée après sa séance, pas encore vue. */
  unseen_writing: { id: number; run_id: number | null } | null;
}

export type ProHint = "generation" | "program_end";

/** L'épisode suivant d'une langue ouverte (`GET /api/lang/upcoming`, lecture seule). */
export interface UpcomingEpisode {
  language: string;
  episode_n: number;
  /** `ready` : écrit, en attente de passage. `null` : pas encore réservé. */
  status: FeuilletonStatus["next_status"];
  /** Clikoda l'écrit en ce moment. */
  generating: boolean;
  /** Une relecture imposée passe avant lui (C7). */
  relecture_due: boolean;
}

export interface RubySyllable {
  hanzi: string;
  mark: string;
  num: string;
  tone: number;
  /** Pinyin encore affiché : caractère non acquis (M4). */
  show: boolean;
}

export interface EpToken {
  text: string;
  /** Mot tapable (les espaces et la ponctuation ne le sont pas). */
  w: boolean;
  g?: number | null;
  ruby?: RubySyllable[];
  suspect?: boolean;
  /** Arabe : texte montré selon le niveau d'aide, et ce que révèle le tap. */
  display?: string;
  translit?: string | null;
  tap_vocalized?: string;
  bare?: string;
  validated?: string | null;
  reported?: boolean;
}

export interface EpLine {
  speaker: string;
  translation: string;
  tokens: EpToken[];
}

export interface GlossEntry {
  form: string;
  lemma: string;
  translation: string;
  pos: string | null;
  gender: string | null;
  article: string | null;
  pron: string | null;
  vocalized: string | null;
  faux_ami: string | null;
  acquired: boolean;
  transparent: boolean;
}

export interface EpisodeView {
  id: number;
  n: number;
  title: string;
  summary: string;
  teaser: string;
  format: string;
  kind: "normal" | "respiration";
  family: "latin" | "hanzi" | "arabe";
  dir: "ltr" | "rtl";
  aid_level: number | null;
  tone_colors: boolean;
  gender_colors: boolean;
  explain_lang?: ExplainLang;
  lines: EpLine[];
  glossary: GlossEntry[];
}

export interface EpisodeNote {
  n: number;
  line: number;
  tokens: number[];
  kind: string;
  text: string;
  auto: boolean;
}

export interface PointView {
  title: string;
  learner_goal: string;
  kind: string | null;
  observation: string;
  explanation: string;
  highlights: { line: number; tokens: number[]; example: string }[];
  episode_ref?: number;
  /** Bilan : la règle et « à retenir » de la leçon du point, quand elle existe. */
  rule?: string;
  remember?: string;
}

/** La leçon d'un point (services/lang_point_lesson.py), prononciations calculées. */
export interface Lesson {
  rule: string;
  forms: { columns: string[]; rows: string[][] } | null;
  uses: { use: string; example: string; translation: string; pron?: string | null }[];
  pitfalls: { wrong: string; right: string; why: string; pron?: string | null }[];
  examples: { text: string; translation: string; pron?: string | null }[];
  remember: string;
}

/** Ce que renvoie GET /api/lang/run/{id}/lesson en entrant dans l'étape. */
export interface LessonState {
  lesson: Lesson | null;
  lesson_source: "file" | "db" | "fallback" | null;
  lesson_pending: boolean;
  lesson_items: GameItem[];
}

/** Une touche du clavier d'expression écrite (`label` : ce qui s'affiche). */
export interface KeyboardKey {
  char: string;
  label: string;
}

export interface WritingKeyboard {
  layout: "keys" | "ime";
  rtl: boolean;
  groups: { name: string; keys: KeyboardKey[] }[];
}

export interface WritingWord {
  form: string;
  match: string[];
  translation: string;
}

/** La consigne de l'expression écrite, déterministe (services/lang_writing.py). */
export interface WritingTask {
  kind: "repondre" | "message" | "journal" | "decrire" | "suite";
  prompt: string;
  speaker: string | null;
  use_words: WritingWord[];
  use_forms: string[];
  length: { min: number; max: number; unit: "words" | "chars" };
  bank: WritingWord[];
  tier_index: number;
  explain_lang: ExplainLang;
  max_chars: number;
}

export type WritingStatus = "pending" | "correcting" | "ready" | "failed" | "skipped";

export interface WritingChecks {
  length: { value: number; min: number; max: number; unit: "words" | "chars"; ok: boolean };
  script: { ok: boolean; problem: string | null };
  words_used: { form: string; used: boolean }[];
  forms_used: { form: string; used: boolean }[];
}

export interface WritingFeedbackData {
  verdict: "correct" | "partial" | "incorrect";
  errors: { original: string; correction: string; error_type: string; explanation: string }[];
  corrected: string;
  praise: string;
}

export interface WritingView {
  id: number;
  run_id: number | null;
  status: WritingStatus;
  text: string;
  task: WritingTask;
  checks: WritingChecks | null;
  feedback: WritingFeedbackData | null;
  corrected_at: string | null;
  seen: boolean;
}

export interface GameItem {
  ref: string;
  kind: string;
  // La forme de `prompt`, `options` et `expected` dépend du jeu (services/lang_games.py).
  prompt: Record<string, unknown>;
  options?: unknown[];
  expected: unknown;
  episode_id?: number;
}

export interface Game {
  kind: string;
  ease: number;
  items: GameItem[];
}

export interface DueCard {
  id: number;
  front: string;
  back: string;
  pronunciation?: string | null;
  /** Face écrite dans la langue apprise : recto pour une carte du feuilleton, verso pour une carte héritée. */
  pronunciation_side?: "front" | "back" | null;
}

export interface RunStep {
  key: string;
  kind: string;
  budget_s: number;
  essential: boolean;
  episode_ref?: number | null;
  // Contenu propre à l'étape.
  [field: string]: unknown;
}

export interface RunPlan {
  /** Format du plan : 2 = lecture unique, leçon, expression écrite. */
  version: number;
  run_id: number;
  status: string;
  current_step: string | null;
  done_steps: string[];
  resumed: boolean;
  effective_s: number;
  mode: "zero" | "episode" | "bilan" | "reprise" | "relecture" | "court" | "jalon";
  language: string;
  family: "latin" | "hanzi" | "arabe";
  rtl: boolean;
  target_s: number;
  max_s: number;
  idle_cutoff_s: number;
  episodes: Record<string, EpisodeView>;
  steps: RunStep[];
  episode_id: number | null;
  episode_n: number | null;
  absence: { days: number | null; tier: string };
  tone: string;
}

export type RunEvent =
  | { type: "step"; step: string; started?: boolean; ended?: boolean; active_s?: number; skipped?: boolean; signal?: string | null }
  | { type: "reveal"; episode_id: number; line: number; token: number; pass: string }
  /** Traduction d'une réplique montrée — la réplique seule, ou « Tout traduire » (`all`). */
  | { type: "line"; episode_id: number; line: number; pass: string; all?: boolean }
  | { type: "answer"; item: string; given: unknown; ms?: number }
  | { type: "rating"; episode_id: number; line: number; typed?: string | null; rating: "su" | "a_peu_pres" | "pas_su" }
  | { type: "card"; card_id: number; verdict: "correct" | "partial" | "incorrect" };

export interface EventsResult {
  ok: boolean;
  effective_s?: number;
  cap_reached?: boolean;
  skip_to?: string | null;
  status?: string;
}

export interface RunCompletion {
  ok: boolean;
  mode: string;
  episode: { n: number; title: string } | null;
  point: string | null;
  new_words: string[];
  cards_created: number;
  words_seen: number;
  words_acquired: number;
  acquired_today: number;
  units_acquired_today: number;
  suggest_rewind: number | null;
  /** L'expression écrite de la séance : l'écran de fin attend sa correction. */
  writing: { id: number; status: WritingStatus } | null;
}

export interface PlacementItemView {
  id: string;
  kind: "qcm" | "lecture" | "signes";
  prompt: string;
  choices: string[];
  cefr: string;
}

export interface PlacementOutcome {
  ok: boolean;
  level: string;
  start_order: number;
  start_point: string;
  correct: number;
  total: number;
}

export interface LibraryEntry {
  id: number;
  n: number;
  title: string;
  summary: string;
  kind: string;
  format: string;
}

export interface DiffOp {
  op: "equal" | "missing" | "extra";
  text: string;
}
