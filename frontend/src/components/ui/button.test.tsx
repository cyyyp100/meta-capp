import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./button";

describe("Button", () => {
  it("rend un vrai <button> et déclenche onClick", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Importer</Button>);

    const btn = screen.getByRole("button", { name: "Importer" });
    await userEvent.click(btn);

    expect(onClick).toHaveBeenCalledOnce();
  });

  it("expose variante et taille en attributs data-*", () => {
    render(
      <Button variant="destructive" size="sm">
        Supprimer
      </Button>,
    );

    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute("data-variant", "destructive");
    expect(btn).toHaveAttribute("data-size", "sm");
  });

  it("porte les états interactifs que les styles inline ne pouvaient pas porter", () => {
    // Le cœur de la refonte : c'est l'absence de ces pseudo-classes qui faisait
    // « prototype ». Si quelqu'un les retire, ce test tombe.
    render(<Button>Ouvrir</Button>);

    const cls = screen.getByRole("button").className;
    expect(cls).toContain("hover:");
    expect(cls).toContain("focus-visible:");
    expect(cls).toContain("active:");
    expect(cls).toContain("disabled:");
  });

  it("neutralise le bouton et l'annonce pendant une action en cours", async () => {
    const onClick = vi.fn();
    render(
      <Button pending onClick={onClick}>
        Import…
      </Button>,
    );

    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");

    await userEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("délègue le rendu avec asChild sans casser Slot", () => {
    // Un lien stylé en bouton : Slot n'accepte qu'un enfant, donc le spinner de
    // `pending` ne doit pas être injecté dans ce mode.
    render(
      <Button asChild pending>
        <a href="/stats">Statistiques</a>
      </Button>,
    );

    const link = screen.getByRole("link", { name: "Statistiques" });
    expect(link).toHaveAttribute("data-slot", "button");
  });

  it("laisse une classe passée en prop l'emporter sur la variante", () => {
    // twMerge doit résoudre le conflit, sinon les surcharges ponctuelles des
    // écrans dépendraient de l'ordre du CSS compilé.
    render(<Button className="rounded-full">Chip</Button>);

    const cls = screen.getByRole("button").className;
    expect(cls).toContain("rounded-full");
    expect(cls).not.toContain("rounded-sm");
  });
});
