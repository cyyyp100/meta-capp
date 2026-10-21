// features/reader/engagement.ts — Ce que l'élève FAIT de sa lecture.
//
// Surligner, annoter : des gestes de lecture active, que la jauge d'attention
// crédite (config/settings.py, ATTENTION_ENGAGEMENT_CREDIT). Ils naissent dans
// le carnet (`useAnnotations`), loin du socket du lecteur que tient le panneau
// de Clikoda : ce canal les y porte, sans faire passer une prop à travers tout
// le lecteur. Le serveur décide seul du crédit et de sa cadence.

export type EngagementAction = "highlight" | "note";

const channel = new EventTarget();
const EVENT = "engage";

/** Un geste vient d'être enregistré (le serveur l'a accepté). */
export function reportEngagement(action: EngagementAction): void {
  channel.dispatchEvent(new CustomEvent<EngagementAction>(EVENT, { detail: action }));
}

/** S'abonne aux gestes ; la fonction rendue désabonne. */
export function onEngagement(listener: (action: EngagementAction) => void): () => void {
  const handler = (event: Event) => listener((event as CustomEvent<EngagementAction>).detail);
  channel.addEventListener(EVENT, handler);
  return () => channel.removeEventListener(EVENT, handler);
}
