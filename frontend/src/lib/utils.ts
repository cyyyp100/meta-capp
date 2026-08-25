import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Fusionne des classes conditionnelles en résolvant les conflits Tailwind :
 * `cn("px-4", condition && "px-6")` rend `px-6`, là où une simple concaténation
 * laisserait les deux et s'en remettrait à l'ordre du CSS compilé.
 *
 * Convention shadcn/ui — les composants copiés depuis shadcn l'attendent sous
 * ce nom et à ce chemin (voir `components.json:aliases.utils`).
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
