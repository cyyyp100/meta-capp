// PageBookmarkButton.test.tsx — Le marque-page d'une page du lecteur.
//
// Un bouton à bascule : il dit ce qu'il fera (poser sur cette page, ou
// retirer), son état est annoncé (`aria-pressed`), et il rend la page au
// lecteur, qui décide (un seul marque-page par document).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useLangStore } from "../../i18n";
import { PageBookmarkButton } from "./PageBookmarkButton";

describe("PageBookmarkButton", () => {
  beforeEach(() => useLangStore.setState({ lang: "fr" }));

  it("propose de marquer la page, et la rend au lecteur", async () => {
    const onToggle = vi.fn();
    render(<PageBookmarkButton page={12} active={false} onToggle={onToggle} />);

    const button = screen.getByRole("button", { name: /marquer la page 12/i });
    expect(button).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(button);
    expect(onToggle).toHaveBeenCalledWith(12);
  });

  it("se dit posé, et propose de le retirer", async () => {
    const onToggle = vi.fn();
    render(<PageBookmarkButton page={12} active onToggle={onToggle} />);

    const button = screen.getByRole("button", { name: /retirer le marque-page/i });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button.querySelector("svg")).toHaveAttribute("fill", "currentColor");
    await userEvent.click(button);
    expect(onToggle).toHaveBeenCalledWith(12);
  });
});
