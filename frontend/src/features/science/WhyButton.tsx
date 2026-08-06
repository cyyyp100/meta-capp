import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";

import { useLangStore, useT } from "../../i18n";
import { whyContent, type WhyKey } from "./metacogContent";

export function WhyButton({ whyKey }: { whyKey: WhyKey }) {
  const [open, setOpen] = useState(false);
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const content = whyContent[lang][whyKey];

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} style={buttonStyle}>
        {t("sas.why")}
      </button>
      {open && <WhyDialog title={content.title} onClose={() => setOpen(false)} whyKey={whyKey} />}
    </>
  );
}

function WhyDialog({ title, whyKey, onClose }: { title: string; whyKey: WhyKey; onClose: () => void }) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const content = whyContent[lang][whyKey];
  const titleId = useId();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div onClick={onClose} style={overlay}>
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} onClick={(e) => e.stopPropagation()} style={dialog}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14, justifyContent: "space-between" }}>
          <h2 id={titleId} style={{ fontFamily: "var(--font-title)", fontSize: 23, lineHeight: 1.2, margin: 0 }}>
            {title}
          </h2>
          <button type="button" onClick={onClose} aria-label={t("common.close")} style={closeButton}>
            ×
          </button>
        </div>

        <WhyBlock label={t("why.principle")} text={content.principle} />
        <WhyBlock label={t("why.conclusion")} text={content.conclusion} />
        <WhyBlock label={t("why.in_app")} text={content.inApp} />

        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>
            {t("why.sources")}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
            {content.sources.map((source) => (
              <span key={source} style={sourceChip}>
                {source}
              </span>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginTop: 20, flexWrap: "wrap" }}>
          <Link to="/stats/science" style={scienceLink}>
            {t("why.full_page")}
          </Link>
          <button type="button" onClick={onClose} autoFocus style={primaryButton}>
            {t("common.close")}
          </button>
        </div>
      </div>
    </div>
  );
}

function WhyBlock({ label, text }: { label: string; text: string }) {
  return (
    <section style={{ marginTop: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 800, color: "var(--accent-hover)", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <p style={{ color: "var(--text-soft)", lineHeight: 1.55, margin: "5px 0 0" }}>{text}</p>
    </section>
  );
}

const buttonStyle: React.CSSProperties = {
  border: "1px solid var(--border)",
  background: "var(--surface)",
  color: "var(--accent-hover)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 13px",
  fontWeight: 800,
  cursor: "pointer",
};

const overlay: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.42)",
  display: "grid",
  placeItems: "center",
  zIndex: 300,
  padding: 16,
};

const dialog: React.CSSProperties = {
  width: "min(620px, 94vw)",
  maxHeight: "88vh",
  overflow: "auto",
  background: "var(--surface)",
  color: "var(--text)",
  borderRadius: "var(--radius-lg)",
  boxShadow: "var(--shadow-lg)",
  border: "1px solid var(--border)",
  padding: "var(--space-xl)",
};

const closeButton: React.CSSProperties = {
  width: 34,
  height: 34,
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--surface-soft)",
  color: "var(--text)",
  cursor: "pointer",
  fontSize: 22,
  lineHeight: 1,
};

const sourceChip: React.CSSProperties = {
  display: "inline-flex",
  border: "1px solid var(--border)",
  background: "var(--surface-soft)",
  color: "var(--text-soft)",
  borderRadius: 999,
  padding: "5px 10px",
  fontSize: 12,
  fontWeight: 700,
};

const scienceLink: React.CSSProperties = {
  color: "var(--accent-hover)",
  fontWeight: 800,
  textDecoration: "underline",
};

const primaryButton: React.CSSProperties = {
  border: "none",
  background: "var(--accent)",
  color: "#fff",
  borderRadius: "var(--radius-sm)",
  padding: "10px 18px",
  fontWeight: 800,
  cursor: "pointer",
};
