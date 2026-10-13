// useLlmStatus.ts — L'état de Clikoda (`GET /api/llm/status`), partagé.
//
// Deux écrans le lisent : la pastille du lecteur et la section Réglages ▸
// Clikoda. Une seule clé React Query, donc un seul appel pour les deux — et il
// vit ici, et non dans l'un des deux composants, pour que le lecteur n'embarque
// pas l'écran de réglages dans son bundle.
//
// Rafraîchi doucement : c'est un diagnostic (Ollama tourne-t-il, quel modèle),
// pas une jauge. Côté serveur, chaque appel rafraîchit aussi le catalogue et
// calibre un modèle qui vient de changer — c'est pourquoi l'écriture du réglage
// invalide cette clé.
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";

export const LLM_STATUS_KEY = ["llm-status"] as const;

export function useLlmStatus(enabled = true) {
  return useQuery({
    queryKey: LLM_STATUS_KEY,
    queryFn: api.llmStatus,
    enabled,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}
