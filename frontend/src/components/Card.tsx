import type { CSSProperties, ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  soft?: boolean;
  style?: CSSProperties;
}

export function Card({ children, soft, style }: CardProps) {
  return (
    <div
      style={{
        background: soft ? "var(--surface-soft)" : "var(--surface)",
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
