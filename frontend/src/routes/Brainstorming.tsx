import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

import { api } from "../api/client";
import { ChatPanel } from "../features/brainstorming/ChatPanel";
import { DiscussionList } from "../features/brainstorming/DiscussionList";
import { useT } from "../i18n";

const QK = ["brainstorming", "discussions"];

export function Brainstorming() {
  const t = useT();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  // Incrémenté à chaque « Nouvelle discussion » : le champ de saisie reprend le
  // focus, même quand le serveur a rouvert la page blanche déjà affichée.
  const [focusNonce, setFocusNonce] = useState(0);

  const { data: discussions } = useQuery({ queryKey: QK, queryFn: api.brainstormDiscussions });
  const selected = discussions?.find((d) => d.id === selectedId);

  // Sélection toujours valide : la 1re discussion quand rien n'est choisi, ou
  // quand la discussion choisie a disparu de la liste (supprimée).
  useEffect(() => {
    if (!discussions) return;
    if (selectedId !== null && discussions.some((d) => d.id === selectedId)) return;
    setSelectedId(discussions[0]?.id ?? null);
  }, [discussions, selectedId]);

  // Le serveur tient la règle « une seule page blanche » : il renvoie la
  // discussion vierge existante au lieu d'en empiler une autre.
  async function createDiscussion() {
    if (creating) return;
    setCreating(true);
    try {
      const created = await api.createDiscussion();
      await qc.invalidateQueries({ queryKey: QK });
      setSelectedId(created.id);
      setFocusNonce((n) => n + 1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  }

  // On attend la liste à jour avant de réévaluer la sélection : sinon l'effet
  // ci-dessus reprenait la discussion supprimée dans la liste encore périmée.
  async function deleteDiscussion(id: number) {
    try {
      await api.deleteDiscussion(id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
    await qc.invalidateQueries({ queryKey: QK });
  }

  // Le plafond d'épinglage est tenu par le serveur : son refus (400, message
  // traduit) remonte tel quel en toast.
  async function togglePin(id: number, pinned: boolean) {
    try {
      await api.pinDiscussion(id, pinned);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
    qc.invalidateQueries({ queryKey: QK });
  }

  async function setFolder(id: number, folderId: number | null) {
    try {
      await api.setDiscussionFolder(id, folderId);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
    qc.invalidateQueries({ queryKey: QK });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "var(--space-lg)", gap: "var(--space-md)" }}>
      <header>
        <h1
          style={{ margin: 0, fontSize: "var(--text-h2)", fontFamily: "var(--font-title)" }}
          className="flex items-center gap-2.5"
        >
          <MessageSquare className="size-5 shrink-0 text-brand-ink" aria-hidden />
          {t("brainstorm.title")}
        </h1>
        <p style={{ margin: "4px 0 0", color: "var(--muted)", fontSize: 13 }}>{t("brainstorm.subtitle")}</p>
      </header>

      <div style={{ display: "flex", gap: "var(--space-lg)", flex: 1, minHeight: 0 }}>
        <aside style={{ width: 260, display: "flex", flexDirection: "column", gap: 10, minHeight: 0 }}>
          <Button variant="secondary" className="w-full" onClick={createDiscussion} pending={creating}>
            {!creating && <Plus aria-hidden />}
            {t("brainstorm.new")}
          </Button>
          <DiscussionList
            discussions={discussions ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onDelete={deleteDiscussion}
            onTogglePin={togglePin}
          />
        </aside>

        <main style={{ flex: 1, minWidth: 0 }}>
          {selectedId !== null ? (
            <ChatPanel
              key={selectedId}
              discussionId={selectedId}
              discussion={selected}
              focusNonce={focusNonce}
              onFolderChange={(folderId) => setFolder(selectedId, folderId)}
              onActivity={() => qc.invalidateQueries({ queryKey: QK })}
            />
          ) : (
            <div style={placeholder}>{t("brainstorm.pick")}</div>
          )}
        </main>
      </div>
    </div>
  );
}

const placeholder: React.CSSProperties = {
  height: "100%",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: "var(--muted)",
  fontSize: 14,
  border: "1px dashed var(--border)",
  borderRadius: "var(--radius-md)",
};
