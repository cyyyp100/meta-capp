// sonner.tsx — Toaster de l'app (remplace les `alert()` de la bibliothèque).
//
// Écarts assumés par rapport au fichier généré par shadcn :
//  - `next-themes` (lib Next.js) retiré au profit de notre store `useThemeStore` ;
//  - les variables brutes de sonner pointaient sur `var(--popover)` / `var(--radius)`,
//    qui n'existent pas ici : notre pont Tailwind expose `--color-popover`, et les
//    surfaces réelles sont `--surface` / `--text` / `--border` / `--radius-sm`.

import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { Toaster as Sonner, type ToasterProps } from "sonner";

import { useThemeStore } from "@/theme/useTheme";

function Toaster({ ...props }: ToasterProps) {
  const theme = useThemeStore((s) => s.theme);

  return (
    <Sonner
      theme={theme}
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--surface)",
          "--normal-text": "var(--text)",
          "--normal-border": "var(--border)",
          "--error-bg": "var(--danger-soft)",
          "--error-text": "var(--danger)",
          "--error-border": "var(--danger)",
          "--success-bg": "var(--success-soft)",
          "--success-text": "var(--success)",
          "--success-border": "var(--success)",
          "--border-radius": "var(--radius-sm)",
        } as React.CSSProperties
      }
      {...props}
    />
  );
}

export { Toaster };
