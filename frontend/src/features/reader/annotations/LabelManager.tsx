// features/reader/annotations/LabelManager.tsx — Les étiquettes, dans le carnet.
//
// Renommer (le nom d'une étiquette prédéfinie devient alors personnel ; vidé,
// il revient au nom traduit), recolorer depuis la palette fermée, ajouter
// (jusqu'à la limite que le serveur annonce), supprimer — la confirmation dit combien
// d'éléments la portent, qui restent, sans étiquette —, réordonner par ↑ et ↓.
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { useConfirm } from "@/components/ui/confirm";

import type { AnnotationColor, AnnotationLabel } from "../../../api/types";
import { useLangStore, useT } from "../../../i18n";
import { ANNOTATION_COLORS, colorVar, labelName } from "./palette";
import type { Annotations } from "./useAnnotations";

const iconButton: React.CSSProperties = {
  display: "grid",
  placeItems: "center",
  width: 26,
  height: 26,
  padding: 0,
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface)",
  color: "var(--text-soft)",
  cursor: "pointer",
};

const input: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  padding: "4px 8px",
  fontSize: 13,
  color: "var(--text)",
  background: "var(--surface-soft)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
};

/** Les dix couleurs, en pastilles (un groupe radio). */
export function ColorPicker({
  value,
  onChange,
  label,
}: {
  value: AnnotationColor;
  onChange: (color: AnnotationColor) => void;
  label: string;
}) {
  const t = useT();
  return (
    <div role="radiogroup" aria-label={label} style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
      {ANNOTATION_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          role="radio"
          aria-checked={color === value}
          aria-label={t(`annotations.color.${color}`)}
          title={t(`annotations.color.${color}`)}
          onClick={() => onChange(color)}
          style={{
            width: 18,
            height: 18,
            padding: 0,
            borderRadius: 999,
            background: colorVar(color),
            border: color === value ? "2px solid var(--text)" : "1px solid var(--border-strong)",
            cursor: "pointer",
          }}
        />
      ))}
    </div>
  );
}

function LabelRow({
  label,
  index,
  count,
  annotations,
}: {
  label: AnnotationLabel;
  index: number;
  count: number;
  annotations: Annotations;
}) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const confirm = useConfirm();
  const shown = labelName(label, lang);
  const [name, setName] = useState(shown);
  const [recolor, setRecolor] = useState(false);

  function commitName() {
    const clean = name.trim().replace(/\s+/g, " ");
    if (clean === shown) return;
    if (!clean) {
      // Vidé : une étiquette prédéfinie reprend son nom traduit ; une autre le garde.
      if (label.preset) annotations.updateLabel(label.id, { name: null });
      else setName(shown);
      return;
    }
    annotations.updateLabel(label.id, { name: clean });
  }

  function move(delta: number) {
    const ids = annotations.labels.map((l) => l.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    annotations.reorderLabels(ids);
  }

  async function remove() {
    const ok = await confirm({
      title: t("annotations.label_delete_confirm", { label: shown }),
      description:
        label.usage > 0 ? t("annotations.label_delete_used", { n: label.usage }) : t("annotations.label_delete_unused"),
      confirmLabel: t("common.delete"),
      destructive: true,
    });
    if (ok) void annotations.deleteLabel(label.id);
  }

  return (
    <li style={{ display: "flex", flexDirection: "column", gap: 6, padding: "6px 0" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <button
          type="button"
          aria-label={t("annotations.label_recolor", { label: shown })}
          aria-expanded={recolor}
          title={t("annotations.label_recolor", { label: shown })}
          onClick={() => setRecolor((open) => !open)}
          style={{ ...iconButton, width: 22, height: 22, borderRadius: 999, background: colorVar(label.color) }}
        />
        <input
          value={name}
          maxLength={annotations.limits?.nameMax}
          aria-label={t("annotations.label_rename", { label: shown })}
          onChange={(e) => setName(e.target.value)}
          onBlur={commitName}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
          }}
          style={input}
        />
        <button type="button" style={iconButton} disabled={index === 0} onClick={() => move(-1)} aria-label={t("annotations.label_up")}>
          <ArrowUp className="size-3.5" aria-hidden />
        </button>
        <button
          type="button"
          style={iconButton}
          disabled={index === count - 1}
          onClick={() => move(1)}
          aria-label={t("annotations.label_down")}
        >
          <ArrowDown className="size-3.5" aria-hidden />
        </button>
        <button
          type="button"
          style={{ ...iconButton, color: "var(--danger)" }}
          disabled={count <= 1}
          onClick={remove}
          aria-label={t("annotations.label_delete", { label: shown })}
          title={count <= 1 ? t("annotations.label_last") : t("annotations.label_delete", { label: shown })}
        >
          <Trash2 className="size-3.5" aria-hidden />
        </button>
      </div>
      {recolor ? (
        <ColorPicker
          value={label.color}
          label={t("annotations.label_recolor", { label: shown })}
          onChange={(color) => {
            annotations.updateLabel(label.id, { color });
            setRecolor(false);
          }}
        />
      ) : null}
    </li>
  );
}

export function LabelManager({ annotations }: { annotations: Annotations }) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const [name, setName] = useState("");
  // La couleur proposée vient du serveur (settings.ANNOTATION_DEFAULT_COLOR).
  const [picked, setPicked] = useState<AnnotationColor | null>(null);
  const color = picked ?? annotations.limits?.defaultColor ?? ANNOTATION_COLORS[0];
  const full = annotations.limits !== null && annotations.labels.length >= annotations.limits.maxLabels;

  async function add() {
    const clean = name.trim();
    if (!clean || full) return;
    if (await annotations.createLabel(clean, color)) setName("");
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {annotations.labels.map((label, index) => (
          // Le nom affiché sert de clé : renommée, ou la langue changée, la
          // ligne repart du nom à jour.
          <LabelRow
            key={`${label.id}-${labelName(label, lang)}`}
            label={label}
            index={index}
            count={annotations.labels.length}
            annotations={annotations}
          />
        ))}
      </ul>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingTop: 6, borderTop: "1px solid var(--border)" }}>
        <div style={{ display: "flex", gap: 6 }}>
          <input
            value={name}
            maxLength={annotations.limits?.nameMax}
            disabled={full}
            placeholder={t(full ? "annotations.label_full" : "annotations.label_new_placeholder")}
            aria-label={t("annotations.label_new_placeholder")}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void add();
            }}
            style={input}
          />
          <button
            type="button"
            onClick={() => void add()}
            disabled={!name.trim() || full}
            style={{ ...iconButton, width: "auto", padding: "0 10px", gap: 4, display: "inline-flex", alignItems: "center" }}
          >
            <Plus className="size-3.5" aria-hidden />
            {t("annotations.label_add")}
          </button>
        </div>
        <ColorPicker value={color} onChange={setPicked} label={t("annotations.label_new_color")} />
      </div>
    </div>
  );
}
