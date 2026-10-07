// EpisodeText — Rendu d'un épisode, réplique par réplique, jeton par jeton (F3-F6).
//
// Le serveur a déjà décidé ce que l'apprenant voit encore (services/lang_runs.
// display_episode) : pinyin des seuls caractères non acquis (M4), niveau de
// vocalisation arabe et translittération sous les lettres non acquises (A6).
// Ici, on rend et on remonte deux gestes, distincts :
//   * un tap sur un mot ouvre sa bulle (traduction, prononciation calculée,
//     genre, faux-ami, « signaler ») et compte comme une révélation ;
//   * « voir la traduction » d'une réplique (ou « Tout traduire ») envoie UN
//     événement par réplique montrée : une réplique traduite ne dit plus rien
//     de ce que l'apprenant lit seul.
// Le mode de traduction ne dépend plus d'une « passe » : `none` (aucune),
// `lines` (réplique par réplique), `all` (toutes affichées), `toggle` (réplique
// par réplique, plus « Tout traduire »). La marque d'une note est un bouton à
// part, à côté du mot : elle ouvre la note sous sa réplique sans compter de tap.
import { useRef, useState } from "react";

import { api } from "../../../api/client";
import type { EpisodeNote, EpisodeView, EpToken, GlossEntry } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { ghostBtn, Target } from "./ui";

export type TranslationMode = "none" | "lines" | "all" | "toggle";

const TONE_COLOR: Record<number, string> = {
  1: "var(--tone-1)",
  2: "var(--tone-2)",
  3: "var(--tone-3)",
  4: "var(--tone-4)",
  5: "var(--tone-5)",
};
const GENDER_COLOR: Record<string, string> = { m: "var(--gender-m)", f: "var(--gender-f)", n: "var(--gender-n)" };

const smallBtn = { ...ghostBtn, minHeight: 32, padding: "4px 10px", fontSize: 12 };

