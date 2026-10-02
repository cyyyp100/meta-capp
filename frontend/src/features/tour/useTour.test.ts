// Le moteur de la visite guidée.
//
// Ce que ces tests verrouillent n'est pas l'enchaînement des bulles — un script
// se relit — mais les deux promesses faites à l'utilisateur, celles qui se
// cassent en silence si personne ne les surveille :
//
//   1. le document de démonstration est TOUJOURS rendu, quelle que soit la
//      façon dont la visite se termine (au bout, ou abandonnée en son milieu) ;
//   2. une visite sans document jouable saute son chapitre lecture d'un bloc
//      au lieu de s'arrêter sur une bulle qui ne s'ancrera jamais.
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/api/client";
import { queryClient } from "@/api/queryClient";
import { NAV } from "@/components/AppLayout";

import { TOUR_STEPS } from "./steps";
import { useTour } from "./useTour";

vi.mock("@/api/client", () => ({
  api: {
    borrowDemoDocument: vi.fn(),
    returnDemoDocument: vi.fn(),
    setPreferences: vi.fn(),
  },
}));

const borrow = vi.mocked(api.borrowDemoDocument);
const giveBack = vi.mocked(api.returnDemoDocument);
const setPreferences = vi.mocked(api.setPreferences);
const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);

/** Avance jusqu'à l'étape portant cet identifiant (bornes de sécurité). */
function advanceTo(id: string) {
  for (let guard = 0; guard < TOUR_STEPS.length + 1; guard++) {
    if (TOUR_STEPS[useTour.getState().index]?.id === id) return;
    useTour.getState().next();
  }
  throw new Error(`Étape « ${id} » jamais atteinte`);
}

beforeEach(() => {
  vi.clearAllMocks();
  borrow.mockResolvedValue({ document: { id: 42 } as never });
  giveBack.mockResolvedValue({ ok: true });
  setPreferences.mockResolvedValue({ preferences: {} as never });
  useTour.setState({ running: false, index: 0, demoDocId: null, hydrated: false, done: false, controls: null });
});

describe("démarrage", () => {
  it("emprunte le document avant d'afficher la première bulle", async () => {
    await useTour.getState().start();
    // La deuxième étape montre la bibliothèque : le document doit déjà y être.
    expect(borrow).toHaveBeenCalledOnce();
    expect(useTour.getState()).toMatchObject({ running: true, index: 0, demoDocId: 42 });
  });

  it("démarre quand même si la ressource manque", async () => {
    borrow.mockResolvedValue({ document: null });
    await useTour.getState().start();
    expect(useTour.getState()).toMatchObject({ running: true, demoDocId: null });
  });

  it("démarre quand même si le serveur refuse", async () => {
    borrow.mockRejectedValue(new Error("500"));
    await useTour.getState().start();
    expect(useTour.getState().running).toBe(true);
  });
});

describe("le document emprunté est toujours rendu", () => {
  it("en quittant le chapitre lecture, et pas seulement à la fin", async () => {
    await useTour.getState().start();
    advanceTo("rest-sas");
    expect(giveBack).not.toHaveBeenCalled();

    useTour.getState().next(); // rest-sas -> profil : on sort du lecteur
    expect(giveBack).toHaveBeenCalledOnce();
    // La bibliothèque doit être vide quand la dernière bulle y ramène.
    expect(useTour.getState().demoDocId).toBeNull();
  });

  it("quand on abandonne la visite en son milieu", async () => {
    await useTour.getState().start();
    advanceTo("clikoda-panel");
    useTour.getState().skip();

    expect(giveBack).toHaveBeenCalledOnce();
    expect(useTour.getState()).toMatchObject({ running: false, done: true, demoDocId: null });
    expect(setPreferences).toHaveBeenCalledWith({ tour_done: true });
  });

  it("quand on va jusqu'au bout", async () => {
    await useTour.getState().start();
    for (let i = 0; i < TOUR_STEPS.length; i++) useTour.getState().next();

    expect(useTour.getState()).toMatchObject({ running: false, done: true });
    expect(setPreferences).toHaveBeenLastCalledWith({ tour_done: true });
    // Une fois en sortant du lecteur, une fois à la clôture : jamais zéro.
    expect(giveBack.mock.calls.length).toBeGreaterThanOrEqual(1);
  });
});

