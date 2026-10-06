// features/library/useRelinkDocument.ts — « Localiser le fichier… ».
//
// Le seul chemin de l'interface vers une re-liaison : la carte de la grille, la
// carte « Reprendre » et l'écran du lecteur passent tous par lui. La politique
// (identité du contenu, voisins, nettoyage) est côté serveur
// (nwol/services/relink.py) ; ici, le dialogue : choisir le fichier, confirmer
// une version différente, rafraîchir, dire ce qui a été retrouvé.
//
// Il vit dans `Home` (et dans l'écran du lecteur), pas dans la carte : une carte
// se rend sans QueryClient ni ConfirmProvider dans ses tests.
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { ApiError, api } from "@/api/client";
import { pickDocument } from "@/api/platform";
import type { DocumentSummary, RelinkResult } from "@/api/types";
import { useConfirm } from "@/components/ui/confirm";

import { useT } from "../../i18n";

export function useRelinkDocument() {
  const t = useT();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  // Document en cours de re-liaison : la passe sur les voisins relit chaque
  // fichier candidat, ce qui peut prendre quelques secondes.
  const [pendingId, setPendingId] = useState<number | null>(null);

  const relink = useCallback(
    async (doc: Pick<DocumentSummary, "id" | "title">): Promise<RelinkResult | null> => {
      // Le sélecteur s'ouvre AVANT tout `await` : un navigateur n'ouvre un
      // <input type="file"> que pendant le geste de l'utilisateur.
      const picked = await pickDocument();
      if (!picked) return null;
      setPendingId(doc.id);
      try {
        let result: RelinkResult;
        try {
          result = await api.relinkDocument(doc.id, picked);
        } catch (e) {
          if (!(e instanceof ApiError) || e.code !== "different_file") throw e;
          const ok = await confirm({
            title: t("library.relink_mismatch_title"),
            description: t("library.relink_mismatch_confirm", { name: doc.title }),
            confirmLabel: t("library.relink_anyway"),
          });
          if (!ok) return null;
          result = await api.relinkDocument(doc.id, picked, true);
        }
        // Le détail relié tout de suite (le lecteur s'ouvre sans repasser par le
        // chargement), puis tout le reste : la passe sur les voisins a pu en
        // relier d'autres, dont le détail est peut-être en cache.
        queryClient.setQueryData(["document", doc.id], result.document);
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["library"] }),
          queryClient.invalidateQueries({ queryKey: ["document"] }),
        ]);
        const others = result.relinked.length;
        toast.success(t("library.relinked", { name: result.document.title || doc.title }), {
          description: others > 0 ? t("library.relinked_others", { n: others }) : undefined,
        });
        return result;
      } catch (e) {
        // Le serveur renvoie un `detail` déjà traduit (doublon, mauvais type…).
        toast.error((e as Error).message || t("library.relink_error"));
        return null;
      } finally {
        setPendingId(null);
      }
    },
    [confirm, queryClient, t],
  );

  return { relink, pendingId };
}
