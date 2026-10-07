// Steps — Une vue par étape de séance (plan § 10.2, F2-F10).
//
// Chaque vue reçoit son étape telle que le serveur l'a assemblée
// (services/lang_runs.build_plan) et remonte ce que fait l'apprenant par le
// tracker de séance. Aucune ne calcule de score : la lecture n'est jamais notée.
// La lecture, la leçon et l'expression écrite ont leur fichier (Lecture.tsx,
// Lecon.tsx, Expression.tsx) ; ici, les autres étapes et les aides partagées.
import { useState } from "react";

import { api } from "../../../api/client";
import type {
  DiffOp,
  DueCard,
  EpisodeView,
  Game,
  GameItem,
  PointView,
  RunPlan,
  RunStep,
} from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { EpisodeText } from "./EpisodeText";
import { GameList } from "./Games";
import type { RunTracker } from "./useRunTracker";
import { Card, chipBtn, ghostBtn, primaryBtn, StepTitle, Target } from "./ui";

export interface StepProps {
  step: RunStep;
  plan: RunPlan;
  tracker: RunTracker;
  /** Passe à l'étape suivante ; `signal` = compris / à peu près / pas compris. */
  onNext: (extra?: { signal?: string | null; feeling?: string | null }) => void;
}

export function episodeOf(plan: RunPlan, ref: unknown): EpisodeView | undefined {
  return ref === null || ref === undefined ? undefined : plan.episodes[String(ref)];
}

export function NextButton({ onClick, label }: { onClick: () => void; label?: string }) {
  const t = useT();
  return (
    <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
      <button style={primaryBtn} onClick={onClick}>{label ?? t("feuil.next")}</button>
    </div>
  );
}

export function answerFor(tracker: RunTracker) {
  return (item: GameItem, given: unknown, ms: number) => tracker.push({ type: "answer", item: item.ref, given, ms });
}

export function revealFor(tracker: RunTracker, episode: EpisodeView, pass: string) {
  return (line: number, token: number) => tracker.push({ type: "reveal", episode_id: episode.id, line, token, pass });
}

// ── Accueil, phrases de survie, écriture (séance zéro, reprise) ───────────────

