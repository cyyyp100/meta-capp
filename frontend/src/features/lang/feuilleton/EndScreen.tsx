// EndScreen — Fin de séance SANS score (F11) : ce qui a été gagné.
//
// L'expression écrite de la séance a été envoyée à Clikoda pendant les jeux :
// l'écran de fin attend sa correction (il interroge le serveur, la séance est
// déjà close) et la montre dès qu'elle arrive. Après une reprise ratée, on
// PROPOSE de relire quelques épisodes, sans l'imposer (§ 14.2).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../../../api/client";
import type { RunCompletion } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { Card, ghostBtn, primaryBtn, StepTitle } from "./ui";
import { WritingFeedback } from "./WritingFeedback";

/** Intervalle d'interrogation tant que la correction s'écrit. */
export const WRITING_POLL_MS = 3000;

export function EndScreen({
  result,
  language,
  rtl = false,
  onClose,
}: {
  result: RunCompletion;
  language: string;
  rtl?: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const [rewound, setRewound] = useState(false);
  const writingId = result.writing?.id ?? null;
  const first = result.writing?.status;
  const { data: writing } = useQuery({
    queryKey: ["feuil", "writing", writingId],
    queryFn: () => api.feuilletonWriting(writingId as number),
    enabled: writingId !== null && first !== "skipped",
    refetchInterval: (q) => {
      const status = q.state.data?.status ?? first;
      return status === "pending" || status === "correcting" ? WRITING_POLL_MS : false;
    },
  });
  const status = writing?.status ?? first;
  useEffect(() => {
    if (writing?.status === "ready" && !writing.seen) void api.feuilletonWritingSeen(writing.id).catch(() => undefined);
  }, [writing?.status, writing?.seen, writing?.id]);

  return (
    <Card>
      <StepTitle>{t("feuil.end.title")}</StepTitle>
      <div style={{ display: "grid", gap: 8 }}>
        {result.episode && <div>{t("feuil.end.episode", { n: result.episode.n, title: result.episode.title })}</div>}
        {result.point && <div>{t("feuil.end.point", { point: result.point })}</div>}
        {result.new_words.length > 0 && (
          <div>
            {t("feuil.end.new_words")} <span style={{ color: "var(--text-soft)" }}>{result.new_words.join(", ")}</span>
          </div>
        )}
        {result.cards_created > 0 && <div>{t("feuil.end.cards", { n: result.cards_created })}</div>}
        <div style={{ color: "var(--muted)" }}>{t("feuil.end.words", { seen: result.words_seen, acquired: result.words_acquired })}</div>
      </div>
      {(status === "pending" || status === "correcting") && (
        <p role="status" style={{ marginTop: 16, color: "var(--muted)" }}>{t("feuil.correction.waiting")}</p>
      )}
      {status === "failed" && <p style={{ marginTop: 16, color: "var(--muted)" }}>{t("feuil.correction.failed")}</p>}
      {writing?.status === "ready" && (
        <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <WritingFeedback writing={writing} rtl={rtl} />
        </div>
      )}
      {result.suggest_rewind && !rewound && (
        <div style={{ marginTop: 16, padding: 12, borderRadius: "var(--radius-md)", background: "var(--surface-soft)" }}>
          <p style={{ margin: "0 0 8px" }}>{t("feuil.end.rewind", { n: result.suggest_rewind })}</p>
          <button
            style={ghostBtn}
            onClick={async () => {
              try {
                await api.feuilletonRewind(language);
              } finally {
                setRewound(true);
              }
            }}
          >
            {t("feuil.end.rewind_yes")}
          </button>
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
        <button style={primaryBtn} onClick={onClose}>{t("feuil.end.close")}</button>
      </div>
    </Card>
  );
}
