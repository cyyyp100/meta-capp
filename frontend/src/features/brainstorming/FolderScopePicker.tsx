// FolderScopePicker.tsx — Dossier de la bibliothèque auquel une discussion est liée.
//
// Lié, Gemma ne puise plus que dans les documents de ce dossier et de ses
// sous-dossiers (surlignages, flashcards, Q&R, erreurs) ; la politique vit dans
// `services/brainstorm.py`, ce composant ne fait que choisir l'id. Le choix
// reste modifiable : il vaut pour les messages suivants.
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Folder, Library } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import { api } from "../../api/client";
import { useT } from "../../i18n";
import { flattenFolders } from "../library/folderTree";

const ALL = "all";

export function FolderScopePicker({
  folderId,
  folderName,
  onChange,
}: {
  folderId: number | null;
  folderName: string | null;
  onChange: (folderId: number | null) => void;
}) {
  const t = useT();
  // Même clé que la bibliothèque : un dossier créé là-bas apparaît ici sans rechargement.
  const { data: tree } = useQuery({ queryKey: ["library", "folders"], queryFn: api.folders });
  const folders = flattenFolders(tree ?? []);
  const linked = folderId !== null;

  return (
    <DropdownMenu>
      {/* Le déclencheur porte lui-même le style du bouton : `asChild` + <Button>
          perdrait la ref sous React 18 (Button n'est pas un forwardRef), et le
          menu, sans ancre, ne serait jamais positionné. */}
      <DropdownMenuTrigger
        aria-label={t("brainstorm.scope_label")}
        className={cn(
          buttonVariants({ variant: "chip", size: "sm" }),
          "max-w-[240px]",
          linked && "border-brand bg-brand-soft text-accent-foreground",
        )}
      >
        {linked ? <Folder aria-hidden /> : <Library aria-hidden />}
        <span className="truncate">{linked ? folderName || "…" : t("brainstorm.scope_all")}</span>
        <ChevronDown className="size-3.5 opacity-70" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="text-xs text-muted-foreground">{t("brainstorm.scope_label")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={linked ? String(folderId) : ALL}
          onValueChange={(value) => onChange(value === ALL ? null : Number(value))}
        >
          <DropdownMenuRadioItem value={ALL}>
            <Library aria-hidden />
            {t("brainstorm.scope_all")}
          </DropdownMenuRadioItem>
          {folders.length > 0 && <DropdownMenuSeparator />}
          {folders.map((folder) => (
            <DropdownMenuRadioItem
              key={folder.id}
              value={String(folder.id)}
              // Indentation de l'arbre, en plus du retrait de l'indicateur radio (pl-8).
              style={{ paddingLeft: 32 + folder.depth * 14 }}
            >
              <Folder aria-hidden />
              <span className="min-w-0 flex-1 truncate">{folder.name}</span>
              <span className="text-xs text-muted-foreground">{folder.total_count}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {folders.length === 0 && (
          <DropdownMenuItem disabled className="text-xs">
            {t("brainstorm.no_folders")}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
