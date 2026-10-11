// useRunTracker.test.ts — Ce que le client dit de l'attention : des intervalles.
//
// Une page, puis chaque réponse, ouvrent un intervalle ; la réponse suivante ou
// la page suivante le ferment. Il part au serveur avec sa durée et sa part sans
// un geste — et un geste, c'est aussi la souris qui suit le texte ou un
// défilement, pas seulement un clic. Le serveur juge ; ici, on mesure.
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";

import { api } from "../../../api/client";
import type { ActivityConfig, RunEvent } from "../../../api/feuilleton";
import { useRunTracker } from "./useRunTracker";

const ACTIVITY: ActivityConfig = { window_s: 15, min_moves: 5, move_sample_ms: 100 };
const IDLE_CUTOFF_S = 90;

type Pace = Extract<RunEvent, { type: "pace" }>;

const mouse = () => window.dispatchEvent(new Event("pointermove"));
const scroll = () => window.dispatchEvent(new Event("scroll"));
const click = () => window.dispatchEvent(new Event("pointerdown"));

/** Avance l'horloge de `ms`, en faisant `gesture` toutes les `everyMs` s'il y en a un. */
async function elapse(ms: number, gesture?: () => void, everyMs = 200) {
  for (let done = 0; done < ms; ) {
    const slice = gesture ? Math.min(everyMs, ms - done) : ms - done;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(slice);
    });
    done += slice;
    gesture?.();
  }
}

describe("useRunTracker", () => {
  let sent: MockInstance<typeof api.feuilletonEvents>;

  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    sent = vi.spyOn(api, "feuilletonEvents").mockResolvedValue({ ok: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function setup() {
    const { result } = renderHook(() => useRunTracker(7, IDLE_CUTOFF_S, ACTIVITY));
    return () => result.current;
  }

  function batches(): RunEvent[][] {
    return sent.mock.calls.map((call) => call[1]);
  }

  function paces(): Pace[] {
    return batches().flat().filter((e): e is Pace => e.type === "pace");
  }

  function ended(step: string) {
    return batches().flat().find((e) => e.type === "step" && e.step === step && e.ended) as
      | Extract<RunEvent, { type: "step" }>
      | undefined;
  }

  it("lire en suivant le texte à la souris n'est pas de l'inactivité", async () => {
    const tracker = setup();
    await act(async () => void (await tracker().advance(null, "lecture")));
    await elapse(120_000, mouse);
    await act(async () => void (await tracker().advance("lecture", "lecon")));

    expect(paces()).toEqual([expect.objectContaining({ step: "lecture", origin: "open", elapsed_s: 120, idle_s: 0 })]);
    // Et le temps de la page compte en entier : plus de « silence » au-delà du seuil.
    expect(ended("lecture")?.active_s).toBe(120);
  });

  it("faire défiler pour garder le texte à hauteur d'yeux non plus", async () => {
    const tracker = setup();
    await act(async () => void (await tracker().advance(null, "lecture")));
    await elapse(120_000, scroll, 10_000);
    await act(async () => void (await tracker().advance("lecture", "lecon")));

    expect(paces()[0]).toMatchObject({ elapsed_s: 120, idle_s: 0 });
  });

  it("sans un geste, la page n'est active que le temps de la fenêtre", async () => {
    const tracker = setup();
    await act(async () => void (await tracker().advance(null, "lecture")));
    await elapse(120_000);
    await act(async () => void (await tracker().advance("lecture", "lecon")));

    const [pace] = paces();
    expect(pace.elapsed_s).toBe(120);
    expect(pace.idle_s).toBeGreaterThanOrEqual(120 - ACTIVITY.window_s);
    expect(ended("lecture")?.active_s).toBeLessThan(IDLE_CUTOFF_S + 1);
  });

  it("un effleurement de la souris ne passe pas pour une lecture", async () => {
    const tracker = setup();
    await act(async () => void (await tracker().advance(null, "lecture")));
    await elapse(60_000);
    await elapse(ACTIVITY.min_moves * 100, mouse, 120); // moins de `min_moves` échantillons
    await elapse(60_000);
    await act(async () => void (await tracker().advance("lecture", "lecon")));

    expect(paces()[0].idle_s).toBeGreaterThanOrEqual(120 - ACTIVITY.window_s);
  });

  it("chaque réponse ferme un intervalle et ouvre celui de la question suivante", async () => {
    const tracker = setup();
    await act(async () => void (await tracker().advance(null, "jeux")));
    await elapse(20_000, mouse);
    // Une réponse se donne d'un clic : c'est aussi un geste.
    click();
    act(() => tracker().push({ type: "answer", item: "a", given: 1, ms: 20_000 }));
    await elapse(70_000); // devant la deuxième question, sans un geste
    click();
    act(() => tracker().push({ type: "card", card_id: 3, verdict: "correct" }));
    await elapse(5_000, mouse);
    click();
    act(() => tracker().push({ type: "reveal", episode_id: 1, line: 0, token: 0, pass: "lecture" }));
    await act(async () => void (await tracker().advance("jeux", "au_revoir")));

    const [page, between, last] = paces();
    expect(page).toMatchObject({ step: "jeux", origin: "open", elapsed_s: 20, idle_s: 0 });
    expect(between).toMatchObject({ step: "jeux", origin: "answer", elapsed_s: 70 });
    expect(between.idle_s).toBeGreaterThanOrEqual(70 - ACTIVITY.window_s);
    // Un tap sur un mot n'est pas une réponse : le dernier intervalle court jusqu'à la page suivante.
    expect(last).toMatchObject({ step: "jeux", origin: "answer", elapsed_s: 5, idle_s: 0 });
    // L'intervalle part avant la réponse qui le ferme.
    const types = batches().flat().map((e) => e.type);
    expect(types.indexOf("pace")).toBeLessThan(types.indexOf("answer"));
  });

  it("une page qu'on n'a pas tournée n'est pas jugée", async () => {
    const tracker = setup();
    await act(async () => void (await tracker().advance(null, "jeux")));
    await elapse(30_000);
    // Plafond atteint : la séance mène plus loin, la page n'a pas été tournée.
    await act(async () => void (await tracker().advance(null, "au_revoir")));
    await elapse(30_000);
    await act(async () => void (await tracker().flush("au_revoir")));

    expect(paces()).toEqual([]);
  });
});
