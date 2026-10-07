// WritingFeedback — La correction de l'expression écrite, écrite par Clikoda.
//
// Les passages relevés sont surlignés dans le texte de l'apprenant (chacun est
// un passage EXACT de son texte : le serveur l'a vérifié), avec leur
// correction, leur type et une explication courte ; puis le texte corrigé.
// Aucune note, aucun score : le verdict dit seulement si le sens passe.
import type { WritingFeedbackData, WritingView } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { ProLine } from "./ProNote";
import { StepTitle, Target } from "./ui";

/** « ordre des mots » → ordre_des_mots, « préposition » → preposition : la clé i18n du type. */
function slug(errorType: string): string {
  return errorType.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[\s-]+/g, "_");
}

/** Le texte de l'apprenant, ses passages relevés surlignés (premières occurrences, sans chevauchement). */
function Marked({ text, feedback, rtl }: { text: string; feedback: WritingFeedbackData; rtl: boolean }) {
  const spans: { start: number; end: number }[] = [];
  for (const e of feedback.errors) {
    const start = text.indexOf(e.original);
    if (start < 0) continue;
    const end = start + e.original.length;
    if (!spans.some((s) => start < s.end && end > s.start)) spans.push({ start, end });
  }
  spans.sort((a, b) => a.start - b.start);
  const parts: React.ReactNode[] = [];
  let at = 0;
  spans.forEach((s, i) => {
    if (s.start > at) parts.push(text.slice(at, s.start));
    parts.push(
      <mark key={i} style={{ background: "var(--warning-soft)", color: "inherit", borderRadius: 3 }}>
        {text.slice(s.start, s.end)}
      </mark>,
    );
    at = s.end;
  });
  parts.push(text.slice(at));
  return <Target rtl={rtl} style={{ fontSize: rtl ? 22 : 17, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>{parts}</Target>;
}

export function WritingFeedback({ writing, rtl }: { writing: WritingView; rtl: boolean }) {
  const t = useT();
  const feedback = writing.feedback;
  if (!feedback) return null;
  const label = { fontSize: 12, fontWeight: 700, textTransform: "uppercase" as const, color: "var(--muted)", margin: "12px 0 4px" };
  return (
    <section aria-label={t("feuil.correction.title")}>
      <StepTitle hint={t(`feuil.correction.verdict.${feedback.verdict}`)}>{t("feuil.correction.title")}</StepTitle>
      {feedback.praise && <p style={{ marginTop: -4 }}>{feedback.praise}</p>}
      <div style={label}>{t("feuil.correction.your_text")}</div>
      <Marked text={writing.text} feedback={feedback} rtl={rtl} />
      {feedback.errors.length > 0 && (
        <ul style={{ margin: "10px 0 0", paddingInlineStart: 20, display: "grid", gap: 8 }}>
          {feedback.errors.map((e, i) => (
            <li key={i}>
              <Target rtl={rtl} style={{ textDecoration: "line-through", color: "var(--danger)" }}>{e.original}</Target>
              {" → "}
              <Target rtl={rtl} style={{ fontWeight: 600 }}>{e.correction}</Target>
              <span style={{ color: "var(--muted)", fontSize: 12 }}> · {t(`feuil.correction.type.${slug(e.error_type)}`)}</span>
              {e.explanation && <div style={{ color: "var(--text-soft)", fontSize: 14 }}>{e.explanation}</div>}
            </li>
          ))}
        </ul>
      )}
      <div style={label}>{t("feuil.correction.corrected")}</div>
      <Target rtl={rtl} style={{ fontSize: rtl ? 22 : 17, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>{feedback.corrected}</Target>
      <ProLine reason="writing" />
    </section>
  );
}
