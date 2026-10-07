// Expression — L'étape « expression écrite » : écrire quelques phrases.
//
// Juste après la leçon, pour l'appliquer aussitôt. La consigne vient du serveur
// (déterministe, dans la langue d'explication), avec les mots du jour et les
// formes du point à employer. Le compteur et la liste de contrôle guident ; ils
// ne notent rien. « Continuer » envoie le texte et passe à la suite sans
// attendre : Clikoda corrige en arrière-plan, la correction attend à l'écran de
// fin (ou à l'accueil, si elle arrive après).
import { useState } from "react";

import { api } from "../../../api/client";
import type { WritingKeyboard, WritingTask, WritingWord } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { NextButton, type StepProps } from "./Steps";
import { Card, StepTitle, Target } from "./ui";
import { toNfc, WritingInput } from "./WritingInput";

const WORD_RE = /[\p{L}\p{N}\p{M}]+(?:['’-][\p{L}\p{N}\p{M}]+)*/gu;
const HAN_RE = /\p{Script=Han}/gu;
const HARAKAT_RE = /[ً-ْٰ]/g;

/** Mots (ou caractères chinois) du texte : le compteur affiché, pas une mesure. */
export function countUnits(text: string, unit: "words" | "chars"): number {
  return (text.match(unit === "chars" ? HAN_RE : WORD_RE) ?? []).length;
}

/** Le mot du jour est-il employé ? Tel quel ou fléchi (même début), sans voyelles brèves en arabe. */
export function wordUsed(text: string, word: WritingWord, family: string): boolean {
  const forms = word.match.filter(Boolean).map((m) => m.normalize("NFC").toLocaleLowerCase());
  if (family === "hanzi") return forms.some((m) => text.includes(m));
  const tokens = (text.normalize("NFC").toLocaleLowerCase().match(WORD_RE) ?? []);
  if (family === "arabe") {
    const bare = tokens.map((w) => w.replace(HARAKAT_RE, ""));
    return forms.some((m) => bare.some((w) => w.includes(m.replace(HARAKAT_RE, ""))));
  }
  return tokens.some((tok) =>
    forms.some((m) => {
      if (tok === m) return true;
      let common = 0;
      while (common < Math.min(tok.length, m.length) && tok[common] === m[common]) common += 1;
      return common >= Math.max(4, Math.min(tok.length, m.length) - 3);
    }),
  );
}

function Check({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li style={{ color: ok ? "var(--success)" : "var(--muted)", listStyle: "none" }}>
      <span aria-hidden style={{ marginInlineEnd: 6 }}>{ok ? "✓" : "○"}</span>
      {children}
    </li>
  );
}

export function ExpressionStep({ step, plan, onNext }: StepProps) {
  const t = useT();
  const task = step.task as WritingTask;
  const keyboard = (step.keyboard as WritingKeyboard | null) ?? null;
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const count = countUnits(text, task.length.unit);

  async function send() {
    if (sending) return;
    setSending(true);
    try {
      await api.feuilletonWritingSubmit(plan.run_id, toNfc(text));
    } catch {
      /* la séance continue : rien n'attend la correction */
    }
    onNext();
  }

  const chip = { display: "inline-flex", gap: 6, alignItems: "baseline", padding: "4px 10px", borderRadius: 999, border: "1px solid var(--border)", background: "var(--surface)" } as const;
  return (
    <Card>
      <StepTitle hint={t("feuil.expr.hint")}>{t("feuil.expr.title")}</StepTitle>
      <p style={{ fontWeight: 600, marginTop: 0 }}>{task.prompt}</p>
      {task.use_words.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", marginBottom: 4 }}>{t("feuil.expr.use_words")}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {task.use_words.map((w) => (
              <span key={w.form} style={{ ...chip, borderColor: wordUsed(text, w, plan.family) ? "var(--success)" : "var(--border)" }}>
                <Target rtl={plan.rtl} style={{ fontWeight: 600, fontSize: plan.rtl ? 19 : 15 }}>{w.form}</Target>
                <span style={{ color: "var(--muted)", fontSize: 13 }}>{w.translation}</span>
              </span>
            ))}
          </div>
        </div>
      )}
      {task.use_forms.length > 0 && (
        <p style={{ fontSize: 14, color: "var(--text-soft)", margin: "0 0 10px" }}>
          {t("feuil.expr.use_forms")}{" "}
          {task.use_forms.map((f, i) => (
            <span key={f}>{i > 0 && ", "}<Target rtl={plan.rtl} style={{ fontWeight: 600 }}>{f}</Target></span>
          ))}
        </p>
      )}
      <WritingInput
        value={text}
        onChange={setText}
        lang={String(step.lang ?? "")}
        rtl={plan.rtl}
        keyboard={keyboard}
        maxChars={task.max_chars}
        placeholder={t("feuil.expr.placeholder")}
      />
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginTop: 8 }}>
        <ul style={{ margin: 0, padding: 0, display: "grid", gap: 2, fontSize: 13 }}>
          <Check ok={count >= task.length.min}>
            {t(task.length.unit === "chars" ? "feuil.expr.count_chars" : "feuil.expr.count_words", {
              n: count, min: task.length.min, max: task.length.max,
            })}
          </Check>
          {task.use_words.length > 0 && (
            <Check ok={task.use_words.every((w) => wordUsed(text, w, plan.family))}>{t("feuil.expr.check_words")}</Check>
          )}
        </ul>
      </div>
      {task.bank.length > 0 && (
        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: "pointer", color: "var(--muted)", fontSize: 14 }}>{t("feuil.expr.bank")}</summary>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
            {task.bank.map((w) => (
              <span key={w.form} style={chip}>
                <Target rtl={plan.rtl} style={{ fontSize: plan.rtl ? 18 : 14 }}>{w.form}</Target>
                <span style={{ color: "var(--muted)", fontSize: 12 }}>{w.translation}</span>
              </span>
            ))}
          </div>
        </details>
      )}
      <NextButton label={t("feuil.expr.continue")} onClick={() => void send()} />
    </Card>
  );
}
