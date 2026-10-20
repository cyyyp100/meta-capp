// features/reader/useStableCallback.ts — Une fonction qui ne change jamais, et
// qui appelle toujours la dernière version de ce qu'on lui a donné.
//
// Les pages du lecteur sont mémoïsées (`PdfPage`, `BlockPages`) : un callback
// recréé à chaque rendu les redessinerait toutes, à chaque page dominante qui
// change en cours de défilement. Le lecteur gardait pour cela une ref par
// callback (`askRemoveRef`) ; ce hook en fait un geste, pour les suivants.
import { useCallback, useLayoutEffect, useRef } from "react";

export function useStableCallback<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn);
  // Après le rendu, avant tout événement : un clic lit toujours la version à jour.
  useLayoutEffect(() => {
    ref.current = fn;
  });
  return useCallback((...args: A) => ref.current(...args), []);
}
