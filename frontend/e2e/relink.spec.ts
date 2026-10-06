// relink.spec.ts — « Localiser le fichier » : un document dont le fichier a été
// déplacé se relie EN PLACE depuis sa carte, sans devenir un nouveau document.
//
// Le fichier de travail est une COPIE de la fixture sous `fixtures/.relink/`,
// dans les racines d'import du serveur de test (playwright.config.ts) et hors de
// git. On l'importe, on renomme son dossier — le document devient introuvable —
// puis on le localise à sa nouvelle place avec le sélecteur simulé.

import { copyFileSync, mkdirSync, renameSync, rmSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { stubDesktopFilePicker } from "./filePicker";

const FIXTURE = fileURLToPath(new URL("./fixtures/echantillon.pdf", import.meta.url));
const WORKDIR = fileURLToPath(new URL("./fixtures/.relink", import.meta.url));
const BEFORE = join(WORKDIR, "a");
const AFTER = join(WORKDIR, "b");
const LATER = join(WORKDIR, "c");
// Un nom à lui : la carte ne se confond pas avec celle de `echantillon.pdf`,
// que reader.spec.ts importe dans la même base.
const NAME = "relink-echantillon.pdf";

let docId: number | null = null;

test.beforeAll(() => {
  // Restes d'une exécution interrompue : on repart d'un dossier propre.
  rmSync(WORKDIR, { recursive: true, force: true });
  mkdirSync(BEFORE, { recursive: true });
  copyFileSync(FIXTURE, join(BEFORE, NAME));
});

test.afterAll(async ({ playwright }, testInfo) => {
  // La base e2e survit d'une exécution à l'autre : le document part avec son
  // dossier, sinon une carte introuvable y traînerait.
  if (docId !== null) {
    const api = await playwright.request.newContext({ baseURL: testInfo.project.use.baseURL });
    await api.delete(`/api/library/doc/${docId}`);
    await api.dispose();
  }
  rmSync(WORKDIR, { recursive: true, force: true });
});

// En série : le second scénario reprend le document que le premier a relié.
test.describe.serial("Localiser un fichier déplacé", () => {
  test.beforeEach(async ({ page }) => {
    // Sans quoi le voile de la visite guidée couvrirait la bibliothèque.
    await page.request.post("/api/preferences", { data: { tour_done: true } });
  });

  test("la carte propose de localiser le fichier, puis retrouve sa vignette", async ({ page }) => {
    const imported = await page.request.post("/api/library/import", { data: { path: join(BEFORE, NAME) } });
    expect(imported.ok(), await imported.text()).toBeTruthy();
    docId = ((await imported.json()) as { id: number }).id;

    // Le dossier est renommé : le document ne sait plus où est son fichier.
    renameSync(BEFORE, AFTER);
    await stubDesktopFilePicker(page, join(AFTER, NAME));
    await page.goto("/");

    const card = page.locator(".doc-card", { hasText: NAME });
    await expect(card.getByText(/fichier introuvable|file not found/i)).toBeVisible({ timeout: 15_000 });
    await expect(card.locator("img")).toHaveCount(0);

    await card.getByRole("button", { name: /localiser|locate/i }).click();

    // La vignette revient, et elle se charge vraiment (pas un cadre vide)…
    const thumbnail = card.locator("img");
    await expect(thumbnail).toBeVisible({ timeout: 30_000 });
    await expect
      .poll(() => thumbnail.evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 30_000 })
      .toBeGreaterThan(0);
    // …sur la bibliothèque (le bouton n'a pas ouvert le lecteur), pour le MÊME
    // document : aucun doublon n'a été créé.
    await expect(page).toHaveURL(/\/$/);
    const docs = (await (await page.request.get("/api/library/documents")).json()) as {
      id: number;
      title: string;
      file_missing: boolean;
    }[];
    expect(docs.filter((d) => d.title === NAME).map((d) => d.id)).toEqual([docId]);
    expect(docs.find((d) => d.id === docId)?.file_missing).toBe(false);
  });

  test("le lecteur d'un fichier introuvable n'ouvre aucune session et propose de le localiser", async ({ page }) => {
    expect(docId, "le scénario précédent a importé le document").not.toBeNull();
    // Déplacé une seconde fois : le lecteur l'ouvre maintenant qu'il manque.
    renameSync(AFTER, LATER);
    await stubDesktopFilePicker(page, join(LATER, NAME));
    let sessionStarted = false;
    let socketOpened = false;
    page.on("request", (request) => {
      if (request.url().includes("/api/session/start")) sessionStarted = true;
    });
    page.on("websocket", (socket) => {
      if (socket.url().includes(`/api/reader/${docId}/stream`)) socketOpened = true;
    });

    await page.goto(`/reader/${docId}`);

    await expect(page.getByRole("heading", { name: /fichier introuvable|file not found/i })).toBeVisible({
      timeout: 15_000,
    });
    // Le dernier emplacement connu est celui d'où le fichier vient de partir.
    await expect(page.getByText(/\.relink[\\/]b$/)).toBeVisible();
    await expect(page.locator("[data-page]")).toHaveCount(0);
    expect(sessionStarted, "aucune session pour un fichier absent").toBe(false);
    expect(socketOpened, "aucun WebSocket pour un fichier absent").toBe(false);

    await page.getByRole("button", { name: /localiser le fichier|locate file/i }).click();

    // Relié : la porte monte le lecteur, qui ouvre enfin sa session et ses pages.
    await expect(page.locator("[data-page]")).toHaveCount(3, { timeout: 30_000 });
    await expect.poll(() => sessionStarted, { timeout: 15_000 }).toBe(true);
  });
});