describe("la bibliothèque suit le document emprunté", () => {
  // Troisième promesse : la carte de démonstration est VISIBLE pendant qu'on la
  // commente. L'emprunt et la restitution ont lieu hors de l'arbre React ; sans
  // invalidation, la grille garde la liste qu'elle a chargée en montant et la
  // carte n'apparaît jamais — l'étape qui la désigne cherche alors une ancre
  // qui n'existe pas.
  it("invalide le cache dès l'emprunt", async () => {
    await useTour.getState().start();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["library"] });
  });

  it("et à la restitution, une fois le serveur passé", async () => {
    await useTour.getState().start();
    invalidate.mockClear();

    useTour.getState().skip();
    // Invalider avant la fin du DELETE ferait recharger la grille pendant que
    // le serveur efface encore : elle réafficherait le document rendu.
    expect(invalidate).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["library"] }));
  });

  it("retire la carte de la grille sans attendre le serveur", async () => {
    // Abandonner la visite ramène à l'accueil tout de suite : la grille ne doit
    // pas s'y peindre avec la liste en cache, qui contient encore la démo.
    await useTour.getState().start();
    queryClient.setQueryData(["library", "documents"], [{ id: 42 }, { id: 7 }]);
    giveBack.mockReturnValue(new Promise(() => {})); // le DELETE n'aboutit jamais

    useTour.getState().skip();
    expect(queryClient.getQueryData(["library", "documents"])).toEqual([{ id: 7 }]);
  });

  it("ne recharge rien quand il n'y a eu aucun emprunt", async () => {
    borrow.mockResolvedValue({ document: null });
    await useTour.getState().start();
    expect(invalidate).not.toHaveBeenCalled();
  });
});

describe("sans document jouable", () => {
  it("saute tout le chapitre lecture d'un bloc", async () => {
    borrow.mockResolvedValue({ document: null });
    await useTour.getState().start();

    const seen: string[] = [];
    for (let i = 0; i < TOUR_STEPS.length; i++) {
      const step = TOUR_STEPS[useTour.getState().index];
      if (!useTour.getState().running) break;
      seen.push(step.id);
      useTour.getState().next();
    }

    // Aucune étape ayant besoin du document n'a été présentée : elles se
    // seraient ancrées sur des cibles qui n'existent pas.
    const demoSteps = TOUR_STEPS.filter((s) => s.needsDemo).map((s) => s.id);
    expect(seen.filter((id) => demoSteps.includes(id))).toEqual([]);
    // Et le reste de la visite a bien été joué.
    expect(seen).toContain("welcome");
    expect(seen).toContain("profil");
    expect(seen).toContain("done");
  });
});

describe("le script lui-même", () => {
  it("ne référence que des identifiants uniques", () => {
    const ids = TOUR_STEPS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("couvre toutes les pages principales", () => {
    // La demande était explicite : chaque écran de la barre latérale doit être
    // présenté. Une route ajoutée sans étape doit faire tomber ce test.
    const routes = TOUR_STEPS.map((s) => s.route);
    for (const route of ["/", "/stats", "/stats/progress", "/flashcards", "/quiz", "/lang", "/brainstorming", "/settings"]) {
      expect(routes).toContain(route);
    }
  });

  it("n'ouvre le chapitre lecture qu'après avoir présenté la bibliothèque", () => {
    const firstReading = TOUR_STEPS.findIndex((s) => s.chapter === "reading");
    const lastLibrary = TOUR_STEPS.map((s) => s.chapter).lastIndexOf("library");
    expect(lastLibrary).toBeLessThan(firstReading);
  });

  it("vise des entrées de navigation qui existent vraiment", () => {
    // Les ancres `nav-*` sont déclarées DEUX fois : ici comme cible d'étape, et
    // dans la table `NAV` de la barre latérale qui les pose sur le DOM. Rien ne
    // relie les deux à la compilation, et une bulle qui vise une ancre absente
    // se contente de passer son tour — en silence. D'où ce test.
    const posed = new Set(NAV.map((item) => item.tour));
    const aimed = TOUR_STEPS.map((s) => s.target).filter((t) => t.startsWith("nav-"));
    for (const target of aimed) {
      // `nav-settings` vit sur le menu utilisateur, pas dans le rail.
      if (target === "nav-settings") continue;
      expect(posed).toContain(target);
    }
  });

  it("mène à la route que l'entrée de navigation visée ouvre", () => {
    // Une étape qui montre « Quiz » en étant restée sur /flashcards désigne le
    // bon bouton au mauvais moment.
    for (const step of TOUR_STEPS) {
      const item = NAV.find((n) => n.tour === step.target);
      if (item) expect(step.route).toBe(item.to);
    }
  });
});
