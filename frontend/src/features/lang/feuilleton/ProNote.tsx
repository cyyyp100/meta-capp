// ProNote — Les limites du modèle local, et ce que va plus loin la version Pro.
//
// Texte STATIQUE : aucun appel réseau, aucune fonction bloquée. Un lien vers la
// section « Editions — Local vs Pro » du README, rien de plus. Le service dit
// où une ligne se justifie (`pro_hints` : deux échecs d'écriture d'un épisode,
// fin du programme) ; le front l'affiche. L'encart de l'accueil se masque une
// fois pour toutes (`lang_pro_note_dismissed`).
import { PRO_EDITION_URL } from "../../../config/links";
import { useT } from "../../../i18n";
import { ghostBtn } from "./ui";

function ProLink() {
  const t = useT();
  return (
    <a href={PRO_EDITION_URL} target="_blank" rel="noreferrer noopener" style={{ color: "var(--accent-ink)", fontWeight: 600 }}>
      {t("feuil.pro.link")}
    </a>
  );
}

/** L'encart de l'accueil d'une langue, masquable. */
export function ProNote({ model, onDismiss }: { model: string; onDismiss: () => void }) {
  const t = useT();
  return (
    <aside
      aria-label={t("feuil.pro.title")}
      style={{ marginTop: 16, padding: "12px 14px", borderRadius: "var(--radius-md)", border: "1px solid var(--border)", background: "var(--surface-soft)", fontSize: 13.5, lineHeight: 1.55 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <strong>{t("feuil.pro.title")}</strong>
        <button style={{ ...ghostBtn, minHeight: 32, padding: "2px 10px", fontSize: 12 }} onClick={onDismiss}>
          {t("feuil.pro.dismiss")}
        </button>
      </div>
      <p style={{ margin: "6px 0 0" }}>{t("feuil.pro.local", { model })}</p>
      <p style={{ margin: "6px 0 0" }}>
        {t("feuil.pro.more")} <ProLink />
      </p>
    </aside>
  );
}

/** Une ligne courte, là où la limite se voit. */
export function ProLine({ reason }: { reason: "writing" | "generation" | "program_end" }) {
  const t = useT();
  return (
    <p style={{ color: "var(--muted)", fontSize: 13, margin: "8px 0 0" }}>
      {t(`feuil.pro.line.${reason}`)} <ProLink />
    </p>
  );
}
