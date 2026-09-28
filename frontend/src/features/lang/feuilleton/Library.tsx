// Library — Les épisodes déjà joués, en lecture libre et sans score (F12).
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../../api/client";
import { useT } from "../../../i18n";
import { EpisodeText } from "./EpisodeText";
import { Card, ghostBtn, StepTitle } from "./ui";

export function Library({ language, onClose }: { language: string; onClose: () => void }) {
  const t = useT();
  const [open, setOpen] = useState<number | null>(null);
  const { data: list } = useQuery({ queryKey: ["feuil", "library", language], queryFn: () => api.feuilletonLibrary(language) });
  const { data: episode } = useQuery({
    queryKey: ["feuil", "episode", open],
    queryFn: () => api.feuilletonEpisode(open as number),
    enabled: open !== null,
  });

  if (open !== null && episode) {
    return (
      <Card>
        <button style={{ ...ghostBtn, marginBottom: 12 }} onClick={() => setOpen(null)}>{t("feuil.library.back")}</button>
        <StepTitle hint={episode.summary}>{`${t("feuil.episode_n", { n: episode.n })} — ${episode.title}`}</StepTitle>
        <EpisodeText episode={episode} pass="p1" translation="masquable" />
        {episode.notes.length > 0 && (
          <ol style={{ marginTop: 16, paddingInlineStart: 22, display: "grid", gap: 6 }}>
            {episode.notes.map((n) => <li key={n.n} value={n.n}>{n.text}</li>)}
          </ol>
        )}
        {episode.point?.title && (
          <p style={{ marginTop: 12 }}>
            <strong>{episode.point.title}</strong> — {episode.point.explanation}
          </p>
        )}
      </Card>
    );
  }

  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <StepTitle>{t("feuil.library.title")}</StepTitle>
        <button style={ghostBtn} onClick={onClose}>{t("common.close")}</button>
      </div>
      {!list?.length && <p style={{ color: "var(--muted)" }}>{t("feuil.library.empty")}</p>}
      <div style={{ display: "grid", gap: 8 }}>
        {list?.map((e) => (
          <button key={e.id} style={{ ...ghostBtn, textAlign: "start", display: "grid", gap: 2, fontWeight: 500 }} onClick={() => setOpen(e.id)}>
            <span style={{ fontWeight: 700 }}>{`${t("feuil.episode_n", { n: e.n })} — ${e.title}`}</span>
            <span style={{ color: "var(--muted)", fontSize: 13 }}>{e.summary}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}
