// HelpSection.tsx — Signaler un problème, noter le logiciel, à propos.
//
// « Signaler un problème » n'envoie RIEN. Il enveloppe l'export de logs qui
// existait déjà (`GET /api/data/export-logs`) : l'archive est téléchargée chez
// l'utilisateur, et c'est lui qui décide de la joindre à un message. Un envoi
// automatique de journaux serait exactement ce que l'édition locale promet de
// ne pas faire.
import { useQuery } from "@tanstack/react-query";
import { Download, ExternalLink } from "lucide-react";
import { useEffect, useRef } from "react";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { SettingsCard } from "./SettingsPrimitives";

import { useT } from "../../i18n";

/** Page publique du projet. En dur, comme toutes les URL sortantes de l'app. */
const PROJECT_PAGE = "https://github.com/cyyyp100/meta-capp";

export function HelpSection({ focusAbout = false }: { focusAbout?: boolean }) {
  const t = useT();
  const about = useRef<HTMLElement>(null);
  // La version vient du serveur (`server/config.APP_VERSION`) et n'est pas
  // recopiée ici : deux versions affichées finissent toujours par diverger.
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health });

  // « Aide ▸ À propos » du menu natif navigue vers /settings/about : la section
  // existe déjà dans la page, on l'amène simplement sous les yeux.
  useEffect(() => {
    if (focusAbout) about.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [focusAbout]);

  return (
    <>
      <SettingsCard title={t("settings.help.report")} description={t("settings.help.report_hint")}>
        <Button asChild variant="secondary">
          <a href="/api/data/export-logs" download>
            <Download className="size-4" aria-hidden />
            {t("data.export_logs")}
          </a>
        </Button>
      </SettingsCard>

      <SettingsCard title={t("settings.help.rate")}>
        <Button asChild variant="secondary">
          <a href={PROJECT_PAGE} target="_blank" rel="noreferrer noopener">
            <ExternalLink className="size-4" aria-hidden />
            {t("settings.help.rate")}
          </a>
        </Button>
      </SettingsCard>

      <section ref={about}>
        <SettingsCard title={t("user.about")} description={t("settings.about.version", { version: health?.version ?? "—" })}>
          <p className="m-0 text-sm leading-relaxed text-text-soft">{t("settings.about.blurb")}</p>
        </SettingsCard>
      </section>
    </>
  );
}
