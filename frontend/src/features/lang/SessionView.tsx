// features/lang/SessionView.tsx — Rendu interactif d'une session de langue,
// dispatché par render_kind. Chaque type du catalogue retombe sur l'un des 8
// rendus ci-dessous. Les types interactifs (QCM, traduction, production, dictée,
// révision) calculent un score remonté à la clôture (api.languageSessionComplete).
import { useMemo, useRef, useState } from "react";

import { api } from "../../api/client";
import type {
  LangCorrection,
  LangPhoneticDrill,
  LangProductionStep,
  LangQcm,
  LangSession,
  LangSessionContent,
} from "../../api/client";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { useT } from "../../i18n";
import { answersMatch } from "./normalize";

export function SessionView({
  session,
  language,
  onComplete,
}: {
  session: LangSession;
  language: string;
  onComplete: (score: number) => void;
}) {
  const t = useT();
  const scores = useRef<number[]>([]);
  const [finished, setFinished] = useState(false);
  const [finalScore, setFinalScore] = useState(0);

  function onScore(s: number) {
    scores.current.push(Math.max(0, Math.min(1, s)));
  }

  function finish() {
    const arr = scores.current;
    const score = arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 1;
    setFinalScore(score);
    setFinished(true);
    onComplete(score);
  }

  const content = session.content;
  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--accent)", background: "var(--accent-soft)", padding: "3px 10px", borderRadius: 999 }}>
          {t("lang.style_today")} · {session.label}
        </span>
      </div>
      {session.reason && (
        <p style={{ fontSize: 12, color: "var(--muted)", fontStyle: "italic", margin: "0 0 12px" }}>
          {session.reason}
        </p>
      )}

      <KindBody content={content} language={language} onScore={onScore} />

      <div style={{ marginTop: 22, display: "flex", alignItems: "center", gap: 14 }}>
        <button
          onClick={finish}
          disabled={finished}
          style={{ border: "none", background: finished ? "var(--border)" : "var(--success)", color: "#fff", borderRadius: "var(--radius-sm)", padding: "10px 18px", fontWeight: 600, cursor: finished ? "default" : "pointer" }}
        >
          {finished ? t("lang.finished") : t("lang.finish")}
        </button>
        {finished && (
          <span style={{ fontSize: 13, color: "var(--text-soft)" }}>
            {t("lang.session_score")} : <strong>{Math.round(finalScore * 100)}%</strong>
          </span>
        )}
      </div>
    </div>
  );
}

export function KindBody({ content, language, rtl, onScore }: { content: LangSessionContent; language: string; rtl?: boolean; onScore: (s: number) => void }) {
  switch (content.kind) {
    case "dialogue":
      return <DialogueView content={content} rtl={rtl} />;
    case "reading":
      return <ReadingView content={content} rtl={rtl} onScore={onScore} />;
    case "vocabulary":
      return <VocabularyView content={content} rtl={rtl} onScore={onScore} />;
    case "phonetics":
      return <PhoneticsView content={content} rtl={rtl} onScore={onScore} />;
    case "translation":
      return <TranslationView content={content} language={language} onScore={onScore} />;
    case "dictation":
      return <DictationView content={content} language={language} rtl={rtl} onScore={onScore} />;
    case "production":
      return <ProductionView content={content} language={language} onScore={onScore} />;
    case "revision":
      return <RevisionView content={content} language={language} onScore={onScore} />;
    case "writing":
      return <WritingView content={content} rtl={rtl} onScore={onScore} />;
    case "cloze":
      return <ClozeView content={content} language={language} onScore={onScore} />;
    case "ordering":
      return <OrderingView content={content} onScore={onScore} />;
    case "matching":
      return <MatchingView content={content} onScore={onScore} />;
    case "transform":
      return <TransformView content={content} language={language} onScore={onScore} />;
    default:
      return null;
  }
}

// Direction d'écriture du texte CIBLE. "rtl" forcé pour les scripts droite-à-gauche
// (arabe, hébreu) ; sinon "auto" (le navigateur déduit du contenu : latin/cyrillique/
// CJK restent ltr, un texte fortement RTL bascule de lui-même).
function targetDir(rtl?: boolean): "rtl" | "auto" {
  return rtl ? "rtl" : "auto";
}

// Badge de ton (langues tonales : mandarin, thaï…) ; rien si absent.
function ToneBadge({ tone }: { tone?: string }) {
  if (!tone) return null;
  return (
    <span style={{ fontSize: 11, fontWeight: 700, color: "#b45309", background: "#f59e0b22", padding: "1px 6px", borderRadius: 999, marginLeft: 6 }}>
      {tone}
    </span>
  );
}

// ── Primitives partagées ──────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", letterSpacing: 0.4, marginBottom: 8 }}>{title.toUpperCase()}</div>
      {children}
    </div>
  );
}

const VERDICT_COLOR: Record<string, string> = {
  correct: "var(--success)",
  partial: "var(--warning, #c47d00)",
  incorrect: "var(--danger)",
};

