// brainstorming.spec.ts — Les garde-fous de la page Brainstorming.
//
// Rien n'empêchait de cliquer dix fois « Nouvelle discussion » : chaque clic
// empilait une discussion vide. Le serveur rouvre désormais la page blanche
// existante ; ce parcours vérifie que l'interface s'y tient.

import { expect, test } from "@playwright/test";

const BLANK_TITLES = ["Nouvelle discussion", "New discussion"];

test.describe("Brainstorming", () => {
  test.beforeEach(async ({ page }) => {
    // Même raison que shell.spec.ts : le voile de la visite guidée masquerait tout.
    await page.request.post("/api/preferences", { data: { tour_done: true } });
    await page.goto("/brainstorming");
  });

  test("« Nouvelle discussion » rouvre la page blanche au lieu d'en empiler", async ({ page }) => {
    const create = page.getByRole("button", { name: /nouvelle discussion|new discussion/i });
    for (let i = 0; i < 5; i++) {
      await create.click();
      await expect(create).toBeEnabled();
    }

    // La base est partagée par toute la campagne : on compte les vierges, pas le total.
    const discussions: { title: string; message_count: number }[] = await (
      await page.request.get("/api/brainstorming/discussions")
    ).json();
    const blanks = discussions.filter((d) => d.message_count === 0 && BLANK_TITLES.includes(d.title));
    expect(blanks).toHaveLength(1);

    // Le clic a un effet visible même quand la page blanche était déjà ouverte.
    await expect(page.getByPlaceholder(/pose ta question|ask gemma/i)).toBeFocused();
  });
});
