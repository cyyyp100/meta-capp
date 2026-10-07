// FeuilletonHome — Accueil d'une langue du pilote (F1).
//
// Un bouton principal (« Épisode N », « Bilan », « Reprendre »), deux entrées
// secondaires (juste relire, séance courte) et la bibliothèque. Les
// compétences « orales » du flux hérité ne mesuraient rien : elles laissent la
// place à ce qui compte — épisodes joués, mots rencontrés, niveau. Aucun
// compteur de jours : le décompte existe côté serveur, il n'est pas une série.
//
// Deux annonces, décidées par le serveur : une correction d'expression écrite
// arrivée après sa séance (« Ta correction est prête »), et les limites du
// modèle local — un encart masquable, plus une ligne là où la limite se voit
// (`pro_hints`). Texte statique : aucun appel réseau, rien de bloqué.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../../../api/client";
import { useT } from "../../../i18n";
import { usePreferences, useSetPreference } from "../../shell/usePreferences";
import { Library } from "./Library";
import { ProLine, ProNote } from "./ProNote";
import { ghostBtn, primaryBtn } from "./ui";
import { WritingFeedback } from "./WritingFeedback";

export function FeuilletonHome({ language, label, rtl }: { language: string; label: string; rtl: boolean }) {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [library, setLibrary] = useState(false);
  const [openWriting, setOpenWriting] = useState(false);
  // Masqué tout de suite au clic ; le réglage s'enregistre en arrière-plan.
  const [noteClosed, setNoteClosed] = useState(false);
  const { data: preferences } = usePreferences();
  const setPreference = useSetPreference();
  const { data: status } = useQuery({
    queryKey: ["feuil", "status", language],
    queryFn: () => api.feuilletonStatus(language),
    // Pendant qu'un épisode s'écrit, l'accueil se met à jour tout seul.
    refetchInterval: (q) => (q.state.data?.generating ? 8000 : false),
  });
  const unseen = status?.unseen_writing ?? null;
  const { data: writing } = useQuery({
    queryKey: ["feuil", "writing", unseen?.id],
    queryFn: () => api.feuilletonWriting(unseen!.id),
    enabled: openWriting && !!unseen,
  });
  if (!status) return <p style={{ color: "var(--muted)" }}>{t("common.loading")}</p>;
  if (status.unavailable) {
    // Porte V17 : dire pourquoi la langue ne s'ouvre pas, plutôt que l'ouvrir à moitié.
    return (
      <div>
        <h2 style={{ fontSize: 16, margin: 0 }}>{label}</h2>
        <p style={{ color: "var(--warning)", margin: "8px 0 0" }}>{t(`feuil.unavailable.${status.unavailable}`)}</p>
      </div>
    );
  }
  if (library) return <Library language={language} rtl={rtl} onClose={() => setLibrary(false)} />;

  const go = (mode?: "court" | "relecture", onboarding = false) =>
    navigate("/lang/episode", { state: { language, label, rtl, mode, onboarding } });
  const ready = status.next_status === "ready";
  let main = t("feuil.home.episode", { n: status.next_episode });
  if (!status.onboarding_done) main = t("feuil.home.begin");
  else if (status.open_run) main = t("feuil.home.resume");
  else if (status.bilan_due) main = t("feuil.home.bilan");
  const hints = status.pro_hints ?? [];
  const showNote = !noteClosed && preferences !== undefined && preferences.preferences.lang_pro_note_dismissed !== "true";

  async function closeWriting(id: number) {
    setOpenWriting(false);
    try {
      await api.feuilletonWritingSeen(id);
    } finally {
      await queryClient.invalidateQueries({ queryKey: ["feuil", "status", language] });
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 16, margin: 0 }}>{label}</h2>
        <button style={primaryBtn} onClick={() => go(undefined, !status.onboarding_done)}>{main}</button>
      </div>
      {status.onboarding_done && !ready && !status.bilan_due && !status.open_run && (
        <p style={{ color: "var(--muted)", fontSize: 13, margin: "8px 0 0" }}>
          {status.generating ? t("feuil.home.writing", { n: status.next_episode }) : t("feuil.home.not_ready")}
        </p>
      )}
      {hints.includes("generation") && !ready && <ProLine reason="generation" />}
      {hints.includes("program_end") && <ProLine reason="program_end" />}
      {unseen && (
        <div style={{ marginTop: 12, padding: "10px 12px", borderRadius: "var(--radius-md)", background: "var(--accent-soft)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <strong>{t("feuil.home.writing_ready")}</strong>
            <button style={ghostBtn} onClick={() => (openWriting ? void closeWriting(unseen.id) : setOpenWriting(true))}>
              {openWriting ? t("common.close") : t("feuil.home.writing_open")}
            </button>
          </div>
          {openWriting && writing && (
            <div style={{ marginTop: 10 }}>
              <WritingFeedback writing={writing} rtl={rtl} />
            </div>
          )}
        </div>
      )}
      {status.onboarding_done && (
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <button style={ghostBtn} onClick={() => go("relecture")}>{t("feuil.home.reread")}</button>
          <button style={ghostBtn} disabled={!ready} onClick={() => go("court")}>{t("feuil.home.short")}</button>
          <button style={ghostBtn} disabled={!status.episodes_played} onClick={() => setLibrary(true)}>{t("feuil.home.library")}</button>
        </div>
      )}
      <div style={{ display: "flex", gap: 28, marginTop: 16, flexWrap: "wrap" }}>
        <Stat label={t("feuil.home.played")} value={String(status.episodes_played)} />
        <Stat label={t("feuil.home.words")} value={String(status.words_seen)} />
        <Stat label={t("feuil.home.acquired")} value={String(status.words_acquired)} />
        <Stat label={t("feuil.home.level")} value={status.level} />
      </div>
      {status.program.point && status.onboarding_done && (
        <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 0 }}>
          {t("feuil.home.program", { order: status.program.order, size: status.program.size, point: status.program.point })}
        </p>
      )}
      {showNote && (
        <ProNote
          model={status.model}
          onDismiss={() => {
            setNoteClosed(true);
            setPreference.mutate({ lang_pro_note_dismissed: true });
          }}
        />
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 24, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 12, color: "var(--muted)" }}>{label}</div>
    </div>
  );
}