// Item à réponse libre corrigé par le LLM (traduction, dictée, production, révision).
function AttemptItem({
  language,
  promptText,
  context,
  expected,
  hint,
  rtl,
  onScore,
  onResult,
  onDone,
}: {
  language: string;
  promptText: string;
  context?: string;
  expected: string;
  hint?: string;
  rtl?: boolean;
  onScore: (s: number) => void;
  onResult?: (r: LangCorrection) => void;
  onDone?: () => void;
}) {
  const t = useT();
  const [value, setValue] = useState("");
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<LangCorrection | null>(null);
  const [revealed, setRevealed] = useState(false);
  const scored = useRef(false);

  async function check() {
    if (checking || !value.trim()) return;
    setChecking(true);
    try {
      const r = await api.languageCorrect(language, expected, value);
      setResult(r);
      if (!r.error && !scored.current) {
        scored.current = true;
        onScore(r.score ?? 0);
        onResult?.(r);
        onDone?.();
      }
    } catch {
      setResult({ verdict: "incorrect", corrections: [], feedback: "", score: 0 });
    } finally {
      setChecking(false);
    }
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12, marginBottom: 10 }}>
      <div style={{ fontWeight: 600, marginBottom: context ? 4 : 8 }}>{promptText}</div>
      {context && <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>{context}</div>}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
        <AutoGrowTextarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onSubmit={check}
          placeholder={t("lang.your_answer")}
          dir="auto"
          style={{ flex: 1, padding: "8px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }}
        />
        <button onClick={check} disabled={checking || !value.trim()} style={{ border: "none", background: "var(--accent)", color: "#fff", borderRadius: "var(--radius-sm)", padding: "8px 14px", fontWeight: 600, cursor: checking ? "default" : "pointer" }}>
          {checking ? t("lang.checking") : t("lang.validate")}
        </button>
      </div>
      {result && !result.error && <CorrectionFeedback result={result} />}
      <div style={{ marginTop: 8, fontSize: 12 }}>
        <button onClick={() => { setRevealed((v) => !v); onDone?.(); }} style={{ border: "none", background: "none", color: "var(--accent)", cursor: "pointer", padding: 0 }}>
          {t("lang.reveal")}
        </button>
        {hint && <span style={{ color: "var(--muted)", marginLeft: 10 }}>💡 {hint}</span>}
        {revealed && (
          <div style={{ marginTop: 4, color: "var(--text-soft)" }}>
            {t("lang.expected")} : <strong dir={targetDir(rtl)}>{expected}</strong>
          </div>
        )}
      </div>
    </div>
  );
}

// Retour de correction LLM (verdict + feedback + corrections catégorisées).
function CorrectionFeedback({ result }: { result: LangCorrection }) {
  const t = useT();
  return (
    <div style={{ marginTop: 8, fontSize: 13 }}>
      <span style={{ fontWeight: 700, color: VERDICT_COLOR[result.verdict] ?? "var(--text)" }}>
        {t(`lang.${result.verdict}`)}
      </span>
      {result.feedback && <span style={{ color: "var(--text-soft)" }}> — {result.feedback}</span>}
      {result.corrections?.map((c, i) => (
        <div key={i} style={{ color: "var(--muted)", marginTop: 2 }}>
          {c.error_type && (
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--accent)", background: "var(--accent-soft)", padding: "1px 6px", borderRadius: 999, marginRight: 6 }}>
              {c.error_type}
            </span>
          )}
          {c.original} → <strong>{c.corrected}</strong>
          {c.reason && ` (${c.reason})`}
        </div>
      ))}
    </div>
  );
}

function QcmItem({ q, onScore }: { q: LangQcm; onScore: (s: number) => void }) {
  const t = useT();
  const [picked, setPicked] = useState<string | null>(null);
  const scored = useRef(false);
  const letters = ["A", "B", "C", "D"];

  function choose(letter: string) {
    if (picked) return;
    setPicked(letter);
    if (!scored.current) {
      scored.current = true;
      onScore(letter === q.correct ? 1 : 0);
    }
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12, marginBottom: 10 }}>
      <div style={{ fontWeight: 600, marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
        {q.depth === "inference" && (
          <span title={t("lang.inference_hint")} style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "#7c3aed", background: "#7c3aed22", padding: "2px 7px", borderRadius: 999 }}>
            🧠 {t("lang.inference")}
          </span>
        )}
        <span>{q.question}</span>
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {q.choices.map((choice, i) => {
          const letter = letters[i];
          const isCorrect = picked && letter === q.correct;
          const isWrongPick = picked === letter && letter !== q.correct;
          return (
            <button
              key={i}
              onClick={() => choose(letter)}
              disabled={!!picked}
              style={{
                textAlign: "left",
                padding: "8px 10px",
                borderRadius: "var(--radius-sm)",
                border: `1px solid ${isCorrect ? "var(--success)" : isWrongPick ? "var(--danger)" : "var(--border)"}`,
                background: isCorrect ? "var(--accent-soft)" : "var(--surface)",
                color: "var(--text)",
                cursor: picked ? "default" : "pointer",
              }}
            >
              {choice}
            </button>
          );
        })}
      </div>
      {picked && (
        <div style={{ marginTop: 8, fontSize: 13 }}>
          <span style={{ fontWeight: 700, color: picked === q.correct ? "var(--success)" : "var(--danger)" }}>
            {t(picked === q.correct ? "lang.correct" : "lang.incorrect")}
          </span>
          {q.explanation && <span style={{ color: "var(--text-soft)" }}> — {q.explanation}</span>}
        </div>
      )}
    </div>
  );
}

// ── 8 rendus par render_kind ──────────────────────────────────────────────────

