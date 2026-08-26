// OrderingAnswer.test.tsx — La remise en ordre doit être jouable SANS souris.
//
// Le glisser-déposer est l'interaction principale, mais il est inopérant au
// clavier et muet pour un lecteur d'écran. Ce test fige les deux garde-fous :
// les flèches ↑/↓ réordonnent réellement, et la position atteinte est annoncée.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { serializeOrder } from "./AnswerInput";
import { OrderingAnswer } from "./OrderingAnswer";

const STEPS = ["Poser les hypothèses", "Appliquer le théorème", "Conclure"];

describe("OrderingAnswer", () => {
  it("réordonne au clavier et renvoie la séquence numérotée", async () => {
    const onSubmit = vi.fn();
    render(<OrderingAnswer items={STEPS} onSubmit={onSubmit} />);

    // « Conclure » remonte d'un cran : il passe devant « Appliquer le théorème ».
    await userEvent.click(screen.getByRole("button", { name: /monter.*conclure/i }));
    await userEvent.click(screen.getByRole("button", { name: /valider/i }));

    expect(onSubmit).toHaveBeenCalledWith([
      "Poser les hypothèses",
      "Conclure",
      "Appliquer le théorème",
    ]);
  });

  it("annonce le déplacement dans une région live", async () => {
    render(<OrderingAnswer items={STEPS} onSubmit={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /descendre.*poser les hypothèses/i }));

    expect(screen.getByRole("status")).toHaveTextContent(/poser les hypothèses/i);
    expect(screen.getByRole("status")).toHaveTextContent(/2/);
  });

  it("borne les déplacements aux extrémités", async () => {
    render(<OrderingAnswer items={STEPS} onSubmit={vi.fn()} />);

    expect(screen.getByRole("button", { name: /monter.*poser les hypothèses/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /descendre.*conclure/i })).toBeDisabled();
  });

  it("affiche la position attendue des étapes mal placées après validation", () => {
    // Ordre proposé faux : « Conclure » est en tête alors qu'il finit la séquence.
    render(
      <OrderingAnswer
        items={["Conclure", "Poser les hypothèses", "Appliquer le théorème"]}
        correctOrder={STEPS}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText(/attendu en 3/i)).toBeInTheDocument();
    // Une fois figée, la liste ne se réordonne plus.
    expect(screen.queryByRole("button", { name: /monter/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /valider/i })).not.toBeInTheDocument();
  });
});

describe("serializeOrder", () => {
  it("numérote la séquence transmise à l'évaluation", () => {
    expect(serializeOrder(["A", "B"])).toBe("1. A\n2. B");
  });
});
