/** Libellé traduit d'un critère du profil (`crit.<clé>`) ; la clé brute si
 *  le critère est inconnu des dictionnaires. */
export function criterionLabel(t: (key: string) => string, key: string): string {
  const label = t(`crit.${key}`);
  return label === `crit.${key}` ? key : label;
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