export function AccueilStep({ step, plan, onNext }: StepProps) {
  const t = useT();
  if (step.variant === "reprise") {
    return (
      <Card>
        <StepTitle>{t("feuil.reprise.title")}</StepTitle>
        <p>{t(`feuil.reprise.${plan.tone}`, { days: String(plan.absence.days ?? "") })}</p>
        <p style={{ color: "var(--muted)" }}>{t("feuil.reprise.no_new")}</p>
        <NextButton onClick={() => onNext()} />
      </Card>
    );
  }
  return (
    <Card>
      <StepTitle>{t("feuil.zero.title")}</StepTitle>
      <p>{t("feuil.zero.method")}</p>
      <p>{t("feuil.zero.daily")}</p>
      <p style={{ color: "var(--muted)" }}>{t("feuil.zero.writing")}</p>
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

export function PhrasesStep({ step, plan, onNext }: StepProps) {
  const t = useT();
  const phrases = (step.phrases as { target: string; translation: string; pron?: string; note?: string }[]) ?? [];
  const [shown, setShown] = useState<Set<number>>(new Set());
  return (
    <Card>
      <StepTitle hint={step.waiting ? t("feuil.phrases.waiting") : t("feuil.phrases.hint")}>{t("feuil.phrases.title")}</StepTitle>
      <div style={{ display: "grid", gap: 10 }}>
        {phrases.map((ph, i) => (
          <button
            key={i}
            onClick={() => setShown((s) => new Set(s).add(i))}
            style={{ ...ghostBtn, textAlign: plan.rtl ? "right" : "left", display: "grid", gap: 2, fontWeight: 500 }}
          >
            <Target rtl={plan.rtl} style={{ fontSize: plan.rtl ? 24 : 18 }}>{ph.target}</Target>
            {ph.pron && <span style={{ color: "var(--muted)", fontSize: 13 }}>{ph.pron}</span>}
            <span style={{ color: "var(--text-soft)", fontStyle: "italic", visibility: shown.has(i) ? "visible" : "hidden" }}>
              {ph.translation}
            </span>
          </button>
        ))}
      </div>
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

export function EcritureStep({ step, plan, onNext }: StepProps) {
  const t = useT();
  const preview = (step.preview as { intro?: string; aids?: string; items?: { sign: string; name?: string; note?: string }[] }) ?? {};
  return (
    <Card>
      <StepTitle>{t("feuil.writing.title")}</StepTitle>
      {preview.intro && <p>{preview.intro}</p>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, margin: "10px 0" }}>
        {(preview.items ?? []).map((it, i) => (
          <div key={i} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: 10, minWidth: 90, textAlign: "center" }}>
            <Target rtl={plan.rtl} style={{ fontSize: 34 }}>{it.sign}</Target>
            {it.name && <div style={{ fontWeight: 600 }}>{it.name}</div>}
            {it.note && <div style={{ color: "var(--muted)", fontSize: 12 }}>{it.note}</div>}
          </div>
        ))}
      </div>
      {preview.aids && <p style={{ color: "var(--muted)" }}>{preview.aids}</p>}
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

// ── Rappel et passages de l'épisode ───────────────────────────────────────────

export function RappelStep({ step, plan, tracker, onNext }: StepProps) {
  const t = useT();
  const episode = episodeOf(plan, step.episode_ref);
  return (
    <Card>
      <StepTitle hint={step.teaser_only ? undefined : t("feuil.rappel.hint")}>{t("feuil.rappel.title")}</StepTitle>
      {!!step.teaser_only && <p style={{ fontStyle: "italic" }}>{String(step.teaser || t("feuil.rappel.first"))}</p>}
      {!!step.long && (
        <ol style={{ paddingInlineStart: 20 }}>
          {((step.summaries as string[]) ?? []).map((s, i) => <li key={i}>{s}</li>)}
        </ol>
      )}
      {episode && !step.long && (
        <>
          <p style={{ color: "var(--muted)", fontStyle: "italic" }}>{String(step.summary ?? episode.summary)}</p>
          <EpisodeText episode={episode} onReveal={revealFor(tracker, episode, "rappel")} />
        </>
      )}
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

export function Understood({ onPick }: { onPick: (signal: string) => void }) {
  const t = useT();
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "flex-end", marginTop: 18 }}>
      <span style={{ color: "var(--muted)", alignSelf: "center", fontSize: 14 }}>{t("feuil.understood.q")}</span>
      {["compris", "a_peu_pres", "pas_compris"].map((s) => (
        <button key={s} style={s === "compris" ? primaryBtn : ghostBtn} onClick={() => onPick(s)}>
          {t(`feuil.understood.${s}`)}
        </button>
      ))}
    </div>
  );
}

export function JeuxStep({ step, plan, tracker, onNext }: StepProps) {
  const t = useT();
  return (
    <Card>
      <StepTitle hint={t("feuil.games.hint")}>{t("feuil.games.title")}</StepTitle>
      <GameList games={(step.games as Game[]) ?? []} episodes={plan.episodes} rtl={plan.rtl} onAnswer={answerFor(tracker)} />
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

// ── Deuxième vague et contrôle de reprise (R7, § 14.2) ────────────────────────

function Retranslate({
  episode,
  line,
  translation,
  typing,
  rtl,
  onRate,
}: {
  episode: EpisodeView;
  line: number;
  translation: string;
  typing: boolean;
  rtl: boolean;
  onRate: (rating: "su" | "a_peu_pres" | "pas_su", typed: string | null) => void;
}) {
  const t = useT();
  const [typed, setTyped] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [diff, setDiff] = useState<DiffOp[] | null>(null);
  const [rated, setRated] = useState<string | null>(null);
  const original = episode.lines[line]?.tokens.map((tk) => tk.text).join("") ?? "";
  async function reveal() {
    setRevealed(true);
    if (typing && typed.trim()) {
      try {
        setDiff((await api.feuilletonCompare(original, typed)).ops);
      } catch {
        setDiff(null);
      }
    }
  }
  return (
    <div style={{ borderBottom: "1px solid var(--border)", paddingBottom: 12 }}>
      <div style={{ fontStyle: "italic" }}>{translation}</div>
      {typing && !revealed && (
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={t("feuil.wave.type")}
          dir="auto"
          style={{ width: "100%", marginTop: 6, padding: "8px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)", fontSize: 16 }}
        />
      )}
      {!revealed ? (
        <button style={{ ...ghostBtn, marginTop: 8 }} onClick={reveal}>{t("feuil.wave.reveal")}</button>
      ) : (
        <div style={{ marginTop: 8 }}>
          <Target rtl={rtl} style={{ fontSize: rtl ? 24 : 18, fontWeight: 600 }}>{original}</Target>
          {diff && (
            <div style={{ marginTop: 4, fontSize: 14 }} aria-label={t("feuil.wave.diff")}>
              {diff.map((op, i) => (
                <span
                  key={i}
                  style={{
                    marginInlineEnd: 4,
                    textDecoration: op.op === "extra" ? "line-through" : undefined,
                    background: op.op === "missing" ? "var(--warning-soft)" : op.op === "extra" ? "var(--danger-soft)" : undefined,
                  }}
                >
                  {op.op === "missing" ? `[${op.text}]` : op.text}
                </span>
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            {(["su", "a_peu_pres", "pas_su"] as const).map((r) => (
              <button key={r} style={chipBtn(rated === r)} onClick={() => { setRated(r); onRate(r, typed.trim() || null); }}>
                {t(`feuil.wave.${r}`)}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function SecondWaveStep({ step, plan, tracker, onNext }: StepProps) {
  const t = useT();
  const episode = episodeOf(plan, step.episode_ref)!;
  const lines = (step.lines as { line: number; translation: string; typing: boolean }[]) ?? [];
  return (
    <Card>
      <StepTitle hint={t("feuil.wave.hint", { n: episode.n })}>{t("feuil.wave.title")}</StepTitle>
      <div style={{ display: "grid", gap: 12 }}>
        {lines.map((l) => (
          <Retranslate
            key={l.line}
            episode={episode}
            line={l.line}
            translation={l.translation}
            typing={l.typing}
            rtl={plan.rtl}
            onRate={(rating, typed) => tracker.push({ type: "rating", episode_id: episode.id, line: l.line, rating, typed })}
          />
        ))}
      </div>
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

export function ControleStep({ step, plan, tracker, onNext }: StepProps) {
  const t = useT();
  if (step.mode === "cartes") {
    return <CartesStep step={{ ...step, cards: step.cards }} plan={plan} tracker={tracker} onNext={onNext} title={t("feuil.controle.title")} />;
  }
  const blocks = (step.blocks as { episode_ref: number; lines: { line: number; translation: string; typing: boolean }[] }[]) ?? [];
  return (
    <Card>
      <StepTitle hint={t("feuil.controle.hint")}>{t("feuil.controle.title")}</StepTitle>
      <div style={{ display: "grid", gap: 14 }}>
        {blocks.map((b) => {
          const episode = episodeOf(plan, b.episode_ref)!;
          return b.lines.map((l) => (
            <Retranslate
              key={`${b.episode_ref}-${l.line}`}
              episode={episode}
              line={l.line}
              translation={l.translation}
              typing={l.typing}
              rtl={plan.rtl}
              onRate={(rating, typed) => tracker.push({ type: "rating", episode_id: episode.id, line: l.line, rating, typed })}
            />
          ));
        })}
      </div>
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

// ── Relectures, jalon, bilan ──────────────────────────────────────────────────

export function RelectureStep({ step, plan, tracker, onNext }: StepProps) {
  const t = useT();
  const episode = episodeOf(plan, step.episode_ref)!;
  return (
    <Card>
      <StepTitle hint={t(`feuil.relecture.${String(step.why ?? "last")}`)}>
        {`${t("feuil.relecture.title")} — ${t("feuil.episode_n", { n: episode.n })}`}
      </StepTitle>
      <EpisodeText episode={episode} onReveal={revealFor(tracker, episode, "relecture")} />
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

export function JalonStep({ step, plan, tracker, onNext }: StepProps) {
  const t = useT();
  const episode = episodeOf(plan, step.episode_ref)!;
  const [taps, setTaps] = useState(0);
  const [done, setDone] = useState(false);
  const reveal = revealFor(tracker, episode, "jalon");
  return (
    <Card>
      <StepTitle hint={t("feuil.jalon.hint")}>{t("feuil.jalon.title")}</StepTitle>
      <EpisodeText episode={episode} onReveal={(l, k) => { setTaps((n) => n + 1); reveal(l, k); }} />
      {!done ? (
        <NextButton label={t("feuil.jalon.done")} onClick={() => setDone(true)} />
      ) : (
        <>
          <p style={{ marginTop: 14, fontWeight: 600 }}>
            {t("feuil.jalon.compare", { today: taps, first: Number(step.first_taps ?? 0) })}
          </p>
          <NextButton onClick={() => onNext()} />
        </>
      )}
    </Card>
  );
}

export function RecapStep({ step, plan, tracker, onNext }: StepProps) {
  const t = useT();
  const points = (step.points as PointView[]) ?? [];
  const summaries = (step.summaries as string[]) ?? [];
  return (
    <Card>
      <StepTitle hint={points.length ? t("feuil.bilan.hint") : undefined}>
        {points.length ? t("feuil.bilan.title") : t("feuil.recap.title")}
      </StepTitle>
      {summaries.length > 0 && (
        <ol style={{ paddingInlineStart: 20 }}>{summaries.map((s, i) => <li key={i}>{s}</li>)}</ol>
      )}
      <div style={{ display: "grid", gap: 18 }}>
        {points.map((p, i) => {
          const episode = episodeOf(plan, p.episode_ref);
          return (
            <div key={i} style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              <div style={{ fontWeight: 700 }}>{p.title}</div>
              <div style={{ color: "var(--muted)", fontSize: 14 }}>{p.learner_goal}</div>
              {/* La règle de la leçon du point quand elle existe, sinon l'explication de l'épisode. */}
              <p style={{ margin: "6px 0" }}>{p.rule || p.explanation}</p>
              {p.remember && (
                <p style={{ margin: "0 0 6px", padding: "6px 10px", borderRadius: "var(--radius-sm)", background: "var(--accent-soft)", fontSize: 14 }}>
                  <strong>{t("feuil.lecon.remember")} :</strong> <bdi dir="auto">{p.remember}</bdi>
                </p>
              )}
              {episode && (
                <EpisodeText episode={episode} highlights={p.highlights}
                             onlyLines={p.highlights.map((h) => h.line)} onReveal={revealFor(tracker, episode, "recap")} />
              )}
            </div>
          );
        })}
      </div>
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

// ── Cartes dues (plafonnées côté serveur, P13) ────────────────────────────────

export function CartesStep({ step, tracker, onNext, title }: StepProps & { title?: string }) {
  const t = useT();
  const cards = (step.cards as DueCard[]) ?? [];
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const card = cards[index];
  function verdict(v: "correct" | "partial" | "incorrect") {
    tracker.push({ type: "card", card_id: card.id, verdict: v });
    setFlipped(false);
    setIndex((i) => i + 1);
  }
  return (
    <Card>
      <StepTitle hint={t("feuil.cards.hint", { n: cards.length })}>{title ?? t("feuil.cards.title")}</StepTitle>
      {card ? (
        <div style={{ textAlign: "center", display: "grid", gap: 10 }}>
          <div style={{ fontSize: 24, fontWeight: 600 }}><bdi dir="auto">{card.front}</bdi></div>
          {/* La prononciation accompagne la face écrite dans la langue apprise. */}
          {card.pronunciation && card.pronunciation_side === "front" && (
            <div style={{ color: "var(--muted)" }}>{card.pronunciation}</div>
          )}
          {flipped ? (
            <>
              <div style={{ fontSize: 18 }}>{card.back}</div>
              {card.pronunciation && card.pronunciation_side === "back" && (
                <div style={{ color: "var(--muted)" }}>{card.pronunciation}</div>
              )}
              <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                <button style={ghostBtn} onClick={() => verdict("incorrect")}>{t("feuil.cards.no")}</button>
                <button style={ghostBtn} onClick={() => verdict("partial")}>{t("feuil.cards.almost")}</button>
                <button style={primaryBtn} onClick={() => verdict("correct")}>{t("feuil.cards.yes")}</button>
              </div>
            </>
          ) : (
            <div><button style={primaryBtn} onClick={() => setFlipped(true)}>{t("feuil.cards.flip")}</button></div>
          )}
        </div>
      ) : (
        <p style={{ color: "var(--muted)" }}>{t("feuil.cards.done")}</p>
      )}
      <NextButton onClick={() => onNext()} />
    </Card>
  );
}

// ── Au revoir (R8) ────────────────────────────────────────────────────────────

export function AuRevoirStep({ step, plan, onNext }: StepProps) {
  const t = useT();
  const take = step.take_away as { episode_ref: number; line: number; translation: string } | null;
  const episode = take ? episodeOf(plan, take.episode_ref) : undefined;
  const feeling = step.feeling as { question: string; options: string[] } | undefined;
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <Card>
      <StepTitle>{t("feuil.goodbye.title")}</StepTitle>
      {take && episode && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>{t("feuil.goodbye.take")}</div>
          <EpisodeText episode={episode} onlyLines={[take.line]} />
          <div style={{ fontStyle: "italic", color: "var(--text-soft)" }}>{take.translation}</div>
        </div>
      )}
      {typeof step.teaser === "string" && step.teaser && (
        <p><span style={{ fontWeight: 700 }}>{t("feuil.goodbye.next")}</span> {step.teaser}</p>
      )}
      {feeling && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>{t(feeling.question)}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {feeling.options.map((o) => (
              <button key={o} style={chipBtn(picked === o)} onClick={() => setPicked(o)}>{t(o)}</button>
            ))}
          </div>
        </div>
      )}
      <NextButton label={t("feuil.goodbye.finish")} onClick={() => onNext({ feeling: picked })} />
    </Card>
  );
}
