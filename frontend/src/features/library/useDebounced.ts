// features/library/useDebounced.ts — Valeur retardée (frappe au clavier).
import { useEffect, useState } from "react";

/** Renvoie `value` après `delayMs` sans nouvelle frappe. */
export function useDebounced<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
