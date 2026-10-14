// ClikodaSection.tsx — Quel modèle fait tourner Clikoda, et peut-il tourner ?
//
// Cette section existe parce que l'application ne disait JAMAIS que Clikoda était
// absente : la pastille du lecteur ne reflétait que le WebSocket local, et sur une
// machine qui ne pouvait pas charger le modèle, l'assistant se taisait sans un mot.
//
// Trois règles tenues ici :
//   1. Rien n'est bloqué. Un modèle non installé ou trop lourd reste choisissable
//      — c'est un choix, et on dit ce qu'il coûtera plutôt que de l'interdire.
//   2. Aucun bouton « installer ». Un `ollama pull` lancé par l'application serait
//      un téléchargement réseau, et cette édition n'a qu'un seul appel sortant
//      (la vérification de mise à jour, opt-in). On donne la commande à copier.
//   3. Le vocabulaire des modèles vient du SERVEUR (`payload.choices.llm_model`,
//      lui-même la table `config/settings.LLM_MODELS`) : il n'est pas réécrit ici.
//      Même chose pour le mode économe : ses valeurs (`choices.llm_economy`), sa
//      décision et sa raison (`status.economy_reason`) viennent du serveur ; le
//      composant ne compare jamais un nom de modèle ni une quantité de mémoire.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Cpu } from "lucide-react";
import { useState } from "react";

import type { LlmStatus, PreferencesPayload } from "@/api/client";
import { Button } from "@/components/ui/button";

import { useT } from "../../i18n";
import { LLM_STATUS_KEY, useLlmStatus } from "../shell/useLlmStatus";
import { useSetPreference } from "../shell/usePreferences";
import { SettingsCard, ChoiceRow } from "./SettingsPrimitives";

export function ClikodaSection({ payload }: { payload: PreferencesPayload }) {
  const t = useT();
  const queryClient = useQueryClient();
  const setPreference = useSetPreference();
  const { data: status } = useLlmStatus();
  const [copied, setCopied] = useState(false);

  const copy = useMutation({
    // Presse-papiers local, rien de plus. Un échec (contexte non sécurisé) n'est
    // pas un événement : la commande reste lisible et sélectionnable à l'écran.
    mutationFn: async (text: string) => navigator.clipboard?.writeText(text),
    onSuccess: () => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    },
    onError: () => setCopied(false),
  });

  const catalog = new Map((status?.catalog ?? []).map((entry) => [entry.name, entry]));
  const options = (payload.choices.llm_model ?? []).map((value) => {
    if (value === "auto") return { value, label: t("settings.clikoda.auto") };
    const entry = catalog.get(value);
    // Tant que l'état n'est pas là, le nom seul : une taille « ? Go » n'informe
    // personne et clignoterait à chaque ouverture de l'écran.
    if (!entry) return { value, label: value };
    const tier = t(`settings.clikoda.tier_${entry.tier ?? "standard"}`);
    const detail = t("settings.clikoda.option", { tier, gb: entry.download_gb ?? "?" });
    // « Trop lourd » passe devant « pas installé » : conseiller un
    // téléchargement de 20 Go à une machine qui ne pourra pas le charger est
    // le pire des deux avertissements possibles.
    const warning = !entry.fits
      ? ` — ${t("settings.clikoda.too_big")}`
      : !entry.installed
        ? ` — ${t("settings.clikoda.not_installed")}`
        : "";
    return { value, label: `${value} · ${detail}${warning}` };
  });

  return (
    <SettingsCard title={t("settings.clikoda.title")}>
      <ChoiceRow
        label={t("settings.clikoda.model")}
        hint={t("settings.clikoda.model_hint")}
        value={payload.preferences.llm_model}
        options={options}
        onChange={(value) => {
          // Un seul chemin d'écriture (`POST /api/preferences`), puis on
          // redemande l'état : c'est cet appel qui, côté serveur, journalise le
          // changement et calibre le nouveau modèle.
          setPreference.mutate(
            { llm_model: value },
            { onSuccess: () => queryClient.invalidateQueries({ queryKey: LLM_STATUS_KEY }) },
          );
        }}
      />

      <ChoiceRow
        label={t("settings.clikoda.economy")}
        hint={t("settings.clikoda.economy_hint")}
        value={payload.preferences.llm_economy}
        options={(payload.choices.llm_economy ?? []).map((value) => ({
          value,
          label: t(`settings.clikoda.economy_${value}`),
        }))}
        onChange={(value) => {
          // Le mode change les budgets de toutes les générations : l'état est
          // redemandé, comme après un changement de modèle.
          setPreference.mutate(
            { llm_economy: value },
            { onSuccess: () => queryClient.invalidateQueries({ queryKey: LLM_STATUS_KEY }) },
          );
        }}
      />

      {status && <ClikodaState status={status} onCopy={(text) => copy.mutate(text)} copied={copied} />}
    </SettingsCard>
  );
}

function ClikodaState({
  status,
  onCopy,
  copied,
}: {
  status: LlmStatus;
  onCopy: (text: string) => void;
  copied: boolean;
}) {
  const t = useT();
  const installed = status.installed.map((entry) => entry.name);
  // La phrase vient de l'énumération fermée du serveur : les mots vivent dans
  // les dictionnaires i18n, en un seul exemplaire (cf. nwol/services/llm_models).
  const reason = status.reason
    ? t(`settings.clikoda.reason_${status.reason}`, { model: status.requested_missing ?? status.model })
    : "";
  const needsPull = status.reason === "model_missing" || status.reason === "no_model";

  return (
    <div className="mt-1">
      <div className="mb-2 text-sm font-semibold">{t("settings.clikoda.state")}</div>
      <p className="mt-0 mb-0 flex gap-2.5 rounded-sm bg-surface-soft p-3.5 text-[13px] leading-relaxed text-text-soft">
        <Cpu className="mt-0.5 size-4 shrink-0 text-brand-ink" aria-hidden />
        <span>
          {t("settings.clikoda.active_model", { model: status.model })}{" "}
          {status.ram_gb === null
            ? t("settings.clikoda.ram_unknown")
            : t("settings.clikoda.ram", { gb: status.ram_gb })}{" "}
          {status.throughput.measured && status.throughput.output_tokens_per_s
            ? t("settings.clikoda.speed", { tps: status.throughput.output_tokens_per_s })
            : t("settings.clikoda.speed_unmeasured")}{" "}
          {installed.length
            ? t("settings.clikoda.installed", { names: installed.join(", ") })
            : t("settings.clikoda.installed_none")}{" "}
          {status.economy && status.economy_reason
            ? t("settings.clikoda.economy_state_on", { why: t(`settings.clikoda.economy_why_${status.economy_reason}`) })
            : t("settings.clikoda.economy_state_off")}
        </span>
      </p>

      {reason && <p className="mt-3 mb-0 text-sm text-warning">{reason}</p>}

      {needsPull && (
        <div className="mt-3">
          <p className="mt-0 mb-1.5 text-[13px] text-muted-foreground">{t("settings.clikoda.pull_hint")}</p>
          <div className="flex flex-wrap items-center gap-2.5">
            <code className="rounded-sm bg-surface-soft px-2.5 py-1.5 text-[13px]">{status.pull_command}</code>
            <Button variant="secondary" size="sm" onClick={() => onCopy(status.pull_command)}>
              {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
              {copied ? t("settings.clikoda.copied") : t("settings.clikoda.copy")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
