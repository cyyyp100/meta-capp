import type { Recommendation, TrendCategory } from "../../api/types";

// Libellés FR (le port complet de l'i18n serveur viendra au Plan 07).
export const CRITERION_LABELS: Record<string, string> = {
  attention: "Attention",
  context_comprehension: "Compréhension",
  creativity: "Créativité",
  retention: "Rétention",
  curiosity: "Curiosité",
  meta_cognition: "Métacognition",
};

export const TREND_LABELS: Record<TrendCategory, string> = {
  in_progress: "En progrès",
  to_improve: "À améliorer",
  stable: "Stable",
};

export const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  solid: "Solide",
  progressing: "En progrès",
  to_review: "À revoir",
  to_improve: "À améliorer",
};

export const CRITERION_DESC: Record<string, string> = {
  attention: "Ta capacité à rester concentré et à éviter les distractions pendant la lecture.",
  context_comprehension: "Ta compréhension du sens global et des liens entre les idées.",
  creativity: "Ta capacité à faire des liens originaux et à reformuler avec tes mots.",
  retention: "Ce que tu retiens dans le temps, mesuré via les révisions et réponses.",
  curiosity: "Ton envie d'explorer, de poser des questions et d'approfondir.",
  meta_cognition: "Ta conscience de ta propre façon d'apprendre et de progresser.",
};

export function criterionLabel(key: string): string {
  return CRITERION_LABELS[key] ?? key;
}

// Clé i18n du libellé de chaque matière, par sa clé en base. Miroir du
// vocabulaire nwol/config/subjects.py — disciplines, puis une matière par langue
// (mêmes codes que le module Langues) — vérifié par nwol/tests/test_subjects.py.
export const SUBJECT_I18N_KEYS: Record<string, string> = {
  "mathématiques": "subj.math",
  "physique": "subj.physics",
  "chimie": "subj.chemistry",
  "biologie": "subj.biology",
  "sciences": "subj.science",
  "informatique": "subj.cs",
  "technologie": "subj.technology",
  "histoire": "subj.history",
  "géographie": "subj.geography",
  "français": "subj.french",
  "philosophie": "subj.philosophy",
  "littérature": "subj.literature",
  "économie": "subj.economics",
  "sciences-sociales": "subj.social",
  "droit": "subj.law",
  "gestion": "subj.management",
  "psychologie": "subj.psychology",
  "sociologie": "subj.sociology",
  "arts": "subj.arts",
  "musique": "subj.music",
  "médecine": "subj.medicine",
  "sport": "subj.sport",
  "religion": "subj.religion",
  "culture": "subj.culture",
  "anglais": "subj.english",
  "espagnol": "subj.spanish",
  "allemand": "subj.german",
  "italien": "subj.italian",
  "portugais": "subj.portuguese",
  "néerlandais": "subj.dutch",
  "polonais": "subj.polish",
  "suédois": "subj.swedish",
  "turc": "subj.turkish",
  "roumain": "subj.romanian",
  "indonésien": "subj.indonesian",
  "vietnamien": "subj.vietnamese",
  "russe": "subj.russian",
  "grec": "subj.greek",
  "coréen": "subj.korean",
  "mandarin": "subj.mandarin",
  "japonais": "subj.japanese",
  "arabe": "subj.arabic",
  "hébreu": "subj.hebrew",
  "hindi": "subj.hindi",
  "thaï": "subj.thai",
  // Plus une matière depuis qu'il y en a une par langue (migration v39), mais
  // les quiz joués avant la nomment encore dans « Ma progression ».
  "langues": "subj.languages",
};

/** Libellé traduit d'une matière ; sa clé, capitalisée, si elle est inconnue. */
export function subjectName(t: (key: string) => string, code: string): string {
  const key = SUBJECT_I18N_KEYS[code];
  return key ? t(key) : code.charAt(0).toUpperCase() + code.slice(1);
}

// Couleur selon le score (miroir de score_color côté Tk).
/**
 * Couleur de REMPLISSAGE d'un score : barre de progression, trait de courbe,
 * pastille. Le palier médian est l'orange de la marque — c'est exactement le
 * rôle qu'on lui donne : montrer une progression.
 */
export function scoreColor(value: number): string {
  if (value >= 75) return "var(--success)";
  if (value >= 45) return "var(--accent)";
  return "var(--warning)";
}

/**
 * La même échelle, mais pour ÉCRIRE le score en toutes lettres.
 *
 * Une seule fonction servait aux deux, et le palier médian rendait « 62 » en
 * `--accent` : lisible tant que l'accent était sombre, mais l'orange de marque
 * ne fait que 2,80:1 sur une surface claire. Les deux usages ont des exigences
 * différentes ; ils ont donc deux fonctions, sur la MÊME échelle de paliers —
 * un chiffre et sa barre ne doivent jamais désigner deux paliers différents.
 */
export function scoreInk(value: number): string {
  if (value >= 75) return "var(--success)";
  if (value >= 45) return "var(--accent-ink)";
  return "var(--warning)";
}

export function deltaLabel(delta: number): string {
  if (delta > 2) return `+${Math.round(delta)}`;
  if (delta < -2) return `${Math.round(delta)}`;
  return "Stable";
}
