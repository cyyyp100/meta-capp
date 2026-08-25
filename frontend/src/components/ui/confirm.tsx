// confirm.tsx — Remplaçant de `window.confirm`, appelé depuis six endroits
// (suppression de dossier, de surlignage, de discussion, restauration et purge
// des données).
//
// Le dialogue natif du navigateur bloque la boucle d'événements, ignore le thème
// et affiche « 127.0.0.1:8756 indique » en en-tête : dans une app de bureau
// empaquetée, rien ne trahit plus sûrement un prototype.
//
// L'API rend une promesse de booléen, exactement comme `confirm()` rend un
// booléen : les sites d'appel ne changent que d'un `await`.
//
//   const ok = await confirm({ title: …, description: …, destructive: true });
//   if (!ok) return;

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useT } from "../../i18n";

export interface ConfirmOptions {
  title: string;
  description?: string;
  /** Libellé du bouton d'action. Par défaut : « Confirmer ». */
  confirmLabel?: string;
  cancelLabel?: string;
  /** Action irréversible : le bouton passe en rouge. */
  destructive?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const t = useT();
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  // La promesse est résolue par le clic ; on garde `resolve` hors du state pour
  // qu'un re-rendu ne le remplace pas au milieu d'une interaction.
  const resolveRef = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((next) => {
    return new Promise<boolean>((resolve) => {
      // Une demande déjà en attente est refusée plutôt qu'écrasée : sinon son
      // appelant resterait suspendu pour toujours.
      resolveRef.current?.(false);
      resolveRef.current = resolve;
      setOptions(next);
    });
  }, []);

  const settle = useCallback((value: boolean) => {
    resolveRef.current?.(value);
    resolveRef.current = null;
    setOptions(null);
  }, []);

  const value = useMemo(() => confirm, [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <AlertDialog
        open={options !== null}
        // Fermeture par Échap ou clic extérieur : c'est un refus, pas un accord.
        onOpenChange={(open) => {
          if (!open) settle(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{options?.title}</AlertDialogTitle>
            {options?.description ? (
              <AlertDialogDescription>{options.description}</AlertDialogDescription>
            ) : null}
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => settle(false)}>
              {options?.cancelLabel ?? t("common.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => settle(true)}
              className={cn(
                buttonVariants({ variant: options?.destructive ? "destructive" : "default" }),
              )}
            >
              {options?.confirmLabel ?? t("common.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ConfirmContext.Provider>
  );
}

/** Ouvre une confirmation et attend la réponse. Rend `false` si l'utilisateur refuse. */
export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm doit être utilisé sous un <ConfirmProvider>.");
  return ctx;
}
