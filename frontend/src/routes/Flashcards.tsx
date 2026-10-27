import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Play, Plus, Trash2 } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

import { api } from "../api/client";
import type { Flashcard, FlashcardSuggestion } from "../api/types";
import { AutoGrowTextarea } from "../components/AutoGrowTextarea";
import { FlipCard } from "../components/FlipCard";
import { MathText } from "../components/MathText";
import { useDebounced } from "../features/library/useDebounced";
import { useT } from "../i18n";

const DIFFICULTY_COLORS = ["var(--success)", "var(--accent)", "var(--warning)", "var(--danger)"];

export function Flashcards() {
  const t = useT();
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [reviewing, setReviewing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [front, setFront] = useState("");
  const [back, setBack] = useState("");
  const [difficulty, setDifficulty] = useState<number>(0);
  const [rawTag, setRawTag] = useState("");

  // Le filtre par tag relançait une requête à CHAQUE frappe : taper « algèbre »
  // déclenchait sept allers-retours, dont six jetés. Même cadence que la
  // recherche de la bibliothèque (Home.tsx).
  const tag = useDebounced(rawTag, 250).trim();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["flashcards", difficulty, tag],
    queryFn: () => api.flashcards({ difficulty: difficulty || undefined, tags: tag || undefined }),
  });

  // Propositions de la relecture hebdomadaire de Clikoda (services/flashcard_check).
  const suggestions = useQuery({
    queryKey: ["flashcards", "suggestions"],
    queryFn: () => api.flashcardSuggestions(),
  });

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["flashcards"] });
  }

  async function settleSuggestion(s: FlashcardSuggestion, accept: boolean) {
    try {
      if (accept) await api.acceptFlashcardSuggestion(s.card_id);
      else await api.dismissFlashcardSuggestion(s.card_id);
    } catch {
      toast.error(t("flash.check_error"));
    }
    invalidate();
  }

  async function create() {
    if (!front.trim() || !back.trim() || saving) return;
    setSaving(true);
    try {
      const { created } = await api.createFlashcard(front.trim(), back.trim(), "manual");
      // Le serveur ne crée jamais deux fois la même carte : on le dit, on
      // garde le formulaire tel quel pour qu'on puisse la retoucher.
      if (!created) {
        toast.info(t("flash.exists"));
        return;
      }
      setFront("");
      setBack("");
      setCreating(false);
      invalidate();
    } catch {
      toast.error(t("flash.create_error"));
    } finally {
      setSaving(false);
    }
  }

  async function remove(card: Flashcard) {
    // La corbeille supprimait sans rien demander : un clic manqué et la carte
    // était perdue, sans annulation possible.
    const ok = await confirm({
      title: t("flash.delete_title"),
      description: <MathText text={card.front} />,
      confirmLabel: t("common.delete"),
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.deleteFlashcard(card.id);
      invalidate();
    } catch {
      toast.error(t("flash.delete_error"));
    }
  }

  if (reviewing && data && data.length > 0) {
    return <ReviewSession cards={data} onDone={() => setReviewing(false)} />;
  }

  return (
    <div className="mx-auto max-w-[900px] p-8.5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="m-0 mb-1 font-serif text-h1 font-bold">
            {t("flash.title")}
          </h1>
          <p className="mt-0 text-muted-foreground">
            {data ? t("flash.count", { n: data.length }) : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setCreating((c) => !c)}>
            <Plus className="size-4" aria-hidden />
            {t("flash.create")}
          </Button>
          {data && data.length > 0 && (
            <Button onClick={() => setReviewing(true)}>
              <Play className="size-4" aria-hidden />
              {t("flash.review")}
            </Button>
          )}
        </div>
      </div>

      {creating && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          transition={{ duration: 0.22, ease: [0.33, 1, 0.68, 1] }}
          className="mt-4 overflow-hidden rounded-md border border-border bg-surface p-5.5"
        >
          <AutoGrowTextarea
            value={front}
            onChange={(e) => setFront(e.target.value)}
            placeholder={t("flash.front")}
            style={field}
          />
          <AutoGrowTextarea
            value={back}
            onChange={(e) => setBack(e.target.value)}
            placeholder={t("flash.back")}
            style={{ ...field, marginTop: 8 }}
          />
          <div className="mt-2.5 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setCreating(false)}>
              {t("common.cancel")}
            </Button>
            {/* Le bouton reste inerte tant que les deux faces ne sont pas
                remplies : le refus est visible avant le clic. */}
            <Button
              onClick={create}
              pending={saving}
              disabled={!front.trim() || !back.trim()}
            >
              {t("common.save")}
            </Button>
          </div>
        </motion.div>
      )}

      {suggestions.data && suggestions.data.length > 0 && (
        <section aria-labelledby="flash-check-title" className="mt-5 grid gap-3 rounded-md border border-brand/40 bg-brand-soft/40 p-4.5">
          <div>
            <h2 id="flash-check-title" className="m-0 text-base font-bold">
              {t("flash.check_title")} ({suggestions.data.length})
            </h2>
            <p className="m-0 mt-1 text-[13px] text-muted-foreground">{t("flash.check_intro")}</p>
          </div>
          {suggestions.data.map((s) => (
            <SuggestionRow
              key={s.card_id}
              suggestion={s}
              onAccept={() => void settleSuggestion(s, true)}
              onDismiss={() => void settleSuggestion(s, false)}
            />
          ))}
        </section>
      )}

      {/* Filtres */}
      <div className="mt-4 flex items-center gap-2.5">
        <input
          value={rawTag}
          onChange={(e) => setRawTag(e.target.value)}
          placeholder={t("flash.filter_tag")}
          aria-label={t("flash.filter_tag")}
          className="w-full max-w-[220px] rounded-sm border border-border bg-background px-3 py-2 text-sm
                     transition-[border-color,box-shadow] duration-fast ease-brand outline-none
                     hover:border-border-strong
                     focus:border-brand focus:ring-[3px] focus:ring-ring/50"
        />
        <Select value={String(difficulty)} onValueChange={(v) => setDifficulty(Number(v))}>
          <SelectTrigger className="w-[180px]" aria-label={t("flash.all_diff")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="0">{t("flash.all_diff")}</SelectItem>
            <SelectItem value="1">{t("flash.easy")}</SelectItem>
            <SelectItem value="2">{t("flash.medium")}</SelectItem>
            <SelectItem value="3">{t("flash.hard")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading && (
        <div className="mt-5.5 grid gap-3.5" role="status" aria-busy="true">
          <span className="sr-only">{t("common.loading")}</span>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24 rounded-md" />
          ))}
        </div>
      )}

      {isError && (
        <div className="mt-5.5 flex flex-col items-start gap-3 rounded-md border border-danger/30 bg-danger-soft p-5.5">
          <p className="m-0 font-semibold text-danger">{t("flash.error")}</p>
          <Button variant="secondary" size="sm" onClick={() => void refetch()}>
            {t("common.retry")}
          </Button>
        </div>
      )}

      {data && data.length === 0 && (
        <div className="mt-8 rounded-lg border border-dashed border-border-strong p-12 text-center text-muted-foreground">
          {t("flash.empty")}
        </div>
      )}

      <div className="mt-5.5 grid gap-3.5">
        {data?.map((card) => (
          <CardRow key={card.id} card={card} onDelete={() => void remove(card)} />
        ))}
      </div>
    </div>
  );
}