function DialogueView({ content, rtl }: { content: Extract<LangSessionContent, { kind: "dialogue" }>; rtl?: boolean }) {
  const t = useT();
  const [showPhon, setShowPhon] = useState(true);
  const [showTrans, setShowTrans] = useState(true);
  return (
    <div>
      {content.theme && <div style={{ fontWeight: 700, marginBottom: 10 }}>{content.theme}</div>}
      <div style={{ display: "flex", gap: 14, marginBottom: 10, fontSize: 12 }}>
        <label style={{ cursor: "pointer", color: "var(--text-soft)" }}>
          <input type="checkbox" checked={showPhon} onChange={(e) => setShowPhon(e.target.checked)} /> {t("lang.phonetic")}
        </label>
        <label style={{ cursor: "pointer", color: "var(--text-soft)" }}>
          <input type="checkbox" checked={showTrans} onChange={(e) => setShowTrans(e.target.checked)} /> {t("lang.translation")}
        </label>
      </div>
      <Section title={t("lang.dialogue")}>
        <div style={{ display: "grid", gap: 8 }}>
          {content.dialogue.map((line, i) => (
            <div key={i} style={{ display: "flex", gap: 8 }}>
              <span style={{ fontWeight: 700, color: line.speaker === "A" ? "var(--accent)" : "var(--success)", minWidth: 18 }}>{line.speaker}</span>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ fontWeight: 600 }} dir={targetDir(rtl)}>{line.target}</div>
                </div>
                {showPhon && line.phonetic && <div style={{ fontSize: 12, color: "var(--muted)", fontStyle: "italic" }}>{line.phonetic}</div>}
                {showTrans && line.translation && <div style={{ fontSize: 12, color: "var(--text-soft)" }}>{line.translation}</div>}
              </div>
            </div>
          ))}
        </div>
      </Section>
      {content.vocabulary.length > 0 && (
        <Section title={t("lang.vocab")}>
          <div style={{ display: "grid", gap: 6 }}>
            {content.vocabulary.map((v, i) => (
              <div key={i} style={{ fontSize: 13 }}>
                <strong dir={targetDir(rtl)}>{v.word}</strong> — {v.translation}
                {v.example && <span style={{ color: "var(--muted)" }}> · {v.example}</span>}
              </div>
            ))}
          </div>
        </Section>
      )}
      {(content.notes.grammar || content.notes.pronunciation || content.notes.cultural) && (
        <Section title={t("lang.notes")}>
          <div style={{ display: "grid", gap: 6, fontSize: 13, color: "var(--text-soft)" }}>
            {content.notes.grammar && <div>📐 {content.notes.grammar}</div>}
            {content.notes.pronunciation && <div>🗣 {content.notes.pronunciation}</div>}
            {content.notes.cultural && <div>🌍 {content.notes.cultural}</div>}
          </div>
        </Section>
      )}
    </div>
  );
}

function ReadingView({ content, rtl, onScore }: { content: Extract<LangSessionContent, { kind: "reading" }>; rtl?: boolean; onScore: (s: number) => void }) {
  const t = useT();
  const [showTrans, setShowTrans] = useState(false);
  return (
    <div>
      {content.title && <div style={{ fontWeight: 700, marginBottom: 10 }} dir={targetDir(rtl)}>{content.title}</div>}
      <Section title={t("lang.text")}>
        <p style={{ lineHeight: 1.6 }} dir={targetDir(rtl)}>{content.text_target}</p>
        <button onClick={() => setShowTrans((v) => !v)} style={{ border: "none", background: "none", color: "var(--accent)", cursor: "pointer", padding: 0, fontSize: 12 }}>
          {t("lang.translation")}
        </button>
        {showTrans && <p style={{ color: "var(--text-soft)", fontSize: 13, lineHeight: 1.6 }}>{content.text_translation}</p>}
      </Section>
      {content.glossary.length > 0 && (
        <Section title={t("lang.glossary")}>
          <div style={{ display: "grid", gap: 4, fontSize: 13 }}>
            {content.glossary.map((g, i) => (
              <div key={i}>
                <strong dir={targetDir(rtl)}>{g.word}</strong> — {g.translation}
              </div>
            ))}
          </div>
        </Section>
      )}
      {content.questions.length > 0 && (
        <Section title={t("lang.questions")}>
          {content.questions.map((q, i) => (
            <QcmItem key={i} q={q} onScore={onScore} />
          ))}
        </Section>
      )}
    </div>
  );
}

