import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { useT } from "../i18n";

/** Une adresse inconnue (lien périmé, URL tapée dans le mode navigateur) :
 *  sans cette route, le layout n'affichait rien du tout à droite. */
export function NotFound() {
  const t = useT();
  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "var(--space-xl)", textAlign: "center" }}>
      <h1 style={{ fontFamily: "var(--font-title)", fontSize: 30, margin: "48px 0 12px" }}>{t("notfound.title")}</h1>
      <p style={{ color: "var(--text-soft)", fontSize: 15, lineHeight: 1.6, margin: "0 0 24px" }}>{t("notfound.body")}</p>
      <Link to="/" style={backLink}>
        <ArrowLeft className="size-4" aria-hidden />
        {t("notfound.back")}
      </Link>
    </div>
  );
}

const backLink: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  color: "var(--accent-ink)",
  textDecoration: "none",
  fontWeight: 800,
  fontSize: 13,
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface)",
  padding: "8px 12px",
};