function ReviewSession({ cards, onDone }: { cards: Flashcard[]; onDone: () => void }) {
  const t = useT();
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const card = cards[index];

  // Clic unique : recto -> verso ; verso -> revue neutre (fait avancer la répétition
  // espacée) puis carte suivante. Pas d'auto-évaluation, pas de boutons.
  function advance() {
    if (!flipped) {
      setFlipped(true);
      return;
    }
    api.reviewFlashcard(card.id, "partial").catch(() => {});
    if (index + 1 >= cards.length) onDone();
    else {
      setIndex((i) => i + 1);
      setFlipped(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-full max-w-[980px] flex-col items-center p-8.5">
      <div className="flex w-full items-center justify-between gap-4">
        <Button variant="ghost" size="sm" onClick={onDone}>
          <ArrowLeft className="size-4" aria-hidden />
          {t("common.quit")}
        </Button>
        {/* Une progression chiffrée seule ne se lit pas d'un coup d'œil : la
            barre montre où on en est dans le paquet. */}
        <div className="flex flex-1 items-center gap-3">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-canvas-alt">
            <div
              className="h-full rounded-full bg-brand transition-[width] duration-normal ease-brand"
              style={{ width: `${((index + 1) / cards.length) * 100}%` }}
            />
          </div>
          <span className="text-sm font-semibold text-muted-foreground tabular-nums">
            {index + 1} / {cards.length}
          </span>
        </div>
      </div>

      <div className="mt-6 w-full">
        <FlipCard card={card} flipped={flipped} onClick={advance} />
      </div>

      <div className="mt-4 text-[13px] text-muted-foreground">
        {flipped ? t("flash.tap_next") : t("flash.tap_reveal")}
      </div>
    </div>
  );
}

function CardRow({ card, onDelete }: { card: Flashcard; onDelete: () => void }) {
  const t = useT();
  const diffColor = DIFFICULTY_COLORS[Math.max(1, Math.min(3, card.difficulty))] ?? "var(--accent)";
  return (
    <div
      className="group rounded-md border border-border bg-surface px-5.5 py-3.5 shadow-e1
                 transition-[box-shadow,border-color] duration-fast ease-brand
                 hover:border-border-strong hover:shadow-e2"
      style={{ borderLeft: `4px solid ${diffColor}` }}
    >
      <div className="flex justify-between gap-3">
        <div className="font-semibold">
          <MathText text={card.front} dir="auto" />
          {card.pronunciation && card.pronunciation_side === "front" && (
            <span title={t("lang.phonetic")} className="font-normal italic text-muted-foreground"> [{card.pronunciation}]</span>
          )}
        </div>
        {/* La corbeille n'apparaît qu'au survol de la carte ou au focus clavier :
            la liste reste lisible au repos sans devenir inatteignable. */}
        <button
          onClick={onDelete}
          title={t("common.delete")}
          aria-label={t("common.delete")}
          className="flex h-fit shrink-0 rounded-[4px] p-1 text-muted-foreground opacity-0
                     transition-[opacity,color,background-color] duration-fast ease-brand
                     group-hover:opacity-100 group-focus-within:opacity-100
                     hover:bg-danger-soft hover:text-danger
                     focus-visible:opacity-100 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <Trash2 className="size-4" aria-hidden />
        </button>
      </div>
      <div className="mt-1.5 text-text-soft">
        <MathText text={card.back} dir="auto" />
        {card.pronunciation && card.pronunciation_side === "back" && (
          <span title={t("lang.phonetic")} className="italic text-muted-foreground"> [{card.pronunciation}]</span>
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {card.document_title && <Pill>{card.document_title}</Pill>}
        {card.tags.map((tg) => (
          <Pill key={tg} accent>
            {tg}
          </Pill>
        ))}
      </div>
    </div>
  );
}

/** Une proposition de Clikoda : la carte telle qu'elle est, et ce qu'il propose
 *  (une version corrigée, ou la suppression d'une carte qui dépend du document). */
function SuggestionRow({
  suggestion: s,
  onAccept,
  onDismiss,
}: {
  suggestion: FlashcardSuggestion;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  const t = useT();
  const remove = s.kind === "remove";
  return (
    <div data-testid="flash-suggestion" className="grid gap-2.5 rounded-md border border-border bg-surface p-4 shadow-e1">
      {remove && (
        <div>
          <Pill>{t("flash.check_context")}</Pill>
        </div>
      )}
      <MathText text={s.reason} className="block text-[13px] text-text-soft" />
      <div className={remove ? "grid gap-2" : "grid gap-3 sm:grid-cols-2"}>
        <SuggestionSide label={t("flash.check_yours")} front={s.front} back={s.back} />
        {!remove && (
          <SuggestionSide
            label={t("flash.check_proposed")}
            front={s.suggested_front ?? ""}
            back={s.suggested_back ?? ""}
            highlight
          />
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={remove ? "destructive" : "default"} onClick={onAccept}>
          {remove ? t("flash.check_remove") : t("flash.check_apply")}
        </Button>
        <Button size="sm" variant="secondary" onClick={onDismiss}>
          {t("flash.check_keep")}
        </Button>
      </div>
    </div>
  );
}

function SuggestionSide({ label, front, back, highlight }: { label: string; front: string; back: string; highlight?: boolean }) {
  return (
    <div className={highlight ? "rounded-sm bg-brand-soft p-3" : "rounded-sm bg-canvas-alt p-3"}>
      <div className="mb-1 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{label}</div>
      <MathText text={front} dir="auto" className="block font-semibold" />
      <MathText text={back} dir="auto" className="mt-1 block text-text-soft" />
    </div>
  );
}

function Pill({ children, accent }: { children: React.ReactNode; accent?: boolean }) {
  return (
    <Badge
      variant="secondary"
      className={
        accent
          ? "bg-brand-soft text-accent-foreground"
          : "bg-canvas-alt text-muted-foreground"
      }
    >
      {children}
    </Badge>
  );
}

/** Champs passés à AutoGrowTextarea, qui attend un objet de style. */
const field: React.CSSProperties = {
  width: "100%",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 12px",
  background: "var(--bg)",
  color: "var(--text)",
  fontSize: 14,
  fontFamily: "var(--font-ui)",
};
