// features/questions/registry.ts — Miroir côté UI du registre canonique
// `nwol/config/question_types.py`.
//
// Le backend décide QUOI demander (types, jauges, poids) ; ce fichier décide
// COMMENT le présenter : icône, libellé, famille de couleur, widget de réponse.
// Les deux jeux de clés doivent coïncider — `nwol/tests/test_question_types.py`
// lit ce fichier et échoue si l'un des deux dérive.

import {
  ArrowUpDown,
  BookOpenText,
  Brain,
  Calculator,
  EyeOff,
  GraduationCap,
  Link2,
  ListChecks,
  PenLine,
  Ruler,
  ScanSearch,
  Shapes,
  Sparkles,
  Split,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

export const QUESTION_TYPES = [
  "qcm",
  "open",
  "comprehension",
  "application",
  "curiosity",
  "visualization",
  "metacognition",
  "anticipation",
  "recall",
  "error_detection",
  "ordering",
  "teach_back",
  "elaboration_why",
  "connection",
  "counterexample",
  "estimation",
] as const;

export type QuestionType = (typeof QUESTION_TYPES)[number];

/** Widget de saisie de la réponse. */
export type AnswerWidget = "choices" | "text" | "ordering";

/**
 * Famille du type, qui donne sa couleur au badge. Trois familles suffisent à
 * situer l'effort demandé sans transformer la carte en nuancier — et aucune
 * n'emprunte le vert/rouge, réservés au verdict.
 */
export type QuestionTone = "knowledge" | "production" | "reflexive";

export interface QuestionTypeMeta {
  icon: LucideIcon;
  /** Clé i18n du libellé affiché dans le badge. */
  labelKey: string;
  /** Clé i18n de la consigne courte (placeholder / aide sous l'énoncé). */
  hintKey: string;
  tone: QuestionTone;
  widget: AnswerWidget;
}

export const QUESTION_TYPE_META: Record<QuestionType, QuestionTypeMeta> = {
  qcm: { icon: ListChecks, labelKey: "qtype.qcm", hintKey: "qtype.qcm.hint", tone: "knowledge", widget: "choices" },
  open: { icon: PenLine, labelKey: "qtype.open", hintKey: "qtype.open.hint", tone: "production", widget: "text" },
  comprehension: { icon: BookOpenText, labelKey: "qtype.comprehension", hintKey: "qtype.comprehension.hint", tone: "knowledge", widget: "text" },
  application: { icon: Calculator, labelKey: "qtype.application", hintKey: "qtype.application.hint", tone: "knowledge", widget: "text" },
  curiosity: { icon: Sparkles, labelKey: "qtype.curiosity", hintKey: "qtype.curiosity.hint", tone: "production", widget: "text" },
  visualization: { icon: Shapes, labelKey: "qtype.visualization", hintKey: "qtype.visualization.hint", tone: "production", widget: "text" },
  metacognition: { icon: Brain, labelKey: "qtype.metacognition", hintKey: "qtype.metacognition.hint", tone: "reflexive", widget: "text" },
  anticipation: { icon: TriangleAlert, labelKey: "qtype.anticipation", hintKey: "qtype.anticipation.hint", tone: "reflexive", widget: "text" },
  recall: { icon: EyeOff, labelKey: "qtype.recall", hintKey: "qtype.recall.hint", tone: "knowledge", widget: "text" },
  error_detection: { icon: ScanSearch, labelKey: "qtype.error_detection", hintKey: "qtype.error_detection.hint", tone: "knowledge", widget: "text" },
  ordering: { icon: ArrowUpDown, labelKey: "qtype.ordering", hintKey: "qtype.ordering.hint", tone: "knowledge", widget: "ordering" },
  teach_back: { icon: GraduationCap, labelKey: "qtype.teach_back", hintKey: "qtype.teach_back.hint", tone: "production", widget: "text" },
  elaboration_why: { icon: Split, labelKey: "qtype.elaboration_why", hintKey: "qtype.elaboration_why.hint", tone: "production", widget: "text" },
  connection: { icon: Link2, labelKey: "qtype.connection", hintKey: "qtype.connection.hint", tone: "reflexive", widget: "text" },
  counterexample: { icon: Split, labelKey: "qtype.counterexample", hintKey: "qtype.counterexample.hint", tone: "production", widget: "text" },
  estimation: { icon: Ruler, labelKey: "qtype.estimation", hintKey: "qtype.estimation.hint", tone: "knowledge", widget: "choices" },
};

/** Fond/texte du badge, par famille. */
export const TONE_CLASS: Record<QuestionTone, string> = {
  knowledge: "bg-brand-soft text-accent-foreground",
  production: "bg-warning-soft text-warning",
  reflexive: "bg-surface-soft text-muted-foreground border border-border",
};

export function isQuestionType(value: unknown): value is QuestionType {
  return typeof value === "string" && (QUESTION_TYPES as readonly string[]).includes(value);
}

/** Type sûr : les questions d'avant la grille typée retombent sur "open". */
export function toQuestionType(value: unknown): QuestionType {
  return isQuestionType(value) ? value : "open";
}

export function questionTypeMeta(value: unknown): QuestionTypeMeta {
  return QUESTION_TYPE_META[toQuestionType(value)];
}

/**
 * Widget réellement affiché.
 *
 * La remise en ordre l'emporte toujours (ses `choices` sont les étapes, pas des
 * propositions). Sinon, des choix présents font un QCM — c'est le cas quand le
 * quiz a fabriqué des distracteurs autour d'une question ouverte. Faute de
 * choix, on saisit du texte.
 */
export function answerWidget(type: unknown, choices: string[] | null | undefined): AnswerWidget {
  const meta = questionTypeMeta(type);
  if (meta.widget === "ordering") return "ordering";
  return choices && choices.length > 0 ? "choices" : "text";
}