function VocabularyView({ content, rtl, onScore }: { content: Extract<LangSessionContent, { kind: "vocabulary" }>; rtl?: boolean; onScore: (s: number) => void }) {
  const t = useT();
  return (
    <div>
      <Section title={t("lang.vocab")}>
        <div style={{ display: "grid", gap: 8 }}>
          {content.items.map((it, i) => (
            <div key={i} style={{ fontSize: 13 }}>
              <strong dir={targetDir(rtl)}>{it.word}</strong>
              {it.phonetic && <span style={{ color: "var(--muted)", fontStyle: "italic" }}> [{it.phonetic}]</span>}
              <ToneBadge tone={it.tone} /> — {it.translation}
              {it.example_target && (
                <div style={{ color: "var(--muted)", fontStyle: "italic" }} dir={targetDir(rtl)}>
                  {it.example_target}
                  {it.example_translation && <span style={{ color: "var(--text-soft)" }}> · {it.example_translation}</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      </Section>
      {content.questions.length > 0 && (
        <Section title={t("lang.questions")}>
          {content.questions.map((q, i) => (
            <QcmItem key={i} q={q} onScore={onScore} />
          ))}
        </Section>
      )}
    </div>
  );
}

function PhoneticsView({ content, rtl, onScore }: { content: Extract<LangSessionContent, { kind: "phonetics" }>; rtl?: boolean; onScore: (s: number) => void }) {
  const t = useT();
  return (
    <div>
      <Section title={t("lang.focus_sound")}>
        <div style={{ fontWeight: 700, fontSize: 18 }}>{content.focus_sound}</div>
        {content.explanation && <p style={{ color: "var(--text-soft)", fontSize: 13 }}>{content.explanation}</p>}
      </Section>
      {content.minimal_pairs.length > 0 && (
        <Section title={t("lang.minimal_pairs")}>
          <div style={{ display: "grid", gap: 6 }}>
            {content.minimal_pairs.map((p, i) => (
              <div key={i} style={{ fontSize: 13 }}>
                <strong dir={targetDir(rtl)}>{p.a}</strong> / <strong dir={targetDir(rtl)}>{p.b}</strong>
                {p.note && <span style={{ color: "var(--muted)" }}> — {p.note}</span>}
              </div>
            ))}
          </div>
        </Section>
      )}
      {content.drills.length > 0 && (
        <Section title={t("lang.drills")}>
          <div style={{ display: "grid", gap: 10 }}>
            {content.drills.map((d, i) => {
              if (d.kind === "stress") return <StressDrill key={i} drill={d} onScore={onScore} />;
              if (d.kind === "spell_to_sound") return <SpellToSoundDrill key={i} drill={d} onScore={onScore} />;
              return (
                <div key={i}>
                  <div style={{ fontWeight: 600 }} dir={targetDir(rtl)}>{d.target}</div>
                  {(d.phonetic || d.tone) && (
                    <div style={{ fontSize: 12, color: "var(--muted)", fontStyle: "italic" }}>
                      {d.phonetic}
                      <ToneBadge tone={d.tone} />
                    </div>
                  )}
                  {d.translation && <div style={{ fontSize: 12, color: "var(--text-soft)" }}>{d.translation}</div>}
                </div>
              );
            })}
          </div>
        </Section>
      )}
    </div>
  );
}

// Drill « accent tonique » : l'apprenant clique la syllabe accentuée (corrigé client).
function StressDrill({ drill, onScore }: { drill: Extract<LangPhoneticDrill, { kind: "stress" }>; onScore: (s: number) => void }) {
  const t = useT();
  const [picked, setPicked] = useState<number | null>(null);
  const scored = useRef(false);
  function pick(i: number) {
    if (picked !== null) return;
    setPicked(i);
    if (!scored.current) {
      scored.current = true;
      onScore(i === drill.stressed_index ? 1 : 0);
    }
  }
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12 }}>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>{t("lang.stress_task")}</div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {drill.syllables.map((syl, i) => {
          const isAnswer = picked !== null && i === drill.stressed_index;
          const isWrong = picked === i && i !== drill.stressed_index;
          return (
            <button key={i} onClick={() => pick(i)} disabled={picked !== null}
              style={{ padding: "6px 12px", borderRadius: "var(--radius-sm)", border: `1px solid ${isAnswer ? "var(--success)" : isWrong ? "var(--danger)" : "var(--border)"}`, background: isAnswer ? "var(--accent-soft)" : "var(--surface)", color: "var(--text)", fontWeight: 600, cursor: picked !== null ? "default" : "pointer" }}>
              {syl}
            </button>
          );
        })}
      </div>
      {drill.translation && <div style={{ fontSize: 12, color: "var(--text-soft)", marginTop: 6 }}>{drill.translation}</div>}
    </div>
  );
}

// Drill « graphie → son » : QCM sur la transcription correcte (corrigé client).
function SpellToSoundDrill({ drill, onScore }: { drill: Extract<LangPhoneticDrill, { kind: "spell_to_sound" }>; onScore: (s: number) => void }) {
  const t = useT();
  const [picked, setPicked] = useState<number | null>(null);
  const scored = useRef(false);
  function pick(i: number) {
    if (picked !== null) return;
    setPicked(i);
    if (!scored.current) {
      scored.current = true;
      onScore(i === drill.answer ? 1 : 0);
    }
  }
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12 }}>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>{t("lang.spell_task")}</div>
      <div style={{ fontWeight: 700, marginBottom: 8 }}>{drill.written}</div>
      <div style={{ display: "grid", gap: 6 }}>
        {drill.options.map((opt, i) => {
          const isAnswer = picked !== null && i === drill.answer;
          const isWrong = picked === i && i !== drill.answer;
          return (
            <button key={i} onClick={() => pick(i)} disabled={picked !== null}
              style={{ textAlign: "left", padding: "8px 10px", borderRadius: "var(--radius-sm)", border: `1px solid ${isAnswer ? "var(--success)" : isWrong ? "var(--danger)" : "var(--border)"}`, background: isAnswer ? "var(--accent-soft)" : "var(--surface)", color: "var(--text)", fontFamily: "var(--font-mono, monospace)", cursor: picked !== null ? "default" : "pointer" }}>
              {opt}
            </button>
          );
        })}
      </div>
      {drill.translation && <div style={{ fontSize: 12, color: "var(--text-soft)", marginTop: 6 }}>{drill.translation}</div>}
    </div>
  );
}

function TranslationView({ content, language, onScore }: { content: Extract<LangSessionContent, { kind: "translation" }>; language: string; onScore: (s: number) => void }) {
  const t = useT();
  return (
    <Section title={t("lang.translation")}>
      {content.items.map((it, i) => (
        <AttemptItem key={i} language={language} promptText={it.prompt_fr} expected={it.expected} hint={it.hint} onScore={onScore} />
      ))}
    </Section>
  );
}

