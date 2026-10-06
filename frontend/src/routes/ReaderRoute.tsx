// routes/ReaderRoute.tsx — La porte du lecteur.
//
// Le lecteur démarre une session, ouvre le WebSocket de Clikoda et pose le sas
// d'entrée dès son montage. Sur un document inconnu, ou dont le fichier a
// disparu, tout cela partait pour rien : une session vide en base, des pages
// cassées. La porte décide AVANT de le monter : chargement, document
// introuvable, fichier à localiser (features/reader/MissingFile.tsx), ou le
// lecteur lui-même.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";

import { api } from "../api/client";
import { MissingFile } from "../features/reader/MissingFile";
import { useT } from "../i18n";
import { Reader } from "./Reader";

export function ReaderRoute() {
  const { docId } = useParams();
  const id = Number(docId);
  const t = useT();
  const navigate = useNavigate();
  // Même clé que le lecteur : il retrouve ce détail en cache, sans requête.
  const { data, isError, isFetching } = useQuery({
    queryKey: ["document", id],
    queryFn: () => api.document(id),
    enabled: Number.isFinite(id),
  });

  // Une fois monté pour un document, le lecteur le reste : un rafraîchissement
  // de la requête (invalidation, fichier déplacé PENDANT la lecture) ne doit
  // pas le démonter en pleine séance. Ajusté pendant le rendu, et non dans un
  // effet : le lecteur ne doit jamais être rendu une fois sans ce verrou.
  const [readerFor, setReaderFor] = useState<number | null>(null);
  const ready = data !== undefined && !data.file_missing;
  if (ready && readerFor !== id) setReaderFor(id);

  if (readerFor === id || ready) return <Reader key={id} />;

  if (!Number.isFinite(id) || (data === undefined && isError)) {
    return (
      <Centered>
        <p className="m-0 text-danger">{t("reader.not_found")}</p>
        <Button variant="ghost" onClick={() => navigate("/")}>
          {t("entry.back_library")}
        </Button>
      </Centered>
    );
  }
  // Pas encore de réponse — ou un fichier introuvable en cache pendant qu'une
  // requête est en vol (retour d'une re-liaison, cache périmé) : on attend la
  // réponse plutôt que d'afficher un écran qu'elle démentirait.
  if (data === undefined || isFetching) return <Centered>{t("reader.opening")}</Centered>;

  return <MissingFile doc={data} />;
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground"
      style={{ background: "var(--bg-alt)" }}
    >
      {children}
    </div>
  );
}
