// components/RouteFallback.tsx — Attente d'un module de route chargé à la
// demande. C'était `<div>Chargement…</div>` — un texte brut, en dur, non
// traduit, sans dimension : l'écran restait vide puis basculait d'un coup sur
// le contenu. La silhouette réserve la place et supprime ce saut.
//
// Vit dans son propre fichier parce que DEUX Suspense s'en servent : celui du
// panneau de droite (AppLayout) et celui des routes plein écran (App).
import { Skeleton } from "@/components/ui/skeleton";

import { useT } from "../i18n";

export function RouteFallback() {
  const t = useT();
  return (
    <div className="flex h-full flex-col gap-5.5 p-8.5" role="status" aria-busy="true">
      <span className="sr-only">{t("common.loading")}</span>
      <div className="flex flex-col gap-2.5">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96" />
      </div>
      <div className="grid flex-1 grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-5.5">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-44 rounded-lg" />
        ))}
      </div>
    </div>
  );
}
