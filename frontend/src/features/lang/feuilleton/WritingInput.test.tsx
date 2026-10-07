// WritingInput.test.tsx — La zone de l'expression écrite et son clavier.
//
// Ce qui compte pour écrire dans une langue qu'on apprend : la zone porte la
// langue et le sens d'écriture sans correcteur automatique, une touche insère
// AU CURSEUR sans voler le focus, rien ne se passe pendant une composition
// d'IME, et le texte part en NFC.
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { WritingKeyboard } from "../../../api/feuilleton";
import { toNfc, WritingInput } from "./WritingInput";

const spanish: WritingKeyboard = {
  layout: "keys",
  rtl: false,
  groups: [{ name: "letters", keys: [{ char: "ñ", label: "ñ" }, { char: "¿", label: "¿" }] }],
};
const arabic: WritingKeyboard = {
  layout: "keys",
  rtl: true,
  groups: [
    { name: "letters", keys: [{ char: "ب", label: "ب" }] },
    { name: "vowels", keys: [{ char: "َ", label: "◌َ" }] },
  ],
};

function Harness({ keyboard, lang = "es", rtl = false, initial = "", maxChars = 40 }: {
  keyboard: WritingKeyboard | null; lang?: string; rtl?: boolean; initial?: string; maxChars?: number;
}) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <WritingInput value={value} onChange={setValue} lang={lang} rtl={rtl} keyboard={keyboard} maxChars={maxChars} placeholder="Écris ici…" />
      <output data-testid="value">{value}</output>
    </>
  );
}

function area() {
  return screen.getByRole("textbox") as HTMLTextAreaElement;
}

describe("WritingInput", () => {
  it("porte la langue et le sens d'écriture, sans correcteur ni majuscule automatique", () => {
    render(<Harness keyboard={spanish} />);
    const ta = area();
    expect(ta).toHaveAttribute("lang", "es");
    expect(ta).toHaveAttribute("dir", "ltr");
    expect(ta).toHaveAttribute("spellcheck", "false");
    expect(ta).toHaveAttribute("autocorrect", "off");
    expect(ta).toHaveAttribute("autocapitalize", "off");
  });

  it("insère la touche au curseur, sans voler le focus", () => {
    render(<Harness keyboard={spanish} initial="Hola Espaa" />);
    const ta = area();
    ta.focus();
    ta.setSelectionRange(9, 9);
    const key = screen.getByRole("button", { name: "ñ" });
    // Le bouton empêche le comportement par défaut du clic souris : le focus reste dans la zone.
    expect(fireEvent.mouseDown(key)).toBe(false);
    fireEvent.click(key);
    expect(screen.getByTestId("value")).toHaveTextContent("Hola España");
    expect(document.activeElement).toBe(ta);
  });

  it("ne fait rien pendant une composition d'IME", () => {
    render(<Harness keyboard={spanish} initial="Hola" />);
    const ta = area();
    ta.setSelectionRange(4, 4);
    fireEvent.compositionStart(ta);
    const key = screen.getByRole("button", { name: "¿" });
    expect(key).toBeDisabled();
    fireEvent.click(key);
    expect(screen.getByTestId("value")).toHaveTextContent("Hola");
    fireEvent.compositionEnd(ta);
    fireEvent.click(screen.getByRole("button", { name: "¿" }));
    expect(screen.getByTestId("value")).toHaveTextContent("Hola¿");
  });

  it("respecte la longueur maximale", () => {
    render(<Harness keyboard={spanish} initial="abcd" maxChars={5} />);
    const ta = area();
    ta.setSelectionRange(4, 4);
    fireEvent.click(screen.getByRole("button", { name: "ñ" }));
    fireEvent.click(screen.getByRole("button", { name: "ñ" }));
    expect(screen.getByTestId("value").textContent).toBe("abcdñ");
    expect(ta).toHaveAttribute("maxLength", "5");
  });

  it("écrit l'arabe de droite à gauche, voyelle brève sur son cercle pointillé", () => {
    render(<Harness keyboard={arabic} lang="ar" rtl initial="ب" />);
    const ta = area();
    expect(ta).toHaveAttribute("dir", "rtl");
    expect(ta.style.fontFamily).toContain("--font-arabic");
    const vowel = screen.getByRole("button", { name: "َ" });
    expect(vowel).toHaveTextContent("◌َ");
    ta.setSelectionRange(1, 1);
    fireEvent.click(vowel);
    expect(screen.getByTestId("value").textContent).toBe("بَ");
  });

  it("laisse la méthode de saisie du système au mandarin", () => {
    render(<Harness keyboard={{ layout: "ime", rtl: false, groups: [] }} lang="zh" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/pinyin/i)).toBeInTheDocument();
  });

  it("normalise en NFC à l'envoi", () => {
    expect(toNfc("España")).toBe("España");
    expect(toNfc("España").length).toBe(6);
  });
});
