// useTour.ts — Le moteur de la visite guidée du premier lancement.
//
// Aucun onboarding n'existait : le premier écran était une bibliothèque vide.
// Le problème que ça pose n'est pas d'ergonomie, il est commercial — personne
// ne paie pour quelque chose qu'il n'a pas vu faire.
//
// Forme retenue : des bulles ANCRÉES sur les vrais boutons, dans l'écran réel,
// le bouton en clair et tout le reste assombri. Pas de vidéo, pas de carrousel
// plein écran — on montre l'application, pas une brochure.
//
// La visite fut d'abord OPPORTUNISTE : cinq bulles qui attendaient que leur
// contexte apparaisse de lui-même, sur le premier document de l'utilisateur.
// L'idée était jolie et le résultat vide : qui n'importait rien ne voyait ni
// Clikoda, ni les sas, ni le profil. Elle est maintenant SCRIPTÉE — elle emprunte
// un document de démonstration, navigue elle-même d'écran en écran et joue une
// fausse séance de lecture. L'utilisateur n'a qu'à lire et cliquer « Suivant ».
//
// « Fausse séance » au sens fort, et c'est la garantie qui compte : le chapitre
// lecture n'appelle NI `/api/session/*`, NI le WebSocket du lecteur, NI Ollama
// (cf. `features/reader/demoScript.ts`). Rien n'atteint donc le profil
// métacognitif — par construction, et non par un drapeau qu'il faudrait penser
// à respecter dans chacune des écritures.
import { create } from "zustand";

import { api } from "@/api/client";
import { queryClient } from "@/api/queryClient";
import type { DocumentSummary } from "@/api/types";

import { DEMO_ROUTE, TOUR_STEPS, type TourStepDef } from "./steps";

/** Ce que la visite sait piloter dans le lecteur, branché par `Reader`. */
export interface DemoControls {
  /** Franchit le sas d'entrée : il recouvre la page qu'on veut ensuite montrer. */
  enterReading: () => void;
  /** Cale la vue sur le passage que Clikoda va citer, avant de la figer. */
  pinPassage: () => void;
  openPanel: () => void;
  play: (beat: "answer" | "intervention" | "question") => void;
  endSession: () => void;
  closeExitSas: () => void;
}

export interface TourContext {
  demo: DemoControls | null;
}

interface TourState {
  /** La visite est en cours : une bulle est (ou va être) à l'écran. */
  running: boolean;
  /** Index dans `TOUR_STEPS`. */
  index: number;
  /** Le document emprunté, `null` si la ressource manque. */
  demoDocId: number | null;
  /** Tant qu'on ignore si la visite a déjà eu lieu, on n'affiche rien. */
  hydrated: boolean;
  /** `true` = terminée ou refusée ; on n'y revient plus sans demande explicite. */
  done: boolean;
  /** Branché par le lecteur pendant qu'il est monté. */
  controls: DemoControls | null;

  hydrate: (done: boolean) => void;
  setControls: (controls: DemoControls | null) => void;
  start: () => Promise<void>;
  next: () => void;
  skip: () => void;
}

/** L'étape courante, ou `null` si la visite ne tourne pas. */
export function currentStep(state: TourState): TourStepDef | null {
  if (!state.running) return null;
  return TOUR_STEPS[state.index] ?? null;
}

/** La route d'une étape, l'id du document de démo substitué. */
export function resolveRoute(step: TourStepDef, demoDocId: number | null): string | undefined {
  if (!step.route) return undefined;
  if (step.route !== DEMO_ROUTE) return step.route;
  return demoDocId === null ? undefined : `/reader/${demoDocId}`;
}

/** La bibliothèque vient de changer sans que React Query l'ait demandé.
 *
 *  L'emprunt et la restitution du document de démonstration passent par ce
 *  store, hors de l'arbre React : le cache de la grille ne pouvait pas le
 *  savoir. Comme `refetchOnWindowFocus` est désactivé (fenêtre native), la
 *  liste chargée au montage de l'accueil ne bougeait plus de la visite — la
 *  carte de démonstration n'apparaissait donc jamais, l'étape qui la commente
 *  ne trouvait pas son ancre, et la dernière bulle annonçait une bibliothèque
 *  vidée d'un document qui y était encore affiché. */
function refreshLibrary(): void {
  void queryClient.invalidateQueries({ queryKey: ["library"] });
}

