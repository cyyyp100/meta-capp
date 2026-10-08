// EpisodeReadyHost — « Anglais : l'épisode 3 est prêt », quelle que soit la page.
//
// Un épisode s'écrit en tâche de fond pendant plusieurs minutes (au démarrage,
// à l'étape « leçon » de la séance précédente, à l'ouverture de l'accueil
// d'une langue) : quand il passe prêt, un petit message le dit en bas à droite,
// avec son numéro et sa langue. Monté au-dessus des routes (App.tsx), comme la
// visite guidée : le lecteur et la séance de langue sont hors du layout.
//
// Seul un PASSAGE à « prêt » s'annonce : un épisode déjà prêt au premier relevé
// n'est pas « tout juste » prêt, et un même relevé ne s'annonce qu'une fois.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { api } from "../../../api/client";
import type { UpcomingEpisode } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { subjectName } from "../../stats/labels";
import { usePolledUpcomingEpisodes } from "./useUpcomingEpisodes";

/** Assez long pour être vu d'un coin de l'œil en lisant un PDF ; il se ferme aussi d'un clic. */
export const READY_TOAST_MS = 12000;

/** Les épisodes passés « prêts » entre deux relevés (aucun au premier relevé). */
export function newlyReady(previous: UpcomingEpisode[] | null, current: UpcomingEpisode[]): UpcomingEpisode[] {
  if (previous === null) return [];
  return current.filter((e) => {
    if (e.status !== "ready") return false;
    const before = previous.find((p) => p.language === e.language);
    return !before || before.episode_n !== e.episode_n || before.status !== "ready";
  });
}

export function EpisodeReadyHost() {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data } = usePolledUpcomingEpisodes();
  const { data: languages } = useQuery({ queryKey: ["lang", "languages"], queryFn: api.languages, staleTime: Infinity });
  const previous = useRef<UpcomingEpisode[] | null>(null);

  useEffect(() => {
    if (!data || data === previous.current) return;
    const ready = newlyReady(previous.current, data);
    previous.current = data;
    for (const e of ready) {
      const flag = languages?.find((l) => l.code === e.language)?.flag;
      toast(t("feuil.ready.toast", { language: subjectName(t, e.language), n: e.episode_n }), {
        id: `episode-ready-${e.language}-${e.episode_n}`,
        // Plus de 3 jours d'absence : il attend derrière une relecture (C7).
        description: t(e.relecture_due ? "feuil.ready.after_relecture" : "feuil.ready.waiting"),
        icon: flag ? <span aria-hidden="true">{flag}</span> : undefined,
        duration: READY_TOAST_MS,
        action: {
          label: t("feuil.ready.open"),
          onClick: () => navigate("/lang", { state: { language: e.language } }),
        },
        actionButtonStyle: { background: "var(--accent)", color: "var(--on-accent)" },
      });
      // L'accueil de cette langue, s'il est ouvert, passe à « Épisode N » sans attendre.
      void queryClient.invalidateQueries({ queryKey: ["feuil", "status", e.language] });
    }
  }, [data, languages, navigate, queryClient, t]);

  return null;
}
