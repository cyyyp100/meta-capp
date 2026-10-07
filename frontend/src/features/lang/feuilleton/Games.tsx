// Games — Petits jeux et micro-items, tous au tap (F8, § 10.3).
//
// Chaque item porte sa clé (`expected`) pour un retour IMMÉDIAT ; la réponse
// part aussi au serveur, qui la recorrige et c'est ce résultat-là qui compte
// (R23). Un item passé sans réponse n'envoie rien : il vaudra NULL, jamais 1.
// En arabe, l'ordre des étiquettes suit le sens de lecture (A11) : le conteneur
// est en `dir="rtl"`, l'ordre logique attendu reste celui du texte.
import { useMemo, useState } from "react";

import type { EpisodeView, Game, GameItem } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { chipBtn, Feedback, ghostBtn, primaryBtn, Target } from "./ui";

type Answer = (item: GameItem, given: unknown, ms: number) => void;

function same(a: unknown, b: unknown): boolean {
  const norm = (x: unknown) => String(x ?? "").normalize("NFC").trim().toLocaleLowerCase();
  return norm(a) === norm(b);
}

export function GameList({
  games,
  episodes,
  rtl,
  onAnswer,
}: {
  games: Game[];
  episodes: Record<string, EpisodeView>;
  rtl: boolean;
  onAnswer: Answer;
}) {
  const t = useT();
  return (
    <div style={{ display: "grid", gap: 22 }}>
      {games.map((game, gi) => (
        <div key={gi}>
          <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--accent-ink)", marginBottom: 8 }}>
            {t(`feuil.game.${game.kind}`)}
          </div>
          <div style={{ display: "grid", gap: 14 }}>
            {game.items.map((item) => (
              <GameItemView key={item.ref} item={item} episodes={episodes} rtl={rtl} onAnswer={onAnswer} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function GameItemView({
  item,
  episodes,
  rtl,
  onAnswer,
}: {
  item: GameItem;
  episodes: Record<string, EpisodeView>;
  rtl: boolean;
  onAnswer: Answer;
}) {
  const [started] = useState(() => Date.now());
  const [given, setGiven] = useState<unknown>(undefined);
  const episode = item.episode_id ? episodes[String(item.episode_id)] : undefined;
  const answer = (value: unknown) => {
    if (given !== undefined) return;
    setGiven(value);
    onAnswer(item, value, Date.now() - started);
  };
  const props = { item, episode, rtl, given, answer };
  switch (item.kind) {
    case "remettre_en_ordre":
      return <Ordering {...props} />;
    case "apparier":
      return <Matching {...props} />;
    case "trouver_dans_le_texte":
    case "retrouver_la_lettre":
      return <FindInText {...props} />;
    default:
      return <Choice {...props} />;
  }
}

interface ItemProps {
  item: GameItem;
  episode?: EpisodeView;
  rtl: boolean;
  given: unknown;
  answer: (value: unknown) => void;
}

function lineText(episode: EpisodeView | undefined, line: unknown): string {
  if (!episode || typeof line !== "number") return "";
  return episode.lines[line]?.tokens.map((tk) => tk.text).join("") ?? "";
}

function Prompt({ item, episode, rtl }: { item: GameItem; episode?: EpisodeView; rtl: boolean }) {
  const t = useT();
  const p = item.prompt as Record<string, unknown>;
  switch (item.kind) {
    case "completer_replique": {
      const ln = episode?.lines[p.line as number];
      return (
        <div>
          <div dir={rtl ? "rtl" : "ltr"} style={{ fontSize: 18 }}>
            {ln?.tokens.map((tk, i) => (i === p.blank ? <span key={i}> ____ </span> : <span key={i}>{tk.text}</span>))}
          </div>
          <div style={{ color: "var(--muted)", fontSize: 13 }}>{String(p.translation ?? "")}</div>
        </div>
      );
    }
    case "qui_a_dit":
      return <Target rtl={rtl} style={{ fontSize: 18 }}>« {lineText(episode, p.line)} »</Target>;
    case "bonne_forme":
      // Items de la leçon : une case du tableau de formes, ou un piège.
      if (p.source === "pitfall") {
        return <div style={{ color: "var(--muted)", fontSize: 14 }}>{t("feuil.lecon.which_right")}</div>;
      }
      if (p.source === "forms") {
        const cue = ((p.cue as string[]) ?? []).filter(Boolean);
        return (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", fontSize: 16 }}>
            {cue.map((c, i) => (
              <bdi key={i} dir="auto" style={{ padding: "2px 8px", borderRadius: 6, background: "var(--surface-soft)", fontFamily: rtl ? "var(--font-arabic)" : undefined }}>
                {c}
              </bdi>
            ))}
            <span aria-hidden>→ ____</span>
          </div>
        );
      }
      return (
        <div>
          <Target rtl={rtl} style={{ fontSize: 18 }}>{String(p.sentence ?? "")}</Target>
          <div style={{ color: "var(--muted)", fontSize: 13 }}>{String(p.translation ?? "")}</div>
        </div>
      );
    case "caractere_sens":
    case "caractere_pinyin":
      return <div style={{ fontSize: 40 }}>{String(p.hanzi ?? "")}</div>;
    case "ton_du_caractere":
      return (
        <div style={{ fontSize: 40 }}>
          {String(p.hanzi ?? "")} <span style={{ fontSize: 20, color: "var(--muted)" }}>{String(p.bare ?? "")}</span>
        </div>
      );
    case "lettre_forme":
      return (
        <div>
          <Target rtl style={{ fontSize: 30 }}>{String(p.word ?? "")}</Target>
          <div style={{ color: "var(--muted)", fontSize: 13 }}>
            {t("feuil.game.letter_position", { letter: String(p.letter ?? ""), position: t(`feuil.pos.${String(p.position)}`) })}
          </div>
        </div>
      );
    case "lire_vocalise":
      return <Target rtl style={{ fontSize: 30 }}>{String(p.word ?? "")}</Target>;
    default:
      return null;
  }
}

function Choice({ item, episode, rtl, given, answer }: ItemProps) {
  const t = useT();
  const options = (item.options ?? []) as string[];
  const labels = item.kind === "ton_du_caractere" ? options.map((o) => t(`feuil.tone_${o}`)) : options;
  return (
    <div>
      <Prompt item={item} episode={episode} rtl={rtl} />
      <div dir={rtl && item.kind !== "lire_vocalise" ? "rtl" : "ltr"} style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
        {options.map((opt, i) => {
          const picked = given !== undefined && same(given, opt);
          return (
            <button
              key={i}
              onClick={() => answer(opt)}
              disabled={given !== undefined}
              style={{
                ...chipBtn(picked),
                fontSize: item.kind === "lettre_forme" ? 26 : 15,
                fontFamily: rtl && item.kind !== "lire_vocalise" ? "var(--font-arabic)" : undefined,
              }}
            >
              {labels[i]}
            </button>
          );
        })}
      </div>
      {given !== undefined && (
        <Feedback ok={same(given, item.expected)}>
          {same(given, item.expected) ? t("feuil.right") : t("feuil.wrong", { answer: String(item.expected) })}
        </Feedback>
      )}
    </div>
  );
}

function Ordering({ item, rtl, given, answer }: ItemProps) {
  const t = useT();
  const options = (item.options ?? []) as string[];
  const [picked, setPicked] = useState<number[]>([]);
  const built = picked.map((i) => options[i]);
  const expected = item.expected as string[];
  const p = item.prompt as Record<string, unknown>;
  return (
    <div>
      <div style={{ color: "var(--muted)", fontSize: 13 }}>{String(p.translation ?? "")}</div>
      <div dir={rtl ? "rtl" : "ltr"} style={{ minHeight: 44, display: "flex", flexWrap: "wrap", gap: 6, padding: 8, border: "1px dashed var(--border-strong)", borderRadius: "var(--radius-sm)", margin: "6px 0" }}>
        {built.length === 0 && <span style={{ color: "var(--muted)", fontSize: 13 }}>{t("feuil.game.order_hint")}</span>}
        {built.map((w, i) => (
          <span key={i} style={{ ...chipBtn(true), cursor: "default", fontFamily: rtl ? "var(--font-arabic)" : undefined }}>{w}</span>
        ))}
      </div>
      <div dir={rtl ? "rtl" : "ltr"} style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {options.map((w, i) => (
          <button
            key={i}
            disabled={given !== undefined || picked.includes(i)}
            onClick={() => setPicked((cur) => [...cur, i])}
            style={{ ...chipBtn(false), opacity: picked.includes(i) ? 0.4 : 1, fontFamily: rtl ? "var(--font-arabic)" : undefined }}
          >
            {w}
          </button>
        ))}
      </div>
      {given === undefined && (
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button style={ghostBtn} onClick={() => setPicked([])} disabled={!picked.length}>{t("feuil.game.reset")}</button>
          <button style={primaryBtn} onClick={() => answer(built)} disabled={built.length !== options.length}>{t("feuil.check")}</button>
        </div>
      )}
      {given !== undefined && (
        <Feedback ok={(given as string[]).every((w, i) => same(w, expected[i]))}>
          {(given as string[]).every((w, i) => same(w, expected[i])) ? t("feuil.right") : t("feuil.wrong", { answer: expected.join(" ") })}
        </Feedback>
      )}
    </div>
  );
}

function Matching({ item, rtl, given, answer }: ItemProps) {
  const t = useT();
  const p = item.prompt as { pairs: { left: string; id: number }[]; right: string[] };
  const expected = item.expected as Record<string, string>;
  const [left, setLeft] = useState<string | null>(null);
  const [pairs, setPairs] = useState<Record<string, string>>({});
  const usedRight = new Set(Object.values(pairs));
  const done = Object.keys(pairs).length === p.pairs.length;
  function pickRight(r: string) {
    if (!left || given !== undefined) return;
    const next = { ...pairs, [left]: r };
    setPairs(next);
    setLeft(null);
    if (Object.keys(next).length === p.pairs.length) answer(next);
  }
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div style={{ display: "grid", gap: 6 }}>
          {p.pairs.map(({ left: l }) => (
            <button
              key={l}
              onClick={() => given === undefined && !pairs[l] && setLeft(l)}
              style={{ ...chipBtn(left === l || !!pairs[l]), fontFamily: rtl ? "var(--font-arabic)" : undefined, fontSize: rtl ? 20 : 15 }}
            >
              <Target rtl={rtl}>{l}</Target>
              {pairs[l] && <span style={{ color: "var(--muted)", fontSize: 12 }}> → {pairs[l]}</span>}
            </button>
          ))}
        </div>
        <div style={{ display: "grid", gap: 6 }}>
          {p.right.map((r) => (
            <button key={r} disabled={usedRight.has(r) || !left} onClick={() => pickRight(r)} style={{ ...chipBtn(false), opacity: usedRight.has(r) ? 0.4 : 1 }}>
              {r}
            </button>
          ))}
        </div>
      </div>
      {!done && <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 6 }}>{t("feuil.game.match_hint")}</div>}
      {given !== undefined && (
        <Feedback ok={Object.entries(expected).every(([k, v]) => same((given as Record<string, string>)[k], v))}>
          {Object.entries(expected).every(([k, v]) => same((given as Record<string, string>)[k], v))
            ? t("feuil.right")
            : t("feuil.wrong", { answer: Object.entries(expected).map(([k, v]) => `${k} = ${v}`).join(", ") })}
        </Feedback>
      )}
    </div>
  );
}

function FindInText({ item, episode, rtl, given, answer }: ItemProps) {
  const t = useT();
  const p = item.prompt as Record<string, unknown>;
  const ln = episode?.lines[p.line as number];
  const [sel, setSel] = useState<Set<number>>(new Set());
  const expected = useMemo(() => new Set(item.expected as number[]), [item.expected]);
  const ok = given !== undefined && [...(given as number[])].sort().join(",") === [...expected].sort().join(",");
  return (
    <div>
      <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 6 }}>
        {item.kind === "retrouver_la_lettre"
          ? t("feuil.game.find_letter", { letter: String(p.letter ?? "") })
          : t("feuil.game.find_example", { example: String(p.example ?? "") })}
      </div>
      <div dir={rtl ? "rtl" : "ltr"} style={{ fontSize: rtl ? 24 : 18, lineHeight: 2 }}>
        {ln?.tokens.map((tk, i) =>
          tk.w ? (
            <button
              key={i}
              disabled={given !== undefined}
              onClick={() => setSel((s) => {
                const n = new Set(s);
                if (n.has(i)) n.delete(i);
                else n.add(i);
                return n;
              })}
              style={{
                border: "none",
                font: "inherit",
                color: "inherit",
                cursor: "pointer",
                borderRadius: 4,
                background:
                  given !== undefined && expected.has(i)
                    ? "var(--success-soft)"
                    : sel.has(i)
                      ? "var(--accent-soft)"
                      : "transparent",
              }}
            >
              {tk.display ?? tk.text}
            </button>
          ) : (
            <span key={i}>{tk.text}</span>
          ),
        )}
      </div>
      {given === undefined ? (
        <button style={{ ...primaryBtn, marginTop: 8 }} disabled={!sel.size} onClick={() => answer([...sel])}>
          {t("feuil.check")}
        </button>
      ) : (
        <Feedback ok={ok}>{ok ? t("feuil.right") : t("feuil.game.find_wrong")}</Feedback>
      )}
    </div>
  );
}
