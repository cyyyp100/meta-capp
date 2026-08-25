// DataSection — Sauvegarde/restauration des données utilisateur (plan P4.3) :
// export de la base, restauration depuis une sauvegarde, export des logs
// (partage volontaire pour diagnostic — rien ne part automatiquement).
//
// Les deux actions dangereuses passaient par des dialogues natifs : un
// `window.confirm` pour la restauration, un `window.prompt` pour la purge — où
// il fallait deviner qu'il fallait taper « EFFACER » depuis le texte du message.
// Elles ont maintenant leurs propres dialogues, et le mot à saisir est affiché.
import { AlertTriangle, Download, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { api } from "../api/client";
import { useT } from "../i18n";
import { Card } from "./Card";

/** Mot de confirmation exigé par le serveur (`routers/data.py`), non traduit. */
const PURGE_WORD = "EFFACER";

export function DataSection() {
  const t = useT();
  const confirm = useConfirm();
  const fileInput = useRef<HTMLInputElement>(null);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [purging, setPurging] = useState(false);

  async function onImportFile(file: File) {
    const ok = await confirm({
      title: t("data.import"),
      description: t("data.import_confirm"),
      confirmLabel: t("common.confirm"),
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.importDb(await file.arrayBuffer());
      toast.success(t("data.import_done"));
    } catch {
      toast.error(t("data.import_error"));
    }
  }

  async function onPurge() {
    if (typed !== PURGE_WORD) return;
    setPurging(true);
    try {
      await api.purgeData();
      setPurgeOpen(false);
      setTyped("");
      toast.success(t("data.purge_done"));
    } catch {
      toast.error(t("data.purge_error"));
    } finally {
      setPurging(false);
    }
  }

  return (
    <Card soft>
      <h2 className="m-0 mb-1.5 text-sm font-bold">{t("data.title")}</h2>
      <p className="m-0 mb-3 text-[13px] text-muted-foreground">{t("data.subtitle")}</p>

      <div className="flex flex-wrap gap-2.5">
        {/* <a> plutôt que fetch : le cookie de session part avec, le navigateur télécharge. */}
        <Button asChild variant="secondary" size="sm">
          <a href="/api/data/export" download>
            <Download className="size-4" aria-hidden />
            {t("data.export")}
          </a>
        </Button>

        <Button variant="secondary" size="sm" onClick={() => fileInput.current?.click()}>
          <Upload className="size-4" aria-hidden />
          {t("data.import")}
        </Button>

        <Button asChild variant="secondary" size="sm">
          <a href="/api/data/export-logs" download>
            <Download className="size-4" aria-hidden />
            {t("data.export_logs")}
          </a>
        </Button>

        <Button
          variant="secondary"
          size="sm"
          onClick={() => setPurgeOpen(true)}
          className="border-danger/40 text-danger hover:border-danger hover:bg-danger-soft hover:text-danger"
        >
          <Trash2 className="size-4" aria-hidden />
          {t("data.purge")}
        </Button>

        <input
          ref={fileInput}
          type="file"
          accept=".db"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onImportFile(f);
            e.target.value = "";
          }}
        />
      </div>

      <Dialog
        open={purgeOpen}
        onOpenChange={(open) => {
          setPurgeOpen(open);
          if (!open) setTyped("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-danger">
              <AlertTriangle className="size-5" aria-hidden />
              {t("data.purge")}
            </DialogTitle>
            <DialogDescription>{t("data.purge_prompt")}</DialogDescription>
          </DialogHeader>

          <label className="flex flex-col gap-2 text-sm">
            {/* Le mot exact est AFFICHÉ. Dans le prompt natif il fallait le
                repérer au milieu d'un paragraphe. */}
            <span className="text-muted-foreground">
              {t("data.purge_label")}{" "}
              <code className="rounded-[4px] bg-danger-soft px-1.5 py-0.5 font-code font-bold text-danger">
                {PURGE_WORD}
              </code>
            </span>
            <input
              value={typed}
              autoFocus
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && typed === PURGE_WORD) void onPurge();
              }}
              className="rounded-sm border border-border bg-background px-3 py-2 font-code text-foreground
                         transition-[border-color,box-shadow] duration-fast ease-brand outline-none
                         focus:border-danger focus:ring-[3px] focus:ring-destructive/30"
            />
          </label>

          <DialogFooter>
            <DialogClose asChild>
              <Button variant="secondary">{t("common.cancel")}</Button>
            </DialogClose>
            <Button
              variant="destructive"
              // Le bouton reste inerte tant que le mot n'est pas exact : le refus
              // est visible AVANT le clic, plutôt qu'en erreur 400 après.
              disabled={typed !== PURGE_WORD}
              pending={purging}
              onClick={() => void onPurge()}
            >
              {t("data.purge")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