function DictationView({ content, language, rtl, onScore }: { content: Extract<LangSessionContent, { kind: "dictation" }>; language: string; rtl?: boolean; onScore: (s: number) => void }) {
  const t = useT();
  return (
    <Section title={t("lang.dialogue")}>
      <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 0 }}>{t("lang.dictation_hint")}</p>
      {content.segments.map((s, i) => (
        <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
          <div style={{ flex: 1 }}>
            <AttemptItem language={language} promptText={`${t("lang.next_segment")} ${i + 1}`} context={s.phonetic || undefined} expected={s.target} hint={s.translation} rtl={rtl} onScore={onScore} />
          </div>
        </div>
      ))}
    </Section>
  );
}

function ProductionView({ content, language, onScore }: { content: Extract<LangSessionContent, { kind: "production" }>; language: string; onScore: (s: number) => void }) {
  const t = useT();
  const twoStep = content.mode === "two_step" || Boolean(content.guided) || Boolean(content.free);
  return (
    <div>
      {content.instructions && (
        <Section title={t("lang.instructions")}>
          <p style={{ color: "var(--text-soft)", fontSize: 13 }}>{content.instructions}</p>
        </Section>
      )}
      {twoStep ? (
        <ProductionTwoStep content={content} language={language} onScore={onScore} />
      ) : (
        <div style={{ marginTop: 12 }}>
          {(content.tasks ?? []).map((task, i) => (
            <AttemptItem key={i} language={language} promptText={task.prompt} context={task.context || undefined} expected={task.reference} hint={task.hint} onScore={onScore} />
          ))}
        </div>
      )}
    </div>
  );
}

// Production en 2 paliers (Axe 2) : guidé (échafaudage) → libre (production réelle).
// Le palier libre offre UNE reprise sur verdict "partial" ; score retenu = le meilleur
// des deux (l'apprenant agit sur le feedback au lieu de le subir).
function ProductionTwoStep({ content, language, onScore }: { content: Extract<LangSessionContent, { kind: "production" }>; language: string; onScore: (s: number) => void }) {
  const t = useT();
  const [guidedDone, setGuidedDone] = useState(!content.guided);
  return (
    <div style={{ marginTop: 12 }}>
      {content.guided && (
        <div>
          <StepLabel n={1} text={t("lang.step_guided")} />
          <AttemptItem
            language={language}
            promptText={content.guided.prompt}
            expected={content.guided.expected ?? ""}
            hint={content.guided.hint}
            onScore={onScore}
            onDone={() => setGuidedDone(true)}
          />
        </div>
      )}
      {guidedDone && content.free && (
        <div>
          <StepLabel n={content.guided ? 2 : 1} text={t("lang.step_free")} />
          <FreeProductionItem step={content.free} language={language} onScore={onScore} />
        </div>
      )}
    </div>
  );
}

