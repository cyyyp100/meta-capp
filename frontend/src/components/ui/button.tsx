// button.tsx — LA définition d'un bouton. Il y en avait dix, sous sept noms
// (`primaryBtn`, `btnPrimary`, `sendBtn`, `newBtn`, `smallBtn`, `importButton()`,
// `btn`), avec des remplissages divergents (10px 18px, 10px 16px, 0 14px,
// 10px 20px) et — surtout — aucun état de survol, de focus clavier ni de clic,
// puisqu'un style inline ne peut pas porter de pseudo-classe.
//
// L'API reste celle de shadcn (`variant`, `size`, `asChild`) pour que les
// composants copiés depuis l'écosystème se branchent sans retouche ; seules les
// valeurs changent, et elles viennent toutes de tokens.css.

import { cva, type VariantProps } from "class-variance-authority";
import { Loader2Icon } from "lucide-react";
import { Slot } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  [
    "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap",
    "rounded-sm font-semibold outline-none select-none",
    // Le survol, le focus et le clic passent par la transition de marque.
    "transition-[color,background-color,border-color,box-shadow,transform,opacity]",
    "duration-fast ease-brand",
    // Retour au clic : trois caractères, mais c'est ce qui fait qu'un bouton
    // « répond » au lieu de simplement changer de couleur.
    "active:scale-[0.98]",
    // Anneau de focus visible AU CLAVIER seulement — jamais après un clic souris.
    "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:ring-offset-1",
    "focus-visible:ring-offset-background",
    "disabled:pointer-events-none disabled:opacity-50",
    "aria-invalid:border-destructive aria-invalid:ring-destructive/20",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0",
    "[&_svg:not([class*='size-'])]:size-4",
  ],
  {
    variants: {
      variant: {
        // Action principale — l'ancien `primaryBtn` / `btnPrimary` / `importButton`.
        default:
          "bg-brand text-primary-foreground shadow-e1 hover:bg-brand-hover hover:shadow-e2",
        // Action secondaire — l'ancien `btnSecondary` / `ghostBtn`.
        secondary:
          "border border-border bg-surface-soft text-text-soft hover:border-border-strong hover:bg-accent hover:text-accent-foreground",
        outline:
          "border border-border bg-background hover:bg-accent hover:text-accent-foreground",
        // Bouton-icône nu — l'ancien `iconBtn` de GemmaPanel.
        ghost: "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
        // Action destructrice (supprimer un dossier, purger les données).
        destructive:
          "bg-destructive text-primary-foreground shadow-e1 hover:brightness-110 focus-visible:ring-destructive/40",
        // Raccourcis de Gemma (Reformuler / Récap / Curiosité) — l'ancien `chip`.
        chip: "rounded-full border border-border bg-surface-soft px-3 text-xs font-medium text-text-soft hover:border-brand hover:bg-brand-soft hover:text-accent-foreground",
        link: "text-brand underline-offset-4 hover:underline",
      },
      size: {
        // Une seule échelle, là où le code en comptait quatre non concertées.
        sm: "h-8 gap-1.5 px-3 text-xs",
        default: "h-9 px-4 text-sm",
        lg: "h-11 px-6 text-sm",
        icon: "size-9",
        "icon-sm": "size-8",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    /**
     * Action en cours : remplace l'icône de tête par un indicateur et bloque le
     * bouton. Les écrans le faisaient à la main en réécrivant `background` vers
     * `--muted-light`, ce qui ne signalait rien — le bouton avait juste l'air cassé.
     */
    pending?: boolean;
  };

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  pending = false,
  disabled,
  children,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot.Root : "button";

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      data-pending={pending || undefined}
      // `aria-busy` fait annoncer l'attente par les lecteurs d'écran ; sans lui,
      // le bouton devient simplement muet et inerte.
      aria-busy={pending || undefined}
      disabled={disabled || pending}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    >
      {/* `asChild` délègue le rendu à l'enfant : Slot exige UN enfant unique, et
          un `{null}` compte comme un enfant. On transmet donc `children` tel
          quel — pas de fragment, pas de spinner injecté. */}
      {asChild ? (
        children
      ) : (
        <>
          {pending ? <Loader2Icon className="animate-spin" /> : null}
          {children}
        </>
      )}
    </Comp>
  );
}

export { Button, buttonVariants };
