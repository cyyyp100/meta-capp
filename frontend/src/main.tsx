import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { ConfirmProvider } from "@/components/ui/confirm";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import { App } from "./App";
import { initLaunchToken } from "./api/security";
// Polices embarquées : voir l'en-tête de fonts.css (aucun CDN).
import "./theme/fonts.css";
import "./theme/tokens.css";

// Avant tout rendu : capture du nonce de lancement (coque desktop) -> cookie.
initLaunchToken();

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* `delayDuration` court : dans une app de bureau la souris ne « survole
          pas par accident » comme sur le web, une infobulle lente frustre. */}
      <TooltipProvider delayDuration={250} skipDelayDuration={500}>
        <ConfirmProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ConfirmProvider>
        {/* Rendu en portail, hors du Router : les toasts survivent aux changements
            de route (une erreur d'import reste lisible après la navigation). */}
        <Toaster position="bottom-right" closeButton richColors={false} />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
