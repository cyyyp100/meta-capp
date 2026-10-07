// Library — Les épisodes déjà joués, en lecture libre et sans score (F12).
//
// Rien n'y est mesuré : ni taps, ni traductions montrées. Un épisode se relit
// avec ses notes et la leçon de son point, quand elle est écrite.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../../api/client";
import { useT } from "../../../i18n";
import { EpisodeText } from "./EpisodeText";
import { LessonBody } from "./Lecon";
import { Card, ghostBtn, StepTitle } from "./ui";

export function Library({ language, rtl = false, onClose }: { language: string; rtl?: boolean; onClose: () => void }) {
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
        <EpisodeText episode={episode} translation="toggle" notes={episode.notes} />
        {episode.point?.title && (
          <div style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <strong>{`${t("feuil.lecon.title")} : ${episode.point.title}`}</strong>
            {episode.lesson ? (
              <LessonBody lesson={episode.lesson} rtl={rtl} />
            ) : (
              <p style={{ margin: "6px 0 0" }}>{episode.point.explanation}</p>
            )}
          </div>
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
