// DocumentCard.test.tsx — Renommer et supprimer un document passent par le
// CLIC DROIT, et par lui seul : ni crayon ni corbeille sur la carte. Seule
// exception, un fichier introuvable montre son bouton « Localiser… ».

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { DocumentSummary } from "../../api/types";
import { DocumentCard } from "./DocumentCard";
import type { FlatFolder } from "./folderTree";

const doc: DocumentSummary = {
  id: 7,
  title: "Analyse — chapitre 3",
  page_count: 12,
  last_page: 4,
  subject: "maths",
  folder_id: null,
  extraction_engine: "pdfium_scroll",
  summary: "",
  keywords: [],
  digest_status: "none",
  imported_at: "",
} as unknown as DocumentSummary;

const folder = (id: number, name: string, depth: number, parent_id: number | null): FlatFolder =>
  ({ id, name, depth, parent_id, position: 0, doc_count: 0, total_count: 0, children: [] }) as FlatFolder;

// Fichier déplacé depuis l'import (services/library.file_missing).
const missing = { ...doc, file_missing: true, last_known_folder: "~/Cours" } as DocumentSummary;

/** La carte, et la route du lecteur : on voit si un clic l'a ouvert. */
function renderCard(card: DocumentSummary = doc) {
  const onDelete = vi.fn();
  const onMove = vi.fn();
  const onRename = vi.fn();
  const onRelink = vi.fn();
  const view = render(
    <MemoryRouter>
      <Routes>
        <Route
          path="/"
          element={
            <DocumentCard
              doc={card}
              folders={[folder(1, "Maths", 0, null), folder(2, "Algèbre", 1, 1)]}
              onKeyword={() => {}}
              onMove={onMove}
              onRename={onRename}
              onDelete={onDelete}
              onRelink={onRelink}
            />
          }
        />
        <Route path="/reader/:docId" element={<p>Lecteur ouvert</p>} />
      </Routes>
    </MemoryRouter>,
  );
  return { onDelete, onMove, onRename, onRelink, container: view.container };
}

describe("DocumentCard", () => {
  it("n'expose aucun bouton de suppression sur la carte", () => {
    renderCard();
    expect(screen.queryByRole("button", { name: /supprimer|delete/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("propose « Supprimer » dans le menu du clic droit", async () => {
    const { onDelete } = renderCard();
    await userEvent.pointer({ keys: "[MouseRight]", target: screen.getByText("Analyse — chapitre 3") });

    const menu = await screen.findByRole("menu");
    expect(menu).toHaveTextContent(/ouvrir|open/i);
    expect(menu).toHaveTextContent(/déplacer vers|move to/i);
    await userEvent.click(screen.getByRole("menuitem", { name: /supprimer|delete/i }));

    expect(onDelete).toHaveBeenCalledWith(doc);
  });

  it("renomme le document en place depuis le menu du clic droit", async () => {
    const { onRename } = renderCard();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    await userEvent.pointer({ keys: "[MouseRight]", target: screen.getByText("Analyse — chapitre 3") });
    await userEvent.click(await screen.findByRole("menuitem", { name: /renommer|rename/i }));

    // Le titre devient un champ, pré-rempli, qui garde le focus une fois le
    // menu refermé — sinon il se validerait à vide avant qu'on ait tapé.
    const input = await screen.findByRole("textbox", { name: /titre|title/i });
    expect(input).toHaveValue("Analyse — chapitre 3");
    expect(input).toHaveFocus();

    await userEvent.clear(input);
    await userEvent.type(input, "  Analyse chap. 3 {Enter}");

    expect(onRename).toHaveBeenCalledWith(7, "Analyse chap. 3");
    expect(screen.queryByRole("textbox", { name: /titre|title/i })).not.toBeInTheDocument();
  });

  it("n'envoie rien si le titre est vide, inchangé ou abandonné (Échap)", async () => {
    const { onRename } = renderCard();
    await userEvent.pointer({ keys: "[MouseRight]", target: screen.getByText("Analyse — chapitre 3") });
    await userEvent.click(await screen.findByRole("menuitem", { name: /renommer|rename/i }));
    const input = await screen.findByRole("textbox", { name: /titre|title/i });

    await userEvent.clear(input);
    await userEvent.keyboard("{Enter}");
    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByText("Analyse — chapitre 3")).toBeInTheDocument();

    await userEvent.pointer({ keys: "[MouseRight]", target: screen.getByText("Analyse — chapitre 3") });
    await userEvent.click(await screen.findByRole("menuitem", { name: /renommer|rename/i }));
    await userEvent.type(await screen.findByRole("textbox", { name: /titre|title/i }), "x{Escape}");
    expect(onRename).not.toHaveBeenCalled();
  });

  it("range le document depuis le sous-menu « Déplacer vers… »", async () => {
    const { onMove } = renderCard();
    await userEvent.pointer({ keys: "[MouseRight]", target: screen.getByText("Analyse — chapitre 3") });
    await userEvent.hover(await screen.findByRole("menuitem", { name: /déplacer vers|move to/i }));

    await userEvent.click(await screen.findByRole("menuitem", { name: "Algèbre" }));

    expect(onMove).toHaveBeenCalledWith(7, 2);
  });

  it("remplace la vignette d'un fichier introuvable par « Localiser… », sans ouvrir le lecteur", async () => {
    const { onRelink, container } = renderCard(missing);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/fichier introuvable|file not found/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /localiser|locate/i }));

    expect(onRelink).toHaveBeenCalledWith(missing);
    expect(screen.queryByText("Lecteur ouvert")).not.toBeInTheDocument();
    // Le reste de la carte ouvre toujours le lecteur (qui proposera de localiser).
    await userEvent.click(screen.getByText("Analyse — chapitre 3"));
    expect(screen.getByText("Lecteur ouvert")).toBeInTheDocument();
  });

  it("propose « Localiser le fichier… » en tête du menu d'un fichier introuvable", async () => {
    const { onRelink } = renderCard(missing);
    await userEvent.pointer({ keys: "[MouseRight]", target: screen.getByText("Analyse — chapitre 3") });

    const items = await screen.findAllByRole("menuitem");
    expect(items[0]).toHaveTextContent(/localiser le fichier|locate file/i);
    await userEvent.click(items[0]);

    expect(onRelink).toHaveBeenCalledWith(missing);
  });

  it("garde sa vignette et ne propose rien à localiser quand le fichier est là", async () => {
    const { container } = renderCard();
    expect(container.querySelector("img")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /localiser|locate/i })).not.toBeInTheDocument();

    await userEvent.pointer({ keys: "[MouseRight]", target: screen.getByText("Analyse — chapitre 3") });
    expect(await screen.findByRole("menu")).not.toHaveTextContent(/localiser|locate/i);
  });
});
