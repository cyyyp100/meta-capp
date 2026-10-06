import { useEffect, useState } from "react";

import { WhyButton } from "../science/WhyButton";
import { useT } from "../../i18n";
import { SasOverlay } from "./SasOverlay";

const REST_SECONDS = 60;
const UNLOCK_AFTER_SECONDS = 15;

// Sas de repos post-session : une courte phase sans stimulation nouvelle.
//
// Les deux durées sont paramétrables pour la visite guidée, et pour elle seule :
// une minute de repos est le bon geste après une vraie lecture, mais imposer une
// minute d'immobilité au milieu d'un tutoriel ferait fermer la fenêtre. La visite
// montre le sas et son intention, pas sa durée.
//
// `skipKey` : le bouton annonce où il mène, et ce n'est pas toujours la
// bibliothèque — après une séance de langue, `onDone` ramène aux langues.
export function PostExitRestSas({
  onDone,
  skipKey = "post_exit_rest.skip",
  totalSeconds = REST_SECONDS,
  unlockAfterSeconds = UNLOCK_AFTER_SECONDS,
}: {
  onDone: () => void;
  skipKey?: string;
  totalSeconds?: number;
  unlockAfterSeconds?: number;
}) {
  const t = useT();
  const [left, setLeft] = useState(totalSeconds);
  const elapsed = totalSeconds - left;
  const canSkip = elapsed >= unlockAfterSeconds;
  const lockedLeft = Math.max(0, unlockAfterSeconds - elapsed);
  const progress = elapsed / totalSeconds;

  useEffect(() => {
    if (left <= 0) {
      onDone();
      return;
    }
    const id = setTimeout(() => setLeft((value) => value - 1), 1000);
    return () => clearTimeout(id);
  }, [left, onDone]);

  return (
    <SasOverlay>
      <div style={{ textAlign: "center", maxWidth: 560, padding: "var(--space-xl)" }}>
        <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: 1, color: "var(--accent-ink)", marginBottom: 12 }}>
          {t("post_exit_rest.label")}
        </div>
        <h2 style={{ fontFamily: "var(--font-title)", fontSize: "var(--text-h2)", margin: "0 0 10px", color: "var(--text)" }}>
          {t("post_exit_rest.title")}
        </h2>
        <p style={{ color: "var(--text-soft)", lineHeight: 1.6, margin: "0 auto", maxWidth: 500 }}>
          {t("post_exit_rest.text")}
        </p>
        <div style={{ marginTop: 14 }}>
          <WhyButton whyKey="postExitRest" />
        </div>

        <div
          style={{
            margin: "18px auto",
            maxWidth: 500,
            background: "var(--accent-soft)",
            color: "var(--accent-ink)",
            borderRadius: "var(--radius-md)",
            padding: "12px 16px",
            fontSize: 14,
            lineHeight: 1.5,
          }}
        >
          {t("post_exit_rest.hook")}
        </div>

        <div
          data-tour="rest"
          style={{
            margin: "22px auto",
            width: 104,
            height: 104,
            borderRadius: "50%",
            display: "grid",
            placeItems: "center",
            background: `conic-gradient(var(--accent) ${progress * 360}deg, var(--accent-soft) 0deg)`,
          }}
        >
          <div
            style={{
              width: 90,
              height: 90,
              borderRadius: "50%",
              display: "grid",
              placeItems: "center",
              background: "var(--bg)",
              color: "var(--accent-ink)",
              fontSize: 30,
              fontWeight: 700,
            }}
          >
            {left}
          </div>
        </div>

        <button
          onClick={onDone}
          disabled={!canSkip}
          style={{
            border: "none",
            background: canSkip ? "var(--accent)" : "var(--surface-soft)",
            color: canSkip ? "var(--on-accent)" : "var(--muted)",
            borderRadius: "var(--radius-sm)",
            padding: "10px 22px",
            fontWeight: 600,
            cursor: canSkip ? "pointer" : "not-allowed",
          }}
        >
          {canSkip ? t(skipKey) : t("post_exit_rest.locked", { n: lockedLeft })}
        </button>
      </div>
    </SasOverlay>
  );
}

