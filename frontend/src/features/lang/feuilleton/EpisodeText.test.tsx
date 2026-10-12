// EpisodeText.test.tsx — Une lecture, aide à la demande.
//
// Deux gestes, deux événements distincts : un tap de mot (révélation) et une
// traduction de réplique montrée — une seule fois par réplique, marquée « Tout
// traduire » quand elle vient du bouton global. La marque d'une note est un
// bouton à part : l'ouvrir ne compte jamais comme un tap de mot.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EpisodeNote, EpisodeView } from "../../../api/feuilleton";
import { EpisodeText } from "./EpisodeText";

const episode: EpisodeView = {
  id: 7, n: 1, title: "t", summary: "", teaser: "", format: "dialogue", kind: "normal", family: "latin", dir: "ltr",
  aid_level: null, tone_colors: false, gender_colors: false, explain_lang: "fr",
  lines: [
    { speaker: "Ana", translation: "Salut.", tokens: [{ text: "Hola", w: true, g: 0 }, { text: ".", w: false }] },
    {
      speaker: "Luis", translation: "Ça va ?",
      tokens: [{ text: "¿", w: false }, { text: "Qué", w: true, g: null }, { text: " ", w: false }, { text: "tal", w: true }, { text: "?", w: false }],
    },
  ],
  glossary: [{
    form: "Hola", lemma: "hola", translation: "salut", pos: "interjection", gender: null, article: null, pron: "ˈola",
    vocalized: null, faux_ami: null, acquired: false, transparent: false,
  }],
};
const notes: EpisodeNote[] = [{ n: 1, line: 0, tokens: [0], kind: "usage", text: "Hola sert à saluer à toute heure.", auto: false }];

describe("EpisodeText", () => {
  it("sans traduction : ni traduction ni bouton", () => {
    render(<EpisodeText episode={episode} />);
    expect(screen.queryByText("Salut.")).toBeNull();
    expect(screen.queryByRole("button", { name: /traduction|translation/i })).toBeNull();
  });

  it("traduit une réplique à la demande, et ne la signale qu'une fois", () => {
    const shown = vi.fn();
    render(<EpisodeText episode={episode} translation="lines" onLineShown={shown} />);
    const buttons = screen.getAllByRole("button", { name: /voir la traduction|show the translation/i });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[1]);
    expect(screen.getByText("Ça va ?")).toBeInTheDocument();
    expect(screen.queryByText("Salut.")).toBeNull();
    expect(shown).toHaveBeenCalledTimes(1);
    expect(shown).toHaveBeenCalledWith(1, false);
  });

  it("« Tout traduire » montre tout, se referme, et ne signale chaque réplique qu'une fois", () => {
    const shown = vi.fn();
    render(<EpisodeText episode={episode} translation="toggle" onLineShown={shown} />);
    fireEvent.click(screen.getAllByRole("button", { name: /voir la traduction|show the translation/i })[0]);
    expect(shown).toHaveBeenLastCalledWith(0, false);
    fireEvent.click(screen.getByRole("button", { name: /tout traduire|translate everything/i }));
    expect(screen.getByText("Salut.")).toBeInTheDocument();
    expect(screen.getByText("Ça va ?")).toBeInTheDocument();
    expect(shown.mock.calls).toEqual([[0, false], [1, true]]);
    fireEvent.click(screen.getByRole("button", { name: /masquer|hide/i }));
    expect(screen.queryByText("Ça va ?")).toBeNull();
    expect(screen.getByText("Salut.")).toBeInTheDocument(); // ouverte à la main, elle reste
    fireEvent.click(screen.getByRole("button", { name: /tout traduire|translate everything/i }));
    expect(shown).toHaveBeenCalledTimes(2);
  });

  it("tout affiché : aucune demande, aucun événement", () => {
    const shown = vi.fn();
    render(<EpisodeText episode={episode} translation="all" onLineShown={shown} />);
    expect(screen.getByText("Salut.")).toBeInTheDocument();
    expect(shown).not.toHaveBeenCalled();
  });

  it("un tap de mot ouvre sa bulle et compte ; une note s'ouvre à part, sans tap", () => {
    const reveal = vi.fn();
    render(<EpisodeText episode={episode} onReveal={reveal} notes={notes} />);
    fireEvent.click(screen.getByRole("button", { name: "Note 1" }));
    expect(screen.getByRole("note")).toHaveTextContent("Hola sert à saluer à toute heure.");
    expect(reveal).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Hola" }));
    expect(reveal).toHaveBeenCalledWith(0, 0);
    expect(screen.getByRole("dialog", { name: "Hola" })).toHaveTextContent("salut");
  });

  it("un verbe conjugué : sa traduction dans le texte, puis son infinitif, prononcé, et son sens", () => {
    const verb: EpisodeView = {
      ...episode,
      lines: [{ speaker: "Ana", translation: "Nous avons le temps.", tokens: [{ text: "Tenemos", w: true, g: 0 }] }],
      glossary: [{
        form: "Tenemos", lemma: "tener", translation: "Nous avons", lemma_translation: "avoir", pos: "verbe",
        gender: null, article: null, pron: "teˈneɾ", vocalized: null, faux_ami: null, acquired: false, transparent: false,
      }],
    };
    render(<EpisodeText episode={verb} onReveal={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Tenemos" }));
    const bubble = screen.getByRole("dialog", { name: "Tenemos" });
    expect(bubble).toHaveTextContent(/Nous avons — (forme de base|base form) : tener \/teˈneɾ\/ = avoir/);
    // La prononciation est celle du lemme : elle n'est pas posée sous « Tenemos ».
    expect(screen.queryByText("teˈneɾ")).toBeNull();
  });
});
