// ui.tsx — Petits éléments partagés par les écrans du feuilleton.
//
// Styles en ligne sur les jetons du thème, comme le reste du module langues.
// Cibles de tap d'au moins 40 px (F17) : la séance se joue au doigt comme à la
// souris.
import type { CSSProperties, ReactNode } from "react";

export const primaryBtn: CSSProperties = {
  border: "none",
  background: "var(--accent)",
  color: "var(--on-accent)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 20px",
  minHeight: 40,
  fontWeight: 600,
  cursor: "pointer",
};

export const ghostBtn: CSSProperties = {
  border: "1px solid var(--border)",
  background: "var(--surface)",
  color: "var(--text)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 14px",
  minHeight: 40,
  fontWeight: 600,
  cursor: "pointer",
};

export const chipBtn = (active: boolean): CSSProperties => ({
  border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
  background: active ? "var(--accent-soft)" : "var(--surface)",
  color: "var(--text)",
  borderRadius: 999,
  padding: "8px 14px",
  minHeight: 40,
  cursor: "pointer",
  fontWeight: 500,
});

export function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-sm)",
        padding: "var(--space-lg)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function StepTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <h2 style={{ fontFamily: "var(--font-title)", fontSize: "var(--text-h2)", margin: 0 }}>{children}</h2>
      {hint && <p style={{ color: "var(--muted)", margin: "4px 0 0", fontSize: 14 }}>{hint}</p>}
    </div>
  );
}

export function Feedback({ ok, children }: { ok: boolean; children?: ReactNode }) {
  return (
    <div
      role="status"
      style={{
        marginTop: 8,
        padding: "6px 10px",
        borderRadius: "var(--radius-sm)",
        background: ok ? "var(--success-soft)" : "var(--danger-soft)",
        color: ok ? "var(--success)" : "var(--danger)",
        fontWeight: 600,
        fontSize: 14,
      }}
    >
      {children}
    </div>
  );
}

/** Texte en langue cible : sens d'écriture et isolation bidirectionnelle (A10). */
export function Target({ children, rtl, style }: { children: ReactNode; rtl?: boolean; style?: CSSProperties }) {
  return (
    <bdi dir={rtl ? "rtl" : "ltr"} style={{ fontFamily: rtl ? "var(--font-arabic)" : undefined, ...style }}>
      {children}
    </bdi>
  );
}
