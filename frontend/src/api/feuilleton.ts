// api/feuilleton.ts — Types du module langues, méthode « feuilleton ».
//
// Miroir de ce que renvoient services/lang_runs.py et routers/lang.py. Tout ce
// qui décide (mode de séance, aides visibles, corrigés, plafond) est calculé
// côté serveur : le front rend un plan et renvoie des événements.

/** Langue dans laquelle Gemma écrit pour ce profil (traductions, notes…). */
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
  level: string;
  program: { order: number; size: number; point: string };
  words_seen: number;
  words_acquired: number;
  episodes_played: number;
  open_run: number | null;
  has_placement: boolean;
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
