import { Link } from "react-router-dom";

import { Card } from "../components/Card";
import { scienceContent, type ScienceCard } from "../features/science/metacogContent";
import { useLangStore, useT } from "../i18n";

export function ScienceSources() {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const content = scienceContent[lang];

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "var(--space-xl)" }}>
      <Link to="/stats" style={backLink}>
        {t("science.back")}
      </Link>

      <header style={{ margin: "22px 0 var(--space-lg)" }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "var(--accent)", letterSpacing: 1, textTransform: "uppercase" }}>
          {t("science.label")}
        </div>
        <h1 style={{ fontFamily: "var(--font-title)", fontSize: 34, lineHeight: 1.12, margin: "8px 0 12px" }}>
          {content.title}
        </h1>
        <div style={{ display: "grid", gap: 8, color: "var(--text-soft)", fontSize: 15, lineHeight: 1.65, maxWidth: 900 }}>
          {content.intro.map((p) => (
            <p key={p} style={{ margin: 0 }}>
              {p}
            </p>
          ))}
        </div>
      </header>

      <Card style={{ marginBottom: "var(--space-lg)" }}>
        <SectionTitle>{content.definition.title}</SectionTitle>
        <p style={paragraph}>{content.definition.body}</p>
      </Card>

      <Card style={{ marginBottom: "var(--space-lg)" }}>
        <SectionTitle>{content.flowTitle}</SectionTitle>
        <p style={mutedParagraph}>{content.flowIntro}</p>
        <div style={flowGrid}>
          {content.flowSteps.map((step, index) => (
            <div key={step} style={flowStep}>
              <div style={flowNumber}>{index + 1}</div>
              <div>{step}</div>
            </div>
          ))}
        </div>
      </Card>

      {content.sections.map((section) => (
        <Card key={section.id} style={{ marginBottom: "var(--space-lg)" }}>
          <SectionTitle>{section.title}</SectionTitle>
          {section.intro && <p style={mutedParagraph}>{section.intro}</p>}
          <div style={cardGrid}>
            {section.cards.map((card) => (
              <ScienceInfoCard key={card.title} card={card} />
            ))}
          </div>
        </Card>
      ))}

      <Card>
        <SectionTitle>{content.referencesTitle}</SectionTitle>
        <p style={mutedParagraph}>{content.referencesIntro}</p>
        <div style={{ display: "grid", gap: 10 }}>
          {content.references.map((ref) => (
            <div key={`${ref.authors}-${ref.doi ?? ref.detail}`} style={referenceCard}>
              <div style={{ fontWeight: 800, color: "var(--text)" }}>{ref.authors}</div>
              <div style={{ color: "var(--text-soft)", fontSize: 13, lineHeight: 1.5 }}>{ref.detail}</div>
              {ref.doi && (
                <a href={`https://doi.org/${ref.doi}`} target="_blank" rel="noreferrer" style={doiLink}>
                  DOI: {ref.doi}
                </a>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function ScienceInfoCard({ card }: { card: ScienceCard }) {
  const t = useT();

  return (
    <div style={infoCard}>
      <h3 style={{ fontSize: 15, margin: 0, color: "var(--text)" }}>{card.title}</h3>
      <p style={{ ...paragraph, fontSize: 13, marginTop: 7 }}>{card.body}</p>
      {(card.user || card.system) && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 8, marginTop: 10 }}>
          {card.user && <MiniBlock label={t("science.visible")} text={card.user} />}
          {card.system && <MiniBlock label={t("science.system")} text={card.system} />}
        </div>
      )}
    </div>
  );
}

function MiniBlock({ label, text }: { label: string; text: string }) {
  return (
    <div style={{ background: "var(--surface-soft)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "9px 10px" }}>
      <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ color: "var(--text-soft)", fontSize: 12, lineHeight: 1.45, marginTop: 3 }}>{text}</div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 style={{ fontSize: 17, fontWeight: 800, margin: "0 0 12px" }}>{children}</h2>;
}

const backLink: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  color: "var(--accent-hover)",
  textDecoration: "none",
  fontWeight: 800,
  fontSize: 13,
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface)",
  padding: "8px 12px",
};

const paragraph: React.CSSProperties = {
  color: "var(--text-soft)",
  lineHeight: 1.62,
  margin: 0,
};

const mutedParagraph: React.CSSProperties = {
  ...paragraph,
  color: "var(--muted)",
  marginBottom: 14,
};

const cardGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
  gap: 12,
};

const infoCard: React.CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-md)",
  padding: 14,
  background: "var(--surface)",
};

const flowGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
  gap: 10,
};

const flowStep: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: 10,
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-soft)",
  color: "var(--text-soft)",
  padding: 12,
  lineHeight: 1.45,
};

const flowNumber: React.CSSProperties = {
  width: 24,
  height: 24,
  flex: "0 0 auto",
  borderRadius: "50%",
  display: "grid",
  placeItems: "center",
  background: "var(--accent-soft)",
  color: "var(--accent-hover)",
  fontWeight: 800,
  fontSize: 12,
};

const referenceCard: React.CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-soft)",
  padding: "11px 12px",
};

const doiLink: React.CSSProperties = {
  display: "inline-block",
  marginTop: 5,
  color: "var(--accent-hover)",
  fontWeight: 700,
  fontSize: 12,
  overflowWrap: "anywhere",
};