function StepLabel({ n, text }: { n: number; text: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0 6px" }}>
      <span style={{ width: 20, height: 20, borderRadius: 999, background: "var(--accent)", color: "#fff", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{n}</span>
      <span style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", letterSpacing: 0.3 }}>{text}</span>
    </div>
  );
}

// Palier libre avec UNE reprise sur "partial" (meilleur des deux scores).
function FreeProductionItem({ step, language, onScore }: { step: LangProductionStep; language: string; onScore: (s: number) => void }) {
  const t = useT();
  const [value, setValue] = useState("");
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<LangCorrection | null>(null);
  const [attempt, setAttempt] = useState(0);     // 0 = 1er essai, 1 = reprise
  const [canRetry, setCanRetry] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const best = useRef(0);
  const finalized = useRef(false);

  function finalize(score: number) {
    if (finalized.current) return;
    finalized.current = true;
    onScore(score);
  }

  async function check() {
    if (checking || !value.trim()) return;
    setChecking(true);
    try {
      const r = await api.languageCorrect(language, step.reference ?? "", value);
      setResult(r);
      const sc = r.error ? 0 : (r.score ?? 0);
      best.current = Math.max(best.current, sc);
      if (r.verdict === "partial" && attempt === 0) {
        setCanRetry(true);              // on propose UNE reprise, on ne fige pas encore
      } else {
        finalize(best.current);          // correct/incorrect, ou 2e essai → score retenu
      }
    } catch {
      setResult({ verdict: "incorrect", corrections: [], feedback: "", score: 0 });
    } finally {
      setChecking(false);
    }
  }

  function retry() {
    setAttempt(1);
    setCanRetry(false);
    setResult(null);
    setValue("");
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12, marginBottom: 10 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>{step.prompt}</div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
        <AutoGrowTextarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onSubmit={check}
          placeholder={t("lang.your_answer")}
          dir="auto"
          style={{ flex: 1, padding: "8px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)" }}
        />
        <button onClick={check} disabled={checking || !value.trim()} style={{ border: "none", background: "var(--accent)", color: "#fff", borderRadius: "var(--radius-sm)", padding: "8px 14px", fontWeight: 600, cursor: checking ? "default" : "pointer" }}>
          {checking ? t("lang.checking") : t("lang.validate")}
        </button>
      </div>
      {result && !result.error && <CorrectionFeedback result={result} />}
      {canRetry && (
        <button onClick={retry} style={{ marginTop: 10, border: "1px solid var(--accent)", background: "var(--accent-soft)", color: "var(--accent)", borderRadius: "var(--radius-sm)", padding: "7px 14px", fontWeight: 600, cursor: "pointer" }}>
          ↻ {t("lang.retry_improve")}
        </button>
      )}
      <div style={{ marginTop: 8, fontSize: 12 }}>
        <button onClick={() => setRevealed((v) => !v)} style={{ border: "none", background: "none", color: "var(--accent)", cursor: "pointer", padding: 0 }}>
          {t("lang.reveal")}
        </button>
        {step.hint && <span style={{ color: "var(--muted)", marginLeft: 10 }}>💡 {step.hint}</span>}
        {revealed && step.reference && (
          <div style={{ marginTop: 4, color: "var(--text-soft)" }}>
            {t("lang.model_answer")} : <strong>{step.reference}</strong>
          </div>
        )}
      </div>
    </div>
  );
}

function RevisionView({ content, language, onScore }: { content: Extract<LangSessionContent, { kind: "revision" }>; language: string; onScore: (s: number) => void }) {
  const t = useT();
  return (
    <Section title={t("lang.translation")}>
      {content.exercises.map((ex, i) => (
        <AttemptItem
          key={i}
          language={language}
          promptText={ex.prompt_fr}
          expected={ex.expected}
          hint={ex.hint || ex.target_word}
          onScore={onScore}
          onResult={(r) => {
            // Bouclage du pont SR : repousse/rapproche l'échéance de la carte révisée.
            const target = ex.target_word || ex.expected;
            if (ex.card_id || target) {
              void api.languageReviewCard(language, r.verdict, { cardId: ex.card_id, word: target });
            }
          }}
        />
      ))}
    </Section>
  );
}

function WritingView({ content, rtl, onScore }: { content: Extract<LangSessionContent, { kind: "writing" }>; rtl?: boolean; onScore: (s: number) => void }) {
  const t = useT();
  return (
    <div>
      {content.intro && <p style={{ color: "var(--text-soft)", fontSize: 13 }}>{content.intro}</p>}
      {content.signs.length > 0 && (
        <Section title={t("lang.signs")}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8 }}>
            {content.signs.map((s, i) => (
              <div key={i} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "10px 12px" }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 26, fontWeight: 700 }} dir={targetDir(rtl)}>{s.sign}</span>
                  {s.translit && <span style={{ fontSize: 13, color: "var(--muted)" }}>[{s.translit}]</span>}
                  <ToneBadge tone={s.tone} />
                </div>
                {(s.name || s.sound) && (
                  <div style={{ fontSize: 12, color: "var(--text-soft)" }}>
                    {s.name}
                    {s.sound && ` · ${s.sound}`}
                  </div>
                )}
                {s.example_word && (
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    <strong dir={targetDir(rtl)}>{s.example_word}</strong>
                    {s.example_translit && <span style={{ color: "var(--muted)" }}> [{s.example_translit}]</span>}
                    {s.example_translation && <span style={{ color: "var(--text-soft)" }}> — {s.example_translation}</span>}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}
      {content.reading.length > 0 && (
        <Section title={t("lang.reading")}>
          <div style={{ display: "grid", gap: 6 }}>
            {content.reading.map((r, i) => (
              <div key={i} style={{ fontSize: 14 }}>
                <strong dir={targetDir(rtl)}>{r.target}</strong>
                {r.translit && <span style={{ color: "var(--muted)" }}> [{r.translit}]</span>}
                {r.translation && <span style={{ color: "var(--text-soft)" }}> — {r.translation}</span>}
              </div>
            ))}
          </div>
        </Section>
      )}
      {content.drill.length > 0 && (
        <Section title={t("lang.questions")}>
          {content.drill.map((q, i) => (
            <QcmItem key={i} q={q} onScore={onScore} />
          ))}
        </Section>
      )}
    </div>
  );
}

// ── Types interactifs (correction côté client) ────────────────────────────────

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const PILL_OK = "var(--success)";
const PILL_KO = "var(--danger)";

// cloze : complétion à trous (banque de mots ou saisie libre).
function ClozeView({ content, language, onScore }: { content: Extract<LangSessionContent, { kind: "cloze" }>; language: string; onScore: (s: number) => void }) {
  const t = useT();
  return (
    <div>
      <Section title={content.mode === "bank" ? t("lang.cloze_bank") : t("lang.cloze_free")}>
        {content.instructions && <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 0 }}>{content.instructions}</p>}
        {content.sentences.map((s, i) => (
          <ClozeSentence key={i} sentence={s} mode={content.mode} language={language} onScore={onScore} />
        ))}
      </Section>
    </div>
  );
}

function ClozeSentence({ sentence, mode, language, onScore }: { sentence: Extract<LangSessionContent, { kind: "cloze" }>["sentences"][number]; mode: "bank" | "free"; language: string; onScore: (s: number) => void }) {
  const t = useT();
  const parts = useMemo(() => sentence.text.split("___"), [sentence.text]);
  const options = useMemo(() => (sentence.options ? shuffle(sentence.options) : []), [sentence.options]);
  const [answers, setAnswers] = useState<string[]>(() => sentence.blanks.map(() => ""));
  const [verdict, setVerdict] = useState<boolean[] | null>(null);
  const [checking, setChecking] = useState(false);
  const scored = useRef(false);

  function setAt(i: number, v: string) {
    setAnswers((a) => a.map((x, k) => (k === i ? v : x)));
  }

  async function check() {
    if (checking || scored.current) return;
    setChecking(true);
    const results: boolean[] = [];
    for (let i = 0; i < sentence.blanks.length; i++) {
      const expected = sentence.blanks[i];
      const given = answers[i] ?? "";
      let ok = answersMatch(given, expected);
      // Saisie libre : tolérance LLM en SECOND recours uniquement (synonymes/variantes).
      if (!ok && mode === "free" && given.trim()) {
        try {
          const r = await api.languageCorrect(language, expected, given);
          ok = !r.error && r.verdict !== "incorrect";
        } catch { /* repli : reste faux */ }
      }
      results.push(ok);
    }
    setVerdict(results);
    if (!scored.current) {
      scored.current = true;
      onScore(results.filter(Boolean).length / (results.length || 1));
    }
    setChecking(false);
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12, marginBottom: 10 }}>
      <div style={{ lineHeight: 2 }}>
        {parts.map((part, i) => (
          <span key={i}>
            <span dir="auto">{part}</span>
            {i < sentence.blanks.length && (
              mode === "bank" ? (
                <select
                  value={answers[i]}
                  disabled={verdict !== null}
                  onChange={(e) => setAt(i, e.target.value)}
                  style={{ margin: "0 4px", padding: "2px 6px", borderRadius: "var(--radius-sm)", border: `1px solid ${verdict ? (verdict[i] ? PILL_OK : PILL_KO) : "var(--accent)"}`, background: "var(--surface)", color: "var(--text)" }}
                >
                  <option value="">— ? —</option>
                  {options.map((o, k) => <option key={k} value={o}>{o}</option>)}
                </select>
              ) : (
                <input
                  value={answers[i]}
                  disabled={verdict !== null}
                  onChange={(e) => setAt(i, e.target.value)}
                  dir="auto"
                  style={{ margin: "0 4px", width: 110, padding: "2px 6px", borderRadius: "var(--radius-sm)", border: `1px solid ${verdict ? (verdict[i] ? PILL_OK : PILL_KO) : "var(--accent)"}`, background: "var(--surface)", color: "var(--text)" }}
                />
              )
            )}
          </span>
        ))}
      </div>
      {sentence.translation && <div style={{ fontSize: 12, color: "var(--text-soft)", marginTop: 6 }}>{sentence.translation}</div>}
      <div style={{ marginTop: 8 }}>
        {verdict === null ? (
          <button onClick={check} disabled={checking} style={smallBtn}>{checking ? t("lang.checking") : t("lang.validate")}</button>
        ) : (
          <span style={{ fontSize: 13, fontWeight: 700, color: verdict.every(Boolean) ? PILL_OK : PILL_KO }}>
            {verdict.filter(Boolean).length}/{verdict.length} — {sentence.blanks.join(" · ")}
          </span>
        )}
      </div>
    </div>
  );
}

