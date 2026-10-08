// useUpcomingEpisodes — L'épisode suivant de chaque langue ouverte.
//
// Une requête, une clé, deux lecteurs : l'annonce « épisode prêt », montée sur
// toutes les pages (EpisodeReadyHost), qui l'interroge ; les pastilles de la
// page Langues, qui lisent le même cache. Un épisode peut partir s'écrire sans
// que le front le déclenche (au démarrage, à l'étape « leçon » d'une séance) :
// on interroge donc toujours, souvent tant qu'un épisode s'écrit, rarement sinon.
import { useQuery } from "@tanstack/react-query";

import { api } from "../../../api/client";
import type { UpcomingEpisode } from "../../../api/feuilleton";

export const UPCOMING_KEY = ["lang", "upcoming"] as const;
/** Un épisode s'écrit : son passage à « prêt » s'annonce dans les secondes qui suivent. */
export const UPCOMING_POLL_WRITING_MS = 5000;
/** Rien ne s'écrit : de quoi voir partir une écriture lancée ailleurs (une écriture dure des minutes). */
export const UPCOMING_POLL_IDLE_MS = 30000;

export function upcomingPollMs(data: UpcomingEpisode[] | undefined): number {
  const writing = data?.some((e) => e.generating || e.status === "generating");
  return writing ? UPCOMING_POLL_WRITING_MS : UPCOMING_POLL_IDLE_MS;
}

/** L'interrogation périodique : l'hôte de l'annonce, seul, la porte. */
export function usePolledUpcomingEpisodes() {
  return useQuery({
    queryKey: UPCOMING_KEY,
    queryFn: api.feuilletonUpcoming,
    refetchInterval: (q) => upcomingPollMs(q.state.data),
  });
}

/** Lecture du même cache (relue au montage) : la page Langues. */
export function useUpcomingEpisodes() {
  return useQuery({ queryKey: UPCOMING_KEY, queryFn: api.feuilletonUpcoming });
}
