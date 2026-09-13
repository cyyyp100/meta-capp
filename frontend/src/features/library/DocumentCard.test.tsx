// DocumentCard.test.tsx — Renommer et supprimer un document passent par le
// CLIC DROIT, et par lui seul : ni crayon ni corbeille sur la carte.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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

function renderCard(onDelete = vi.fn(), onMove = vi.fn(), onRename = vi.fn()) {
  render(
    <MemoryRouter>
      <DocumentCard
        doc={doc}
        folders={[folder(1, "Maths", 0, null), folder(2, "Algèbre", 1, 1)]}
        onKeyword={() => {}}
        onMove={onMove}
        onRename={onRename}
        onDelete={onDelete}
      />
    </MemoryRouter>,
  );
  return { onDelete, onMove, onRename };
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
});