export function EpisodeText({
  episode,
  translation = "none",
  onReveal,
  onLineShown,
  highlights,
  notes,
  onlyLines,
  showPinyinAll,
  toneColors = true,
}: {
  episode: EpisodeView;
  translation?: TranslationMode;
  /** Tap sur un mot (révélation). */
  onReveal?: (line: number, token: number) => void;
  /** Traduction d'une réplique montrée : une fois par réplique, `all` pour « Tout traduire ». */
  onLineShown?: (line: number, all: boolean) => void;
  highlights?: { line: number; tokens: number[] }[];
  notes?: EpisodeNote[];
  onlyLines?: number[];
  showPinyinAll?: boolean;
  toneColors?: boolean;
}) {
  const t = useT();
  const rtl = episode.dir === "rtl";
  const [open, setOpen] = useState<{ line: number; token: number } | null>(null);
  // Répliques ouvertes une à une ; « Tout traduire » est un état à part, qu'on
  // peut refermer. Chaque réplique n'est signalée qu'une fois au serveur.
  const [shown, setShown] = useState<Set<number>>(new Set());
  const [allShown, setAllShown] = useState(false);
  const reported = useRef<Set<number>>(new Set());
  const [openNote, setOpenNote] = useState<number | null>(null);
  const focused = notes?.find((n) => n.n === openNote);
  const lit = new Set(
    [...(highlights ?? []), ...(focused ? [{ line: focused.line, tokens: focused.tokens }] : [])].flatMap((h) =>
      h.tokens.map((ti) => `${h.line}:${ti}`),
    ),
  );
  const visible = (li: number) =>
    translation === "all" || (translation !== "none" && (shown.has(li) || (translation === "toggle" && allShown)));

  function tap(li: number, ti: number) {
    setOpen((cur) => (cur && cur.line === li && cur.token === ti ? null : { line: li, token: ti }));
    onReveal?.(li, ti);
  }

  function report(li: number, all: boolean) {
    if (reported.current.has(li)) return;
    reported.current.add(li);
    onLineShown?.(li, all);
  }

  function showLine(li: number) {
    setShown((s) => new Set(s).add(li));
    report(li, false);
  }

  function toggleAll() {
    if (!allShown) {
      episode.lines.forEach((_, li) => {
        if (!onlyLines || onlyLines.includes(li)) report(li, true);
      });
    }
    setAllShown((v) => !v);
  }

  return (
    <div>
      {translation === "toggle" && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
          <button style={ghostBtn} onClick={toggleAll} aria-pressed={allShown}>
            {allShown ? t("feuil.lecture.hide_all") : t("feuil.lecture.translate_all")}
          </button>
        </div>
      )}
      <div style={{ display: "grid", gap: 14 }}>
        {episode.lines.map((ln, li) => {
          if (onlyLines && !onlyLines.includes(li)) return null;
          const lineNotes = (notes ?? []).filter((n) => n.line === li);
          return (
            <div key={li}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", marginBottom: 2 }}>{ln.speaker}</div>
              <div dir={rtl ? "rtl" : "ltr"} style={{ fontSize: rtl ? 26 : episode.family === "hanzi" ? 24 : 19, lineHeight: rtl ? 2.1 : episode.family === "hanzi" ? 2.2 : 1.7 }}>
                {ln.tokens.map((tok, ti) => {
                  const marks = lineNotes.filter((n) => n.tokens[n.tokens.length - 1] === ti);
                  return (
                    <span key={ti}>
                      <Token
                        tok={tok}
                        gloss={tok.g !== undefined && tok.g !== null ? episode.glossary[tok.g] : undefined}
                        lit={lit.has(`${li}:${ti}`)}
                        active={!!open && open.line === li && open.token === ti}
                        rtl={rtl}
                        showPinyinAll={showPinyinAll}
                        toneColors={toneColors && episode.tone_colors}
                        genderColors={episode.gender_colors}
                        onTap={() => tap(li, ti)}
                      />
                      {marks.map((m) => (
                        <NoteMark key={m.n} n={m.n} active={openNote === m.n} onToggle={() => setOpenNote((cur) => (cur === m.n ? null : m.n))} />
                      ))}
                    </span>
                  );
                })}
              </div>
              {open && open.line === li && (
                <Bubble
                  episode={episode}
                  tok={ln.tokens[open.token]}
                  gloss={(() => {
                    const g = ln.tokens[open.token]?.g;
                    return g !== undefined && g !== null ? episode.glossary[g] : undefined;
                  })()}
                  lineTranslation={ln.translation}
                  line={li}
                  token={open.token}
                  onClose={() => setOpen(null)}
                />
              )}
              {focused && focused.line === li && (
                <div role="note" style={{ margin: "6px 0 2px", padding: "8px 12px", borderInlineStart: "3px solid var(--accent)", background: "var(--surface-soft)", borderRadius: "var(--radius-sm)", fontSize: 14 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "var(--muted)" }}>
                    {t(`feuil.note_kind.${focused.kind}`)}
                  </span>{" "}
                  {focused.text}
                </div>
              )}
              {(translation === "lines" || translation === "toggle") && !visible(li) && (
                <button style={{ ...smallBtn, marginTop: 4 }} onClick={() => showLine(li)}>
                  {t("feuil.reveal_line")}
                </button>
              )}
              {visible(li) && (
                <div style={{ color: "var(--text-soft)", fontStyle: "italic", marginTop: 2 }}>{ln.translation}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** La marque d'une note : un bouton à part, jamais un tap de mot. */
function NoteMark({ n, active, onToggle }: { n: number; active: boolean; onToggle: () => void }) {
  const t = useT();
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={active}
      aria-label={t("feuil.note.open", { n })}
      style={{
        border: "none",
        background: active ? "var(--accent-soft)" : "transparent",
        color: "var(--accent-ink)",
        fontWeight: 700,
        fontSize: "0.55em",
        verticalAlign: "super",
        padding: "0 3px",
        marginInlineStart: 1,
        borderRadius: 4,
        cursor: "pointer",
        minWidth: 18,
      }}
    >
      {n}
    </button>
  );
}

function Token({
  tok,
  gloss,
  lit,
  active,
  rtl,
  showPinyinAll,
  toneColors,
  genderColors,
  onTap,
}: {
  tok: EpToken;
  gloss?: GlossEntry;
  lit: boolean;
  active: boolean;
  rtl: boolean;
  showPinyinAll?: boolean;
  toneColors: boolean;
  genderColors: boolean;
  onTap: () => void;
}) {
  if (!tok.w) return <span>{tok.text}</span>;
  const gender = genderColors && gloss?.gender ? GENDER_COLOR[gloss.gender] : undefined;
  const base: React.CSSProperties = {
    border: "none",
    background: lit ? "color-mix(in srgb, var(--hl-key) 45%, transparent)" : active ? "var(--accent-soft)" : "transparent",
    color: "inherit",
    font: "inherit",
    padding: "0 1px",
    margin: 0,
    cursor: "pointer",
    borderRadius: 4,
    borderBottom: gender ? `2px solid ${gender}` : tok.suspect ? "2px dotted var(--warning)" : "1px dotted transparent",
  };
  let body: React.ReactNode = tok.text;
  if (tok.ruby && tok.ruby.length) {
    // Pinyin au-dessus des seuls caractères non acquis (M4) ; couleur du ton en
    // plus des diacritiques, jamais à leur place (F17).
    const hanzi = [...tok.text];
    let si = 0;
    body = hanzi.map((ch, i) => {
      const syl = tok.ruby![si];
      if (!syl || syl.hanzi !== ch) return <span key={i}>{ch}</span>;
      si += 1;
      const color = toneColors ? TONE_COLOR[syl.tone] : undefined;
      return (
        <ruby key={i} style={{ color }}>
          {ch}
          <rt style={{ fontSize: "0.5em", visibility: syl.show || showPinyinAll ? "visible" : "hidden" }}>{syl.mark}</rt>
        </ruby>
      );
    });
  } else if (rtl && tok.display !== undefined) {
    body = (
      <span style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", verticalAlign: "top" }}>
        <span>{tok.display}</span>
        {tok.translit && <span dir="ltr" style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.2 }}>{tok.translit}</span>}
      </span>
    );
  }
  return (
    <button type="button" onClick={onTap} style={base} aria-label={tok.text}>
      {body}
    </button>
  );
}

function Bubble({
  episode,
  tok,
  gloss,
  lineTranslation,
  line,
  token,
  onClose,
}: {
  episode: EpisodeView;
  tok: EpToken;
  gloss?: GlossEntry;
  lineTranslation: string;
  line: number;
  token: number;
  onClose: () => void;
}) {
  const t = useT();
  const [reported, setReported] = useState(!!tok.reported);
  const rtl = episode.dir === "rtl";
  const pron = tok.ruby?.map((s) => s.mark).join(" ") || tok.translit || gloss?.pron || "";
  async function report() {
    const kind = episode.family === "arabe" ? "vocalisation" : episode.family === "hanzi" ? "pinyin" : "traduction";
    try {
      await api.feuilletonReport(episode.id, line, token, kind);
      setReported(true);
    } catch {
      /* signalement best-effort */
    }
  }
  return (
    <div
      role="dialog"
      aria-label={tok.text}
      style={{
        margin: "6px 0 2px",
        padding: "10px 12px",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border-strong)",
        background: "var(--surface-soft)",
        display: "grid",
        gap: 4,
        fontSize: 14,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10 }}>
        <Target rtl={rtl} style={{ fontSize: rtl ? 22 : 17, fontWeight: 700 }}>
          {gloss?.article ? `${gloss.article} ` : ""}
          {tok.tap_vocalized || tok.text}
        </Target>
        <button onClick={onClose} style={{ ...ghostBtn, minHeight: 32, padding: "2px 10px" }} aria-label={t("common.close")}>
          ×
        </button>
      </div>
      {pron && <div style={{ color: "var(--muted)" }}>{pron}</div>}
      {gloss ? (
        <div>
          <strong>{gloss.translation}</strong>
          {gloss.lemma && gloss.lemma !== tok.text && (
            <span style={{ color: "var(--muted)" }}> — {t("feuil.lemma")} : <Target rtl={rtl}>{gloss.lemma}</Target></span>
          )}
          {gloss.gender && (
            <span style={{ color: "var(--muted)" }}> · {t(`feuil.gender_${gloss.gender}`)}</span>
          )}
        </div>
      ) : (
        <div style={{ color: "var(--text-soft)" }}>
          {t("feuil.line_meaning")} : <em>{lineTranslation}</em>
        </div>
      )}
      {gloss?.transparent && (
        <div style={{ color: "var(--success)" }}>{t(`feuil.transparent.${episode.explain_lang ?? "fr"}`)}</div>
      )}
      {gloss?.faux_ami && <div style={{ color: "var(--warning)" }}>{t("feuil.faux_ami")} : {gloss.faux_ami}</div>}
      {tok.validated && (
        <div style={{ color: "var(--warning)" }}>
          {t("feuil.vocalization_doubt")} <Target rtl>{tok.validated}</Target>
        </div>
      )}
      {tok.suspect && !tok.validated && <div style={{ color: "var(--warning)" }}>{t("feuil.suspect")}</div>}
      <div>
        <button onClick={report} disabled={reported} style={{ ...ghostBtn, minHeight: 32, padding: "2px 10px", fontSize: 12 }}>
          {reported ? t("feuil.reported") : t("feuil.report")}
        </button>
      </div>
    </div>
  );
}
