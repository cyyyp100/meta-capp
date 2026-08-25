// Types miroir des dicts renvoyés par nwol/services (contrat d'API).

export type TrendCategory = "in_progress" | "to_improve" | "stable";
export type Recommendation = "solid" | "progressing" | "to_review" | "to_improve";

export interface CriterionEntry {
  key: string;
  value: number;
  history: number[];
  delta: number;
}

export interface SubjectEntry {
  subject: string;
  level: number;
  history: number[];
  delta: number;
  updates: number;
  recommendation: Recommendation;
}

export interface MetacogOverview {
  user: { id: number; name: string };
  sessions_count: number;
  updated_at: string;
  global_score: number;
  trend: { category: TrendCategory; delta: number };
  criteria: CriterionEntry[];
  subjects: SubjectEntry[];
  general_analysis?: string;
  general_analysis_updated_at?: string;
}

export interface Health {
  status: string;
  version: string;
}

export interface DocumentSummary {
  id: number;
  title: string;
  filename: string;
  page_count: number;
  last_page: number;
  subject: string | null;
  last_opened: string;
  // `documents.created_at` : date du PREMIER import, inchangée à la ré-ouverture.
  imported_at: string;
  // "code" = document servi en blocs (lecteur texte), sinon PDF rendu en image.
  extraction_engine?: string | null;
  // Rangement et classification automatique (schéma v26). Miroir exact de
  // services/library._summary : ce dict EST le contrat d'API du document.
  folder_id: number | null;
  summary: string;
  keywords: string[];
  // "none" (jamais tenté) | "pending" (fiche en cours) | "done" | "failed".
  digest_status: string;
}

/** Nœud de l'arbre de dossiers de la bibliothèque. */
export interface FolderNode {
  id: number;
  name: string;
  parent_id: number | null;
  position: number;
  /** Documents directement dans ce dossier. */
  doc_count: number;
  /** Documents du sous-arbre — ce qu'affiche une ligne repliée. */
  total_count: number;
  children: FolderNode[];
}

/** Bloc de contenu d'une page servie en blocs. */
export interface ReaderBlock {
  id: string;
  type: "heading" | "paragraph" | "formula" | "figure" | "table" | "remark" | "code";
  page: number;
  reading_order: number;
  text?: string;
  latex?: string;
  markdown?: string;
  level?: number;
  image_name?: string;
  asset_name?: string;
  bbox?: number[];
  metadata: {
    reader_hidden?: boolean;
    contains_inline_math?: boolean;
    is_caption?: boolean;
    [key: string]: unknown;
  };
}

export interface Flashcard {
  id: number;
  front: string;
  back: string;
  tags: string[];
  difficulty: number;
  source: string;
  document_title: string | null;
  chapter_title: string | null;
}

export interface Chapter {
  title: string;
  [key: string]: unknown;
}

export interface DocumentDetail extends DocumentSummary {
  page_sizes_pts: [number, number][];
  chapters: Chapter[];
}

export interface QuizQuestion {
  id: number;
  question: string;
  choices: string[] | null;
  answer: string;
  category: string;
  document?: string | null;
  document_id?: number | null;
  chapter_title?: string | null;
  source: string;
}

// Matière disponible pour le quiz (avec son effectif de questions stockées).
export interface QuizSubject {
  subject: string;
  count: number;
}

// Cours recommandé en fin de session (document à relire pour se renforcer).
export interface QuizCourse {
  title: string;
  subject: string;
  reason: string;
  document: string;
  chapter_title: string;
  document_id: number | null;
}

// Analyse LLM de fin de session de quiz + conseils de cours.
export interface QuizAnalysis {
  analysis: string;
  weak_subjects: string[];
  courses_to_review: QuizCourse[];
}

// Entrée d'historique d'une réponse de quiz (envoyée à l'analyse de fin de session).
export interface QuizAnswerRecord {
  question: string;
  user_answer: string;
  verdict: "correct" | "incorrect";
  score: number;
  category: string;
  source: string;
  document: string | null;
  document_id: number | null;
  chapter_title: string | null;
}

export interface Highlight {
  quote?: string;
  text?: string;
  purpose?: "key" | "explain" | "reference";
}

/** Ancrage texte d'un surlignage sur une page servie en blocs. */
export interface HighlightAnchor {
  block_id: string;
  start: number;
  end: number;
}

// Surlignage persistant (mémorisé en base, rechargé à l'ouverture du PDF).
export interface SavedHighlight {
  id: number;
  page: number;
  quote: string;
  rects: number[][];
  color: "key" | "explain" | "reference";
  // Présent pour les documents reconstruits (rects vides dans ce cas).
  anchor?: HighlightAnchor | null;
}

// Mot du calque de texte : [x0, y0, x1, y1, "mot"] en points PDF.
export type PageWord = [number, number, number, number, string];

export interface SessionMetrics {
  session_id: number;
  duration_s: number;
  pages_read: number;
  questions_answered: number;
  correct: number;
  success_rate: number;
  reflection_questions: string[];
}
