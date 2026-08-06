import { useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { SKILL_ORDER } from "../features/lang/skills";
import { scoreColor } from "../features/stats/labels";
import { useT } from "../i18n";

export function Lang() {
  const t = useT();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string | null>(null);

  const { data: languages } = useQuery({ queryKey: ["lang", "languages"], queryFn: api.languages });
  const { data: profile } = useQuery({
    queryKey: ["lang", "profile", selected],
    queryFn: () => api.languageProfile(selected as string),
    enabled: !!selected,
  });

  const selectedLang = languages?.find((l) => l.code === selected);

  // Nombre de colonnes réel de la grille (auto-fill responsive) : mesuré depuis le
  // style calculé, recalculé au redimensionnement. Sert à insérer l'encart stats
  // juste sous la LIGNE de la langue choisie (et non en fin de grille).
  const gridRef = useRef<HTMLDivElement>(null);
  const [cols, setCols] = useState(1);
  useEffect(() => {
    const el = gridRef.current;
    if (!el) return;
    const measure = () => {
      const n = getComputedStyle(el).gridTemplateColumns.split(" ").filter(Boolean).length;
      setCols(Math.max(1, n));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [languages?.length]);

  // Index de la dernière tuile de la ligne contenant la langue choisie : l'encart
  // s'insère juste après → il prend toute la largeur et pousse la ligne suivante.
  const selectedIndex = languages?.findIndex((l) => l.code === selected) ?? -1;
  const panelAfter =
    selectedIndex >= 0 && languages
      ? Math.min(Math.floor(selectedIndex / cols) * cols + cols - 1, languages.length - 1)
      : -1;

  function startLesson() {
    if (!selected) return;
    // La séance se joue en plein écran (comme le lecteur) ; on passe la langue en state.
    // Indice de placement (profil déjà chargé) : permet d'afficher le SAS d'entrée
    // d'emblée sans risquer de rebondir ensuite sur le test de niveau.
    const needsPlacement = !(profile?.profile as { placement_done?: number } | undefined)?.placement_done;
    navigate("/lang/lesson", {
      state: {
        language: selected,
        label: selectedLang?.label ?? selected,
        needsPlacement,
        rtl: selectedLang?.rtl ?? profile?.rtl ?? false,
      },
    });
  }

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", padding: "var(--space-xl)" }}>
      <h1 style={{ fontFamily: "var(--font-title)", fontSize: 32, margin: "0 0 4px" }}>{t("lang.title")}</h1>
      <p style={{ color: "var(--muted)", marginTop: 0 }}>{t("lang.subtitle")}</p>

      <div ref={gridRef} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: "var(--space-md)", marginTop: "var(--space-lg)" }}>
        {languages?.map((l, i) => (
          <Fragment key={l.code}>
            <button
              onClick={() => setSelected(l.code)}
              style={{
                padding: "20px 12px",
                borderRadius: "var(--radius-md)",
                border: `1px solid ${selected === l.code ? "var(--accent)" : "var(--border)"}`,
                background: selected === l.code ? "var(--accent-soft)" : "var(--surface)",
                cursor: "pointer",
                textAlign: "center",
                boxShadow: "var(--shadow-sm)",
              }}
            >
              <div style={{ fontSize: 34 }}>{l.flag}</div>
              <div style={{ fontWeight: 600, marginTop: 6, color: "var(--text)" }}>{l.label}</div>
            </button>

            {/* Encart stats inséré pleine largeur juste sous la ligne de la langue choisie. */}
            {i === panelAfter && selected && profile && (
              <div style={{ gridColumn: "1 / -1", background: "var(--surface)", border: "1px solid var(--accent)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-sm)", padding: "var(--space-lg)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <h2 style={{ fontSize: 16, margin: 0 }}>{selectedLang?.label}</h2>
                  <button onClick={startLesson} style={{ border: "none", background: "var(--accent)", color: "#fff", borderRadius: "var(--radius-sm)", padding: "10px 18px", fontWeight: 600, cursor: "pointer" }}>
                    {t("lang.start_lesson")}
                  </button>
                </div>
                <div style={{ display: "flex", gap: 28, marginTop: 14 }}>
                  <Stat label={t("lang.lessons")} value={String(profile.progress.total_lessons ?? 0)} />
                  <Stat label={t("lang.avg")} value={`${Math.round(profile.progress.avg_score)}%`} />
                  <Stat label={t("lang.level")} value={String((profile.profile as { level?: string }).level ?? "A1")} />
                </div>

                {/* Analyse poussée : score 0–100 par compétence. */}
                {(() => {
                  const skills = profile.progress.skills ?? {};
                  const rows = SKILL_ORDER.filter((k) => skills[k]);
                  if (rows.length === 0) return null;
                  return (
                    <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>{t("lang.skills_title")}</div>
                      <div style={{ display: "grid", gap: 9 }}>
                        {rows.map((k) => (
                          <SkillBar key={k} label={t(`skill.${k}`)} value={skills[k].score} />
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}
          </Fragment>
        ))}
      </div>
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

function SkillBar({ label, value }: { label: string; value: number }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
        <span>{label}</span>
        <span style={{ color: scoreColor(v), fontWeight: 700 }}>{Math.round(v)}</span>
      </div>
      <div style={{ height: 8, borderRadius: 999, background: "var(--border)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${v}%`, background: scoreColor(v), borderRadius: 999 }} />
      </div>
    </div>
  );
}
