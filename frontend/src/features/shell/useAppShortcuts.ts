// useAppShortcuts.ts — Raccourcis globaux de l'application.
//
// Ils vivent ICI et non dans la barre de menu native parce que pywebview 6.2.1
// ne sait pas leur en donner : `MenuAction` n'a aucun paramètre de raccourci
// (le `# TODO` est dans `webview/menu.py`). Le menu affiche donc les entrées,
// et ce fichier fournit les raccourcis — un seul endroit les déclare.
//
// ⌘/Ctrl+O  : ouvrir un document (le même chemin que « Fichier ▸ Ouvrir »)
// ⌘/Ctrl+,  : Réglages (la convention macOS, honorée aussi sous Windows)
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

interface Options {
  onOpenDocument?: () => void;
}

export function useAppShortcuts({ onOpenDocument }: Options = {}): void {
  const navigate = useNavigate();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!event.metaKey && !event.ctrlKey) return;
      if (event.altKey) return;

      // Un raccourci ne doit jamais voler une frappe à un champ de saisie : le
      // lecteur, le brainstorming et le sas de sortie sont pleins de textareas.
      const target = event.target as HTMLElement | null;
      if (target?.isContentEditable) return;
      const tag = target?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

      if (event.key === "," && !typing) {
        event.preventDefault();
        navigate("/settings");
        return;
      }
      if ((event.key === "o" || event.key === "O") && onOpenDocument && !typing) {
        event.preventDefault();
        onOpenDocument();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate, onOpenDocument]);
}