// ordering : remise en ordre / construction depuis fragments (corrigé client).
function OrderingView({ content, onScore }: { content: Extract<LangSessionContent, { kind: "ordering" }>; onScore: (s: number) => void }) {
  const t = useT();
  return (
    <Section title={content.task || t("lang.ordering_task")}>
      {content.items.map((it, i) => <OrderingItem key={i} item={it} onScore={onScore} />)}
    </Section>
  );
}

function OrderingItem({ item, onScore }: { item: Extract<LangSessionContent, { kind: "ordering" }>["items"][number]; onScore: (s: number) => void }) {
  const t = useT();
  const shuffled = useMemo(() => shuffle(item.tokens.map((tok, id) => ({ tok, id }))), [item]);
  const [placed, setPlaced] = useState<number[]>([]);
  const [verdict, setVerdict] = useState<boolean | null>(null);
  const scored = useRef(false);
  const remaining = shuffled.filter((s) => !placed.includes(s.id));

  function check() {
    if (scored.current) return;
    const built = placed.map((id) => item.tokens[id]).join(" ");
    const ok = answersMatch(built, item.solution.join(" "));
    setVerdict(ok);
    scored.current = true;
    onScore(ok ? 1 : 0);
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12, marginBottom: 10 }}>
      <div style={{ minHeight: 36, display: "flex", flexWrap: "wrap", gap: 6, padding: 6, border: "1px dashed var(--border)", borderRadius: "var(--radius-sm)", marginBottom: 8 }}>
        {placed.length === 0 && <span style={{ color: "var(--muted)", fontSize: 12 }}>{t("lang.ordering_hint")}</span>}
        {placed.map((id, idx) => (
          <button key={idx} dir="auto" onClick={() => verdict === null && setPlaced((p) => p.filter((_, k) => k !== idx))} style={{ ...chip, borderColor: verdict === null ? "var(--accent)" : verdict ? PILL_OK : PILL_KO }}>
            {item.tokens[id]}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {remaining.map((s) => (
          <button key={s.id} dir="auto" onClick={() => verdict === null && setPlaced((p) => [...p, s.id])} style={chip}>{s.tok}</button>
        ))}
      </div>
      <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 10 }}>
        {verdict === null ? (
          <button onClick={check} disabled={placed.length !== item.tokens.length} style={smallBtn}>{t("lang.validate")}</button>
        ) : (
          <span style={{ fontSize: 13 }}>
            <span style={{ fontWeight: 700, color: verdict ? PILL_OK : PILL_KO }}>{t(verdict ? "lang.correct" : "lang.incorrect")}</span>
            {!verdict && <span style={{ color: "var(--text-soft)" }}> — {item.solution.join(" ")}</span>}
          </span>
        )}
        {item.translation && <span style={{ fontSize: 12, color: "var(--muted)" }}>{item.translation}</span>}
      </div>
    </div>
  );
}

