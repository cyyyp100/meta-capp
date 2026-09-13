// demoScript.ts — Le contenu de la fausse séance de lecture de la visite.
//
// La visite guidée doit montrer Gemma en train de travailler. Deux façons de le
// faire : lancer une VRAIE session, ou en jouer une écrite d'avance. C'est la
// seconde qui est retenue, et pas par facilité :
//
//   * une vraie session écrit — `reading_sessions`, `session_gauges`, `answers`,
//     `page_dwell` — puis nourrit le profil métacognitif à la finalisation. On
//     ne veut RIEN de tout ça : la séance de démonstration ne doit pas compter.
//     Un drapeau « ne compte pas » à respecter dans chaque écriture finirait par
//     être oublié quelque part ; ne rien appeler du tout ne s'oublie pas.
//   * une vraie session dépend d'Ollama. Au premier lancement, Ollama est
//     souvent absent ou froid : la visite montrerait des points de suspension
//     pendant quinze secondes, ou une erreur. Ici tout est instantané.
//   * une vraie réponse de LLM n'est pas prévisible. On ne peut pas construire
//     une explication autour d'un texte qu'on ne connaît pas.
//
// Conséquence à tenir : le chapitre lecture n'ouvre pas le WebSocket et n'appelle
// aucune route `/api/session/*`. C'est vérifiable d'un coup d'œil à l'onglet
// réseau, et c'est ce qui garantit la promesse faite à l'utilisateur.
import type { SessionMetrics } from "../../api/types";

/** Un temps de la démonstration, déclenché par une étape de la visite. */
export type DemoBeat = "answer" | "intervention" | "question";

/**
 * Les phrases que Gemma « surligne » dans la page.
 *
 * Elles doivent exister MOT POUR MOT dans la première page du PDF de
 * démonstration (`nwol/resources/`), sans quoi `api.searchPage` ne trouve rien
 * et il ne se passe simplement rien de visible — la visite continue, sans
 * surlignage. C'est la dégradation voulue : une ressource remplacée ne doit pas
 * casser le tutoriel.
 *
 * Après avoir déposé un nouveau PDF, recopier ici deux phrases de sa page 1.
 */
export const DEMO_QUOTES = {
  key: "It executes program instructions and performs the necessary calculations.",
  explain: "The processor takes instructions in the form of machine code from the OS (binary) and executes them sequentially.",
} as const;

/**
 * Les deux cartes du warm-up de démonstration.
 *
 * De la connaissance générale, et non le contenu du PDF : une carte de warm-up
 * porte sur ce qu'on sait DÉJÀ, et celle-ci doit se répondre sans avoir rien lu
 * du document, sinon la démonstration met en échec la première personne qui la
 * voit. Ce sont des clés i18n, résolues à l'affichage comme le reste.
 *
 * Les identifiants sont négatifs : aucune ligne de `flashcards` ne peut porter
 * ces valeurs, donc aucune révision ne peut être écrite par erreur sur une vraie
 * carte. `WarmUp` n'appelle de toute façon pas la route de révision en
 * démonstration, mais les deux verrous ne coûtent rien.
 */
export const DEMO_CARDS = [
  { id: -1, frontKey: "demo.card_1_front", backKey: "demo.card_1_back" },
  { id: -2, frontKey: "demo.card_2_front", backKey: "demo.card_2_back" },
] as const;

/** Ce que la fausse séance affiche dans le sas de sortie.
 *
 *  Des chiffres plausibles et modestes : le sas doit ressembler à ce qu'on
 *  obtient après quelques minutes de lecture, pas à une performance. Les
 *  intitulés des questions de réflexion sont des clés i18n, résolues à
 *  l'affichage comme le reste. */
export const DEMO_METRICS: SessionMetrics = {
  // `-1` : aucune session n'existe côté serveur. Toute tentative de
  // finalisation avec cet id échouerait — c'est voulu, elle n'a pas lieu.
  session_id: -1,
  duration_s: 512,
  pages_read: 3,
  questions_answered: 2,
  correct: 2,
  success_rate: 75,
  reflection_questions: [],
};

/** Les clés i18n des questions de réflexion du sas de sortie de démonstration. */
export const DEMO_REFLECTION_KEYS = ["demo.reflect_1", "demo.reflect_2", "demo.reflect_3"];

/** La question posée dans la carte de quiz. On la MONTRE : elle n'est jamais
 *  envoyée à l'évaluateur, et le verdict ci-dessous est écrit d'avance. */
export const DEMO_QUESTION = {
  questionKey: "demo.qa_question",
  type: "mcq",
  choiceKeys: ["demo.qa_choice_1", "demo.qa_choice_2", "demo.qa_choice_3"],
  verdict: "correct",
  feedbackKey: "demo.qa_feedback",
} as const;

/** Temps de « réflexion » simulé (ms) avant qu'une réplique de Gemma n'arrive.
 *
 *  Il couvre le changement d'étape de la visite — sortie de la bulle quittée
 *  puis entrée de la suivante, cf. `tour/Coachmark.tsx` — avec de la marge : la
 *  réponse doit tomber une fois la bulle qui l'explique posée et lisible, pas
 *  au milieu de son apparition. C'était 700 ms, et elle arrivait en plein fondu. */
export const DEMO_THINKING_MS = 1400;

/** Les répliques jouées, dans l'ordre où les étapes les déclenchent. */
export const DEMO_BEATS: Record<DemoBeat, { userKey?: string; assistantKey?: string }> = {
  // L'utilisateur pose une question, Gemma répond en citant la page.
  answer: { userKey: "demo.ask", assistantKey: "demo.answer" },
  // Personne n'a rien demandé : c'est le moment où le produit se montre.
  intervention: { assistantKey: "demo.intervention" },
  // La question arrive dans la carte dédiée, pas dans le fil.
  question: {},
};
