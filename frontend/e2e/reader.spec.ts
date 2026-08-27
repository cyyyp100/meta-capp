// reader.spec.ts — Le parcours central : importer un document, l'ouvrir, lire.
//
// Ollama n'est pas requis : on n'affirme jamais rien sur le CONTENU produit par
// le LLM, seulement sur l'état de l'interface (pages affichées, panneau ouvert,
// indicateur d'attente). La fiche de classification arrive en tâche de fond et
// reste `pending` sans Ollama, ce que l'interface doit savoir montrer.

import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

const FIXTURE = fileURLToPath(new URL("./fixtures/echantillon.pdf", import.meta.url));

// La fixture est versionnée par une EXCEPTION dans .gitignore (`*.pdf` l'excluait,
// la CI clonait donc sans elle). Sans ce garde-fou, son absence se manifestait par
// un import qui répond 400 « Fichier introuvable », un toast déjà disparu et trois
// scénarios en timeout de 30 s — trente minutes de diagnostic pour un fichier manquant.
test.beforeAll(() => {
  if (!existsSync(FIXTURE)) {
    throw new Error(
      `Fixture absente : ${FIXTURE}\nElle doit être versionnée (voir l'exception \`!frontend/e2e/fixtures/*.pdf\` dans .gitignore).`,
    );
  }
});

/**
 * Le sélecteur de fichier natif passe par le pont pywebview, absent d'un
 * navigateur. On l'implante avant le chargement de la page, exactement comme la
 * coque de bureau le fait : le frontend obtient un CHEMIN, le backend lit le
 * fichier côté serveur (voir src/api/platform.ts).
 */
async function stubDesktopFilePicker(page: Page, path: string) {
  await page.addInitScript((p) => {
    (window as unknown as Record<string, unknown>).pywebview = {
      api: { pick_pdf: async () => p },
    };
  }, path);
}

/**
 * Avance l'horloge simulée SECONDE PAR SECONDE.
 *
 * `fastForward` déclenche tous les minuteurs d'un coup, sans rendre la main à
 * React entre deux. Or le décompte du SAS réarme son `setTimeout` à chaque
 * rendu : d'un bloc, il n'avance que d'un cran. En avançant pas à pas, React a
 * le temps de se re-rendre et le compte à rebours se déroule vraiment.
 */
async function advanceSeconds(page: Page, seconds: number) {
  for (let i = 0; i < seconds; i++) await page.clock.runFor(1000);
}

test.describe("Lecture d'un document", () => {
  test("importe un PDF, l'ouvre et affiche ses pages", async ({ page }) => {
    await stubDesktopFilePicker(page, FIXTURE);
    await page.goto("/");

    await page.getByRole("button", { name: /importer/i }).first().click();

    // L'import redirige vers le lecteur.
    await expect(page).toHaveURL(/\/reader\/\d+$/, { timeout: 30_000 });

    // Les trois pages du PDF sont rendues en images.
    const pages = page.locator("[data-page]");
    await expect(pages).toHaveCount(3, { timeout: 30_000 });

    // Et l'image de la première page se charge vraiment (pas un cadre vide).
    const firstImage = pages.first().locator("img");
    await expect(firstImage).toBeVisible();
    await expect
      .poll(() => firstImage.evaluate((img: HTMLImageElement) => img.naturalWidth), {
        timeout: 30_000,
      })
      .toBeGreaterThan(0);
  });

  test("le document importé apparaît dans la bibliothèque", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("echantillon", { exact: false }).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("le SAS d'entrée retient avant la lecture puis laisse passer", async ({ page }) => {
    // Ouvrir un document ne mène pas au texte : un SAS de préparation d'une
    // minute s'interpose, passable après 30 s. C'est voulu — on ralentit avant
    // de lire. On avance l'horloge plutôt que d'attendre pour de vrai.
    await page.clock.install();
    await page.goto("/");
    await page.getByText("echantillon", { exact: false }).first().click();
    await expect(page).toHaveURL(/\/reader\/\d+$/);

    const gate = page.getByRole("button", { name: /disponible dans|continuer/i });
    await expect(gate).toBeVisible({ timeout: 15_000 });
    await expect(gate).toBeDisabled();
    await expect(page.getByRole("timer")).toBeVisible();

    await advanceSeconds(page, 31);
    await expect(gate).toBeEnabled();
  });

  // Les noms accessibles des commandes de Gemma (🎯 ⤢ ✕ -> boutons nommés) sont
  // vérifiés en test de composant (src/features/reader/GemmaPanel.test.tsx) :
  // les atteindre ici imposerait de traverser le SAS puis le warm-up, une
  // machine à états que l'horloge simulée ne franchit pas de façon fiable.
});
