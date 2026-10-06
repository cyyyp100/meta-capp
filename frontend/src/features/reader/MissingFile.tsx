// features/reader/MissingFile.tsx — L'écran du lecteur quand le fichier du
// document a disparu (déplacé, renommé, supprimé).
//
// Rien ne démarre ici : ni session, ni WebSocket, ni sas d'entrée — la porte
// (routes/ReaderRoute.tsx) ne monte pas le lecteur. L'écran dit ce qui se passe,
// où était le fichier, et propose de le localiser. Une fois relié, le détail du
// document est à jour et la porte ouvre le lecteur, au même marque-page.
import { FileQuestionMark } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { DocumentDetail } from "@/api/types";
import { Button } from "@/components/ui/button";

import { useT } from "../../i18n";
import { useRelinkDocument } from "../library/useRelinkDocument";

export function MissingFile({ doc }: { doc: DocumentDetail }) {
  const t = useT();
  const navigate = useNavigate();
  const { relink, pendingId } = useRelinkDocument();

  return (
    <div className="flex h-full items-center justify-center p-8" style={{ background: "var(--bg-alt)" }}>
      <section
        className="flex max-w-lg flex-col items-center gap-4 rounded-lg border border-border bg-surface p-8
                   text-center shadow-e1"
      >
        {/* `--warning` et non `--danger` : rien n'est perdu, le fichier est ailleurs. */}
        <div className="flex size-14 items-center justify-center rounded-full bg-warning-soft text-warning">
          <FileQuestionMark className="size-7" aria-hidden />
        </div>
        <h1 className="m-0 font-serif text-h2 font-bold">{t("reader.file_missing_title")}</h1>
        <p className="m-0 text-muted-foreground">{t("reader.file_missing_body", { name: doc.title })}</p>
        {doc.last_known_folder && (
          <p className="m-0 text-[13px] break-all text-muted-foreground">
            {t("reader.file_missing_last_location", { folder: doc.last_known_folder })}
          </p>
        )}
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          <Button size="lg" pending={pendingId === doc.id} onClick={() => void relink(doc)}>
            {t("library.locate_file")}
          </Button>
          <Button variant="ghost" onClick={() => navigate("/")}>
            {t("entry.back_library")}
          </Button>
        </div>
      </section>
    </div>
  );
}
