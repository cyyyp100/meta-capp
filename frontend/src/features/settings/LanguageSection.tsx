// LanguageSection.tsx — FR/EN.
//
// Ce réglage n'est pas cosmétique : `nwol/i18n.py` pilote aussi la langue des
// prompts LLM. Le dire ici évite qu'on cherche ailleurs pourquoi Gemma a changé
// de langue.
import type { PreferencesPayload } from "@/api/client";
import { ChoiceRow, SettingsCard } from "./SettingsPrimitives";

import type { Lang } from "../../i18n";
import { useLangStore, useT } from "../../i18n";

export function LanguageSection({ payload }: { payload: PreferencesPayload }) {
  const t = useT();
  const { lang, setLang } = useLangStore();

  const options = (payload.supported_langs.length ? payload.supported_langs : ["fr", "en"])
    .filter((code): code is Lang => code === "fr" || code === "en")
    .map((code) => ({ value: code, label: code.toUpperCase() }));

  return (
    <SettingsCard title={t("common.language")}>
      <ChoiceRow<Lang>
        label={t("common.language")}
        hint={t("settings.lang_hint")}
        value={lang}
        options={options}
        onChange={(value) => setLang(value)}
      />
      {/* Le menu natif est construit une fois, au démarrage : on l'annonce
          plutôt que de laisser croire à un bug de traduction. */}
      <p className="mt-1 mb-0 text-[13px] text-muted-foreground">{t("settings.menu_lang_note")}</p>
    </SettingsCard>
  );
}