/** Rend le document emprunté. Best-effort : un échec ne bloque jamais la visite,
 *  le serveur le nettoiera de toute façon au prochain démarrage.
 *
 *  L'invalidation attend la fin de la requête : lancée avant, la grille se
 *  rechargerait pendant que le serveur efface encore, et réafficherait le
 *  document qu'on vient de rendre.
 *
 *  La carte, elle, quitte la grille TOUT DE SUITE. Abandonner la visite ramène
 *  à l'accueil sans attendre le serveur, et l'accueil se peindrait d'abord avec
 *  la liste en cache — celle qui contient encore le document qu'on vient de
 *  rendre. */
function returnDemoDocument(docId: number | null): void {
  if (docId !== null) {
    queryClient.setQueryData<DocumentSummary[]>(["library", "documents"], (docs) =>
      docs?.filter((d) => d.id !== docId),
    );
  }
  void api
    .returnDemoDocument()
    .catch(() => undefined)
    .finally(refreshLibrary);
}

export const useTour = create<TourState>((set, get) => ({
  running: false,
  index: 0,
  demoDocId: null,
  hydrated: false,
  done: false,
  controls: null,

  hydrate: (done) => set({ done, hydrated: true }),

  setControls: (controls) => set({ controls }),

  start: async () => {
    // Emprunter AVANT d'afficher la première bulle : la deuxième étape montre la
    // bibliothèque, et le document doit déjà y être. Le coût est un aller-retour
    // local, invisible.
    let demoDocId: number | null;
    try {
      const { document } = await api.borrowDemoDocument();
      demoDocId = document?.id ?? null;
    } catch {
      // Ressource absente ou serveur grognon : on joue la visite sans son
      // chapitre lecture. Un tutoriel amputé vaut mieux qu'un tutoriel qui
      // s'arrête sur un message d'erreur au premier lancement du produit.
      demoDocId = null;
    }
    set({ running: true, index: 0, demoDocId, done: false, hydrated: true });
    // Le document est en base ; la grille, elle, tient encore la liste d'avant.
    if (demoDocId !== null) refreshLibrary();
    void api.setPreferences({ tour_done: false }).catch(() => undefined);
  },

  next: () => {
    const { index, demoDocId, controls } = get();
    let target = index + 1;

    // Sans document emprunté, tout le chapitre lecture saute d'un bloc.
    if (demoDocId === null) {
      while (target < TOUR_STEPS.length && TOUR_STEPS[target].needsDemo) target += 1;
    }

    if (target >= TOUR_STEPS.length) {
      returnDemoDocument(demoDocId);
      set({ running: false, done: true, demoDocId: null, controls: null });
      void api.setPreferences({ tour_done: true }).catch(() => undefined);
      return;
    }

    // On rend le document en QUITTANT le chapitre lecture, et non à la toute
    // fin : la dernière bulle montre une bibliothèque vide en disant « à toi
    // d'importer le tien », ce qui ne marche que s'il en est déjà sorti.
    //
    // La condition porte sur le CHAPITRE et non sur `needsDemo` : l'étape qui
    // commente la carte du document de démonstration est dans la bibliothèque
    // tout en ayant besoin de lui, et rendait donc le document six étapes trop
    // tôt — emportant avec elle tout le chapitre lecture, désormais injouable.
    if (TOUR_STEPS[index]?.chapter === "reading" && TOUR_STEPS[target].chapter !== "reading") {
      returnDemoDocument(demoDocId);
      set({ demoDocId: null, controls: null });
    }

    set({ index: target });
    // Après le `set` : le `enter` peut vouloir agir sur l'écran de l'étape.
    TOUR_STEPS[target].enter?.({ demo: controls });
  },

  // Le retour à l'accueil n'est pas ici : le store n'a pas de routeur. C'est
  // `TourHost` qui le fait, dès que `running` retombe.
  skip: () => {
    returnDemoDocument(get().demoDocId);
    set({ running: false, done: true, demoDocId: null, controls: null });
    void api.setPreferences({ tour_done: true }).catch(() => undefined);
  },
}));

// Barre de menu native (« Aide ▸ Tutoriel ») et bouton « Revoir le tutoriel »
// des réglages. Le menu vit côté Python : il ne peut pas appeler le store, il
// émet cet événement — même pont que le thème (cf. theme/useTheme.ts).
window.addEventListener("metacapp:tour", () => {
  void useTour.getState().start();
});

export { TOUR_STEPS };
