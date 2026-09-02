// AppearanceSection.tsx — Thème, densité, taille du texte.
//
// Le thème a désormais TROIS états : clair, sombre et système. « Système » est
// l'option qui manquait — `tokens.css` déclarait déjà un bloc
// `prefers-color-scheme` que rien ne pouvait choisir.
import type { PreferenceKey, PreferencesPayload } from "@/api/client";
import { ChoiceRow, SettingsCard } from "./SettingsPrimitives";
import type { ThemeChoice } from "@/theme/useTheme";
import { useThemeStore } from "@/theme/useTheme";

import { useT } from "../../i18n";
import { useSetPreference } from "../shell/usePreferences";

export function AppearanceSection({ payload }: { payload: PreferencesPayload }) {
  const t = useT();
  const setPreference = useSetPreference();
  const choice = useThemeStore((s) => s.choice);
  const setTheme = useThemeStore((s) => s.setTheme);

  function set(key: PreferenceKey, value: string) {
    setPreference.mutate({ [key]: value });
  }

  return (
    <SettingsCard title={t("settings.section.appearance")}>
      <ChoiceRow<ThemeChoice>
        label={t("settings.theme")}
        hint={t("settings.theme_hint")}
        value={choice}
        options={[
          { value: "light", label: t("settings.theme.light") },
          { value: "dark", label: t("settings.theme.dark") },
          { value: "system", label: t("settings.theme.system") },
        ]}
        // Le store applique ET persiste : on ne double pas l'écriture ici, sinon
        // deux chemins écriraient la même préférence et pourraient diverger.
        onChange={(value) => setTheme(value)}
      />

      <ChoiceRow
        label={t("settings.density")}
        value={payload.preferences.density}
        options={[
          { value: "comfortable", label: t("settings.density.comfortable") },
          { value: "compact", label: t("settings.density.compact") },
        ]}
        onChange={(value) => set("density", value)}
      />

      <ChoiceRow
        label={t("settings.text_size")}
        value={payload.preferences.text_size}
        options={[
          { value: "small", label: t("settings.text_size.small") },
          { value: "normal", label: t("settings.text_size.normal") },
          { value: "large", label: t("settings.text_size.large") },
        ]}
        onChange={(value) => set("text_size", value)}
      />
    </SettingsCard>
  );
}
