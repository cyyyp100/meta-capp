// ProfileSection.tsx — Nom, série d'étude, nombre de sessions.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { PreferencesPayload, StudyStreak } from "@/api/client";
import { Button } from "@/components/ui/button";
import { SettingsCard } from "./SettingsPrimitives";

import { useT } from "../../i18n";
import { useSetUserName } from "../shell/usePreferences";

export function ProfileSection({
  payload,
  streak,
}: {
  payload: PreferencesPayload;
  streak?: StudyStreak;
}) {
  const t = useT();
  const setName = useSetUserName();
  const [draft, setDraft] = useState(payload.user.name);
  const { data: overview } = useQuery({ queryKey: ["stats", "overview"], queryFn: api.statsOverview });

  // Le nom peut changer ailleurs (restauration d'une sauvegarde) : le brouillon
  // suit la source tant que l'utilisateur n'a rien tapé de différent.
  useEffect(() => setDraft(payload.user.name), [payload.user.name]);

  async function save() {
    const clean = draft.trim();
    if (!clean) {
      toast.error(t("settings.name_error"));
      return;
    }
    try {
      await setName.mutateAsync(clean);
      toast.success(t("settings.name_saved"));
    } catch {
      toast.error(t("settings.name_error"));
    }
  }

  return (
    <>
      <SettingsCard title={t("settings.name")} description={t("settings.name_hint")}>
        <div className="flex flex-wrap items-center gap-2.5">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void save();
            }}
            className="h-9 min-w-56 flex-1 rounded-sm border border-border bg-background px-3 text-sm
                       text-foreground outline-none transition-[border-color,box-shadow]
                       duration-fast ease-brand focus:border-brand focus:ring-[3px] focus:ring-ring/30"
          />
          <Button
            onClick={() => void save()}
            pending={setName.isPending}
            disabled={draft.trim() === payload.user.name}
          >
            {t("common.save")}
          </Button>
        </div>
      </SettingsCard>

      <SettingsCard title={t("settings.section.profile")}>
        <dl className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-4">
          <Stat label={t("settings.streak_current")} value={t("settings.days", { n: streak?.streak ?? 0 })} />
          <Stat
            label={t("settings.streak_longest")}
            value={t("settings.days", { n: streak?.longest_streak ?? 0 })}
          />
          <Stat label={t("settings.sessions_count")} value={String(overview?.sessions_count ?? 0)} />
        </dl>
        {/* Le ton du streak est un choix de produit : on rappelle la tolérance
            plutôt que d'agiter la perte de la série. */}
        <p className="mt-3.5 mb-0 text-[13px] text-muted-foreground">
          {(streak?.streak ?? 0) > 0 ? t("streak.grace") : t("streak.none")}
        </p>
      </SettingsCard>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] font-bold tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="m-0 mt-1 text-h2 font-bold tabular-nums">{value}</dd>
    </div>
  );
}
