// ReadingSection.tsx — Le rituel avant la lecture.
//
// Un seul réglage pour l'instant : la durée du sas d'entrée. C'est un temps de
// ralentissement que l'élève s'accorde ; à la fin, le sas attend son clic, il
// ne l'envoie nulle part de lui-même (cf. features/session/EntrySas.tsx).
import type { PreferencesPayload } from "@/api/client";

import { useT } from "../../i18n";
import { useSetPreference } from "../shell/usePreferences";
import { ChoiceRow, SettingsCard } from "./SettingsPrimitives";

export function ReadingSection({ payload }: { payload: PreferencesPayload }) {
  const t = useT();
  const setPreference = useSetPreference();
  // Les valeurs admises viennent du serveur (`services/preferences.py`) : la
  // liste n'est déclarée qu'une fois.
  const options = (payload.choices.entry_sas_s ?? []).map((value) => {
    const seconds = Number(value);
    return {
      value,
      label: seconds % 60 === 0 ? t("settings.entry_sas.minutes", { n: seconds / 60 }) : t("settings.entry_sas.seconds", { n: seconds }),
    };
  });

  return (
    <SettingsCard title={t("settings.section.reading")}>
      <ChoiceRow
        label={t("settings.entry_sas")}
        hint={t("settings.entry_sas_hint")}
        value={payload.preferences.entry_sas_s}
        options={options}
        onChange={(value) => setPreference.mutate({ entry_sas_s: value })}
      />
    </SettingsCard>
  );
}
