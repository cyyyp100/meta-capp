// useTour.ts — La visite guidée du premier lancement.
//
// Aucun onboarding n'existait : le premier écran était une bibliothèque vide.
// Le problème que ça pose n'est pas d'ergonomie, il est commercial — personne
// ne paie pour quelque chose qu'il n'a pas vu faire.
//
// Forme retenue : des bulles ANCRÉES sur les vrais boutons, dans l'écran réel,
// pendant que l'utilisateur peut agir. Pas de vidéo, pas de carrousel plein
// écran — on montre l'application, pas une brochure.
//
// La séquence n'est PAS jouée d'affilée : chaque étape attend son contexte.
// La bulle « Gemma » ne peut se montrer que dans le lecteur, celle du sas de
// sortie qu'à la fin d'une session. Un composant signale « mon contexte vient
// d'apparaître » via `request()`, et le store décide si c'est le tour de
// celle-là. C'est ce qui permet de déclencher les étapes 2 à 4 sur le PREMIER
// document importé par l'utilisateur, plutôt que d'embarquer un PDF d'exemple :
// on découvre Gemma sur son propre contenu, ce qui est bien plus convaincant.
import { create } from "zustand";

import { api } from "@/api/client";

export type TourStep = "import" | "gemma" | "intervention" | "exit" | "profil";

/** L'ordre du RÉCIT, pas celui de la navigation. Il ne force pas un passage
 *  obligé : il ne sert qu'à ne jamais revenir en arrière. Quelqu'un qui va droit
 *  au profil sans rien importer verra la bulle du radar — et pas ensuite celle
 *  de l'import, qui n'aurait plus rien à raconter. */
export const TOUR_ORDER: TourStep[] = ["import", "gemma", "intervention", "exit", "profil"];

interface TourState {
  /** `true` = terminée ou refusée. On n'y revient plus sans demande explicite. */
  done: boolean;
  /** Étape la plus avancée déjà montrée (`null` = aucune). */
  furthest: TourStep | null;
  /** Étape actuellement affichée. */
  active: TourStep | null;
  /** Le store n'a pas encore lu l'état serveur : on n'affiche rien avant. */
  hydrated: boolean;

  hydrate: (done: boolean, furthest: TourStep | null) => void;
  request: (step: TourStep) => void;
  dismiss: () => void;
  release: () => void;
  skip: () => void;
}

function indexOf(step: TourStep | null): number {
  return step === null ? -1 : TOUR_ORDER.indexOf(step);
}

export const useTour = create<TourState>((set, get) => ({
  done: false,
  furthest: null,
  active: null,
  hydrated: false,

  hydrate: (done, furthest) => set({ done, furthest, hydrated: true }),

  request: (step) => {
    const { done, hydrated, furthest, active } = get();
    // Rien tant qu'on ne sait pas si la visite a déjà eu lieu : afficher une
    // bulle puis la retirer une frame plus tard serait pire que de ne rien faire.
    if (!hydrated || done || active !== null) return;
    // Déjà vue : on ne la rejoue pas. Une étape qu'on a sautée dans le récit
    // (on ouvre le lecteur avant d'avoir vu la bulle d'import) reste jouable —
    // c'est le contexte qui commande, pas un compteur.
    if (indexOf(step) <= indexOf(furthest)) return;
    set({ active: step });
  },

  dismiss: () => {
    const { active } = get();
    if (active === null) return;
    const last = TOUR_ORDER[TOUR_ORDER.length - 1];
    const done = active === last;
    set({ active: null, furthest: active, done });
    void api
      .setPreferences(done ? { tour_step: active, tour_done: true } : { tour_step: active })
      .catch(() => undefined);
  },

  // Cible introuvable ou disparue (le panneau Gemma remplace la bulle quand on
  // l'ouvre). Sans ce relâchement, l'étape restait `active` sans rien afficher,
  // et `request()` refusait toutes les suivantes : la visite se bloquait en
  // silence, sur un écran parfaitement normal.
  //
  // On NE marque PAS l'étape comme vue : elle se rejouera quand son contexte
  // reviendra, ce qui est exactement ce qu'on veut d'une visite pilotée par le
  // contexte plutôt que par un compteur.
  release: () => set({ active: null }),

  skip: () => {
    set({ active: null, done: true });
    void api.setPreferences({ tour_done: true }).catch(() => undefined);
  },
}));

/** Convertit la préférence stockée en étape. Une valeur inconnue vaut « aucune ». */
export function toStep(value: string | undefined): TourStep | null {
  return TOUR_ORDER.includes(value as TourStep) ? (value as TourStep) : null;
}
