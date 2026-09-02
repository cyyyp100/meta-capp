// SettingsPrimitives.tsx — Les deux briques de l'écran Réglages.
//
// Elles vivaient dans `routes/Settings.tsx`, que les six sections importaient
// en retour : la route dépendait des sections, et les sections de la route. Ça
// compilait, mais c'est un cycle — et le premier import ajouté dans le mauvais
// sens l'aurait rendu visible d'un coup.
import { Button } from "@/components/ui/button";

/** Encadré de section — le seul conteneur de cet écran, pour que les six
 *  sections aient exactement la même assise. */
export function SettingsCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-5 rounded-md border border-border bg-surface p-5.5 shadow-e1">
      <h2 className="m-0 text-h3 font-bold">{title}</h2>
      {description && <p className="mt-1.5 mb-0 text-sm text-muted-foreground">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Groupe de boutons radio en ligne — thème, densité, taille du texte, langue.
 *  `aria-pressed` porte l'état ; la couleur ne fait que le doubler. */
export function ChoiceRow<T extends string>({
  label,
  hint,
  value,
  options,
  onChange,
}: {
  label: string;
  hint?: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="mb-4 last:mb-0">
      <div className="mb-2 text-sm font-semibold">{label}</div>
      <div role="group" aria-label={label} className="flex flex-wrap gap-2">
        {options.map((option) => (
          <Button
            key={option.value}
            type="button"
            size="sm"
            variant={value === option.value ? "default" : "secondary"}
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>
      {hint && <p className="mt-2 mb-0 text-[13px] text-muted-foreground">{hint}</p>}
    </div>
  );
}
