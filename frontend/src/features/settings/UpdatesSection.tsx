// UpdatesSection.tsx — Vérification des mises à jour (opt-in strict).
//
// Le risque principal de cette fonctionnalité est RÉPUTATIONNEL, pas technique :
// un produit qui promet « 100 % local » et contacte GitHub doit l'écrire, en
// clair, à l'endroit où on l'active. D'où le paragraphe de transparence — il
// n'est pas décoratif, il fait partie de la fonctionnalité.
//
// Côté serveur (`nwol/services/updates.py`) : un seul GET vers un hôte figé, la
// réponse traitée comme non fiable (seul le numéro de version en est extrait,
// validé par regex), aucune note de version affichée, aucune redirection
// suivie, échec silencieux. L'URL de téléchargement est EN DUR dans le binaire
// et n'est jamais celle de la réponse.
import { useMutation } from "@tanstack/react-query";
import { Download, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import type { PreferencesPayload, UpdateStatus } from "@/api/client";
import { Button } from "@/components/ui/button";
import { SettingsCard } from "./SettingsPrimitives";

import { useT } from "../../i18n";
import { useSetPreference } from "../shell/usePreferences";

export function UpdatesSection({ payload }: { payload: PreferencesPayload }) {
  const t = useT();
  const setPreference = useSetPreference();
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const enabled = payload.preferences.updates_check === "true";

  const check = useMutation({
    mutationFn: api.checkUpdates,
    onSuccess: setStatus,
    // Un échec de vérification n'est pas un événement : pas de toast, pas
    // d'alerte. On garde simplement l'état précédent.
    onError: () => setStatus(null),
  });

  return (
    <>
      <SettingsCard title={t("settings.updates.title")}>
        <label className="flex cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => {
              setStatus(null);
              setPreference.mutate({ updates_check: e.target.checked });
            }}
            className="mt-0.5 size-4 accent-[var(--accent)]"
          />
          <span className="text-sm font-semibold">{t("settings.updates.toggle")}</span>
        </label>

        <p className="mt-3 mb-0 flex gap-2.5 rounded-sm bg-surface-soft p-3.5 text-[13px] leading-relaxed text-text-soft">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-brand-ink" aria-hidden />
          <span>{t("settings.updates.transparency")}</span>
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2.5">
          <Button
            variant="secondary"
            size="sm"
            disabled={!enabled}
            pending={check.isPending}
            onClick={() => check.mutate()}
          >
            {t("settings.updates.check_now")}
          </Button>
          <span className="text-[13px] text-muted-foreground">
            {t("settings.updates.current", { version: status?.current ?? "—" })}
          </span>
        </div>

        <p className="mt-3 mb-0 text-sm">
          {!enabled
            ? t("settings.updates.disabled")
            : !status
              ? null
              : !status.checked
                ? t("settings.updates.unavailable")
                : status.update_available
                  ? t("settings.updates.available", { version: status.latest ?? "?" })
                  : t("settings.updates.up_to_date")}
        </p>
      </SettingsCard>

      {status?.update_available && (
        <SettingsCard title={t("settings.updates.download")} description={t("settings.updates.keeps_data")}>
          <div className="flex flex-wrap gap-2.5">
            {/* « Sauvegarder maintenant » AVANT d'ouvrir la page : c'est le geste
                que quelqu'un veut faire à cet instant, pas trois écrans plus loin. */}
            <Button asChild variant="secondary">
              <a href="/api/data/export" download>
                <Download className="size-4" aria-hidden />
                {t("settings.updates.backup_now")}
              </a>
            </Button>
            {/* `status.url` vaut TOUJOURS la constante serveur `RELEASES_PAGE` :
                le service ne remonte jamais une URL issue de la réponse GitHub. */}
            <Button asChild>
              <a href={status.url} target="_blank" rel="noreferrer noopener">
                {t("settings.updates.download")}
              </a>
            </Button>
          </div>
        </SettingsCard>
      )}
    </>
  );
}