// matching : appariement (relier chaque mot à sa traduction), corrigé client.
function MatchingView({ content, onScore }: { content: Extract<LangSessionContent, { kind: "matching" }>; onScore: (s: number) => void }) {
  const t = useT();
  const rights = useMemo(() => shuffle(content.pairs.map((p) => p.right)), [content.pairs]);
  const [picks, setPicks] = useState<string[]>(() => content.pairs.map(() => ""));
  const [verdict, setVerdict] = useState<boolean[] | null>(null);
  const scored = useRef(false);

  function check() {
    if (scored.current) return;
    const results = content.pairs.map((p, i) => answersMatch(picks[i] ?? "", p.right));
    setVerdict(results);
    scored.current = true;
    onScore(results.filter(Boolean).length / (results.length || 1));
  }

  return (
    <Section title={content.task || t("lang.matching_task")}>
      <div style={{ display: "grid", gap: 8 }}>
        {content.pairs.map((p, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontWeight: 600, minWidth: 140 }} dir="auto">{p.left}</span>
            <span style={{ color: "var(--muted)" }}>→</span>
            <select
              value={picks[i]}
              disabled={verdict !== null}
              onChange={(e) => setPicks((a) => a.map((x, k) => (k === i ? e.target.value : x)))}
              style={{ flex: 1, padding: "6px 8px", borderRadius: "var(--radius-sm)", border: `1px solid ${verdict ? (verdict[i] ? PILL_OK : PILL_KO) : "var(--border)"}`, background: "var(--surface)", color: "var(--text)" }}
            >
              <option value="">— ? —</option>
              {rights.map((r, k) => <option key={k} value={r}>{r}</option>)}
            </select>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10 }}>
        {verdict === null ? (
          <button onClick={check} disabled={picks.some((p) => !p)} style={smallBtn}>{t("lang.validate")}</button>
        ) : (
          <span style={{ fontSize: 13, fontWeight: 700, color: verdict.every(Boolean) ? PILL_OK : PILL_KO }}>
            {verdict.filter(Boolean).length}/{verdict.length}
          </span>
        )}
      </div>
    </Section>
  );
}

// transform : conjugaison / transformation guidée (client-first, tolérance LLM).
function TransformView({ content, language, onScore }: { content: Extract<LangSessionContent, { kind: "transform" }>; language: string; onScore: (s: number) => void }) {
  const t = useT();
  return (
    <Section title={content.task || t("lang.transform_task")}>
      {content.items.map((it, i) => <TransformItem key={i} item={it} language={language} onScore={onScore} />)}
    </Section>
  );
}

function TransformItem({ item, language, onScore }: { item: Extract<LangSessionContent, { kind: "transform" }>["items"][number]; language: string; onScore: (s: number) => void }) {
  const t = useT();
  const [value, setValue] = useState("");
  const [checking, setChecking] = useState(false);
  const [verdict, setVerdict] = useState<boolean | null>(null);
  const [revealed, setRevealed] = useState(false);
  const scored = useRef(false);

  async function check() {
    if (checking || scored.current || !value.trim()) return;
    let ok = answersMatch(value, item.expected);
    if (!ok) {
      setChecking(true);
      try {
        const r = await api.languageCorrect(language, item.expected, value);
        ok = !r.error && r.verdict !== "incorrect";
      } catch { /* repli : reste faux */ }
      setChecking(false);
    }
    setVerdict(ok);
    scored.current = true;
    onScore(ok ? 1 : 0);
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 12, marginBottom: 10 }}>
      <div style={{ fontWeight: 600 }} dir="auto">{item.source}</div>
      {item.focus && <div style={{ fontSize: 12, color: "var(--accent)", marginBottom: 6 }}>→ {item.focus}</div>}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
        <AutoGrowTextarea
          value={value}
          disabled={verdict !== null}
          onChange={(e) => setValue(e.target.value)}
          onSubmit={check}
          placeholder={t("lang.your_answer")}
          dir="auto"
          style={{ flex: 1, padding: "8px 10px", borderRadius: "var(--radius-sm)", border: `1px solid ${verdict === null ? "var(--border)" : verdict ? PILL_OK : PILL_KO}`, background: "var(--surface)", color: "var(--text)" }}
        />
        {verdict === null && (
          <button onClick={check} disabled={checking || !value.trim()} style={smallBtn}>{checking ? t("lang.checking") : t("lang.validate")}</button>
        )}
      </div>
      {verdict !== null && (
        <div style={{ marginTop: 6, fontSize: 13 }}>
          <span style={{ fontWeight: 700, color: verdict ? PILL_OK : PILL_KO }}>{t(verdict ? "lang.correct" : "lang.incorrect")}</span>
          {!verdict && <span style={{ color: "var(--text-soft)" }} dir="auto"> — {item.expected}</span>}
        </div>
      )}
      <div style={{ marginTop: 8, fontSize: 12 }}>
        <button onClick={() => setRevealed((v) => !v)} style={{ border: "none", background: "none", color: "var(--accent)", cursor: "pointer", padding: 0 }}>
          {t("lang.reveal")}
        </button>
        {item.hint && <span style={{ color: "var(--muted)", marginLeft: 10 }}>💡 {item.hint}</span>}
        {revealed && <div style={{ marginTop: 4, color: "var(--text-soft)" }}>{t("lang.expected")} : <strong dir="auto">{item.expected}</strong></div>}
      </div>
    </div>
  );
}

const smallBtn: React.CSSProperties = {
  border: "none", background: "var(--accent)", color: "#fff",
  borderRadius: "var(--radius-sm)", padding: "7px 14px", fontWeight: 600, cursor: "pointer",
};

const chip: React.CSSProperties = {
  padding: "6px 12px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)",
  background: "var(--surface)", color: "var(--text)", fontWeight: 600, cursor: "pointer",
};
