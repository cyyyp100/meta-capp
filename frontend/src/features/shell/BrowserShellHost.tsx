// BrowserShellHost.tsx — Mode navigateur : présence de l'onglet, écran d'arrêt.
//
// En fenêtre native, la fermer arrête tout. Dans un navigateur, le serveur ne
// sait pas qu'on a fermé l'onglet : chaque onglet tient donc un WebSocket de
// présence, et le serveur s'arrête quelques minutes après le départ du dernier
// (nwol/services/lifecycle.py). Un WebSocket et non une requête périodique :
// un navigateur bride les minuteries d'un onglet en arrière-plan, il ne ferme
// pas ses sockets — un élève qui lit dans un autre onglet resterait « absent ».
//
// Monté au-dessus des routes (App.tsx) : le lecteur est plein écran, hors du
// layout, et un onglet ouvert sur le lecteur est bien un onglet ouvert.
import { useQuery } from "@tanstack/react-query";
import { Power } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { isDesktopShell } from "@/api/platform";
import { wsTokenSuffix } from "@/api/security";
import { Button } from "@/components/ui/button";

import { useT } from "../../i18n";

// Code de fermeture qu'uvicorn envoie à chaque WebSocket quand il s'arrête.
const SERVER_STOPPING = 1012;

/** Vrai quand la coque sert l'app à un navigateur — faux en fenêtre native et en dev. */
export function useBrowserMode(): boolean {
  const { data } = useQuery({
    queryKey: ["shell"],
    queryFn: api.shell,
    enabled: !isDesktopShell(),
    staleTime: Infinity,
  });
  return data?.browser_mode ?? false;
}

export function BrowserShellHost() {
  const browserMode = useBrowserMode();
  const [stopped, setStopped] = useState(false);

  useEffect(() => {
    if (!browserMode) return;
    let ws: WebSocket | null = null;
    let retry: number | undefined;
    let disposed = false;
    const proto = location.protocol === "https:" ? "wss" : "ws";

    const connect = () => {
      let opened = false;
      ws = new WebSocket(`${proto}://${location.host}/api/shell/presence${wsTokenSuffix()}`);
      ws.onopen = () => {
        opened = true;
      };
      ws.onclose = (event) => {
        if (disposed) return;
        // Le serveur s'arrête (Quitter, arrêt automatique, Ctrl+C), ou ne
        // répond plus du tout : il n'y a plus rien derrière cet onglet.
        if (event.code === SERVER_STOPPING || !opened) {
          setStopped(true);
          return;
        }
        // Coupure d'une connexion établie, serveur toujours là : on se
        // reconnecte — sinon le serveur nous croirait partis.
        retry = window.setTimeout(connect, 1000);
      };
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(retry);
      ws?.close();
    };
  }, [browserMode]);

  return stopped ? <StoppedScreen /> : null;
}

function StoppedScreen() {
  const t = useT();
  // Au-dessus de TOUT, visite guidée comprise (`z-120`/`z-130`, Coachmark) :
  // plus rien derrière cet écran ne répond.
  return (
    <div
      role="alertdialog"
      aria-labelledby="shell-stopped-title"
      className="fixed inset-0 z-[200] grid place-items-center bg-background p-8"
    >
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <Power className="size-8 text-muted-foreground" aria-hidden />
        <h1 id="shell-stopped-title" className="font-serif text-h2 font-bold tracking-tight">
          {t("shell.stopped_title")}
        </h1>
        <p className="text-sm text-text-soft">{t("shell.stopped_body")}</p>
        {/* Relancer Meta-Capp rouvre un onglet de toute façon ; ce bouton sert
            à qui l'a relancé autrement, ou à une coupure qui n'en était pas une. */}
        <Button variant="secondary" onClick={() => location.reload()}>
          {t("shell.reload")}
        </Button>
      </div>
    </div>
  );
}
