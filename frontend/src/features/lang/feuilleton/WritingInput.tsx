// WritingInput — La zone de l'expression écrite, et son clavier.
//
// Écrire dans la langue qu'on apprend demande des caractères que le clavier
// de l'apprenant n'a pas toujours : accents et ponctuation espagnols, trémas
// allemands, lettres et voyelles brèves arabes. Le clavier vient du serveur
// (lang_static.writing_keyboard) ; ici :
//   * la zone porte la langue et le sens d'écriture, sans correcteur ni
//     majuscule automatique (ils « corrigent » vers la langue du système) ;
//   * une touche insère son caractère AU CURSEUR et ne vole jamais le focus ;
//   * pendant une composition (méthode de saisie du chinois), les touches ne
//     font rien : la composition en cours appartient à l'IME ;
//   * le texte part en NFC (`toNfc`), comme le serveur le range.
import { useRef, useState } from "react";

import { AutoGrowTextarea } from "../../../components/AutoGrowTextarea";
import type { WritingKeyboard } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { chipBtn } from "./ui";

export function toNfc(text: string): string {
  return text.normalize("NFC");
}

export function WritingInput({
  value,
  onChange,
  lang,
  rtl,
  keyboard,
  maxChars,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  /** Code de langue BCP 47 du texte (es, de, ar, zh…). */
  lang: string;
  rtl: boolean;
  keyboard: WritingKeyboard | null;
  maxChars: number;
  placeholder?: string;
}) {
  const t = useT();
  const area = useRef<HTMLTextAreaElement>(null);
  const [composing, setComposing] = useState(false);

  function insert(char: string) {
    const el = area.current;
    if (!el || composing) return;
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? start;
    const next = (value.slice(0, start) + char + value.slice(end)).slice(0, maxChars);
    onChange(next);
    const caret = Math.min(start + char.length, next.length);
    // Le curseur revient après le caractère inséré, une fois la valeur rendue.
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  }

  return (
    <div>
      <AutoGrowTextarea
        ref={area}
        value={value}
        onChange={(e) => onChange(e.target.value.slice(0, maxChars))}
        onCompositionStart={() => setComposing(true)}
        onCompositionEnd={() => setComposing(false)}
        lang={lang}
        dir={rtl ? "rtl" : "ltr"}
        spellCheck={false}
        autoCorrect="off"
        autoCapitalize="off"
        autoComplete="off"
        maxLength={maxChars}
        maxHeight={320}
        placeholder={placeholder}
        aria-label={placeholder}
        style={{
          width: "100%",
          minHeight: 120,
          padding: "10px 12px",
          borderRadius: "var(--radius-sm)",
          border: "1px solid var(--border)",
          background: "var(--surface)",
          color: "var(--text)",
          fontSize: rtl ? 22 : lang === "zh" ? 20 : 17,
          lineHeight: rtl ? 1.9 : 1.6,
          fontFamily: rtl ? "var(--font-arabic)" : undefined,
        }}
      />
      {keyboard?.layout === "ime" && (
        <p style={{ color: "var(--muted)", fontSize: 13, margin: "6px 0 0" }}>{t("feuil.expr.ime_hint")}</p>
      )}
      {keyboard?.layout === "keys" && (
        <div style={{ display: "grid", gap: 6, marginTop: 8 }} aria-label={t("feuil.kb.title")}>
          {keyboard.groups.map((group) => (
            <div key={group.name} dir={keyboard.rtl ? "rtl" : "ltr"} style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
              {keyboard.groups.length > 1 && (
                <span style={{ fontSize: 11, color: "var(--muted)", minWidth: 64 }}>{t(`feuil.kb.${group.name}`)}</span>
              )}
              {group.keys.map((key) => (
                <button
                  key={key.char}
                  type="button"
                  // Le focus reste dans la zone : le curseur ne bouge pas.
                  onMouseDown={(e) => e.preventDefault()}
                  onPointerDown={(e) => e.preventDefault()}
                  onClick={() => insert(key.char)}
                  disabled={composing}
                  tabIndex={-1}
                  aria-label={key.char}
                  style={{
                    ...chipBtn(false),
                    minHeight: 36,
                    minWidth: 36,
                    padding: "4px 8px",
                    fontSize: keyboard.rtl ? 20 : 16,
                    fontFamily: keyboard.rtl ? "var(--font-arabic)" : undefined,
                  }}
                >
                  {key.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
