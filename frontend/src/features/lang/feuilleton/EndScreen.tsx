// EndScreen — Fin de séance SANS score (F11) : ce qui a été gagné.
//
// Après une reprise ratée, on PROPOSE de relire quelques épisodes, sans
// l'imposer (§ 14.2).
import { useState } from "react";

import { api } from "../../../api/client";
import type { RunCompletion } from "../../../api/feuilleton";
import { useT } from "../../../i18n";
import { Card, ghostBtn, primaryBtn, StepTitle } from "./ui";

export function EndScreen({ result, language, onClose }: { result: RunCompletion; language: string; onClose: () => void }) {
  const t = useT();
  const [rewound, setRewound] = useState(false);
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
