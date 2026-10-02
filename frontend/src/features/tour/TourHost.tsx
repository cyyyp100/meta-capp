// TourHost.tsx — Le conducteur de la visite : navigation, démarrage, bulle.
//
// Monté UNE fois, au-dessus des routes (`App.tsx`) et non dans `AppLayout` :
// le lecteur et la séance de langue sont plein écran, donc hors du layout. Tant
// que l'hôte y vivait, les étapes du chapitre lecture devenaient bien actives
// mais rien ne les peignait jamais — trois bulles sur cinq ne s'étaient donc
// jamais affichées à personne.
//
// C'est aussi lui qui NAVIGUE. Le store est synchrone et sans routeur (il est
// appelé depuis un écouteur d'événement natif, hors de tout composant) ; le
// `useNavigate` de react-router n'existe que dans l'arbre React. La table de
// marche dit où chaque bulle se joue, cet hôte s'y rend.
import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { usePreferences } from "../shell/usePreferences";
import { Coachmark } from "./Coachmark";
import { TOUR_STEPS, resolveRoute, useTour } from "./useTour";

export function TourHost() {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: preferences } = usePreferences();

  const running = useTour((s) => s.running);
  const index = useTour((s) => s.index);
  const demoDocId = useTour((s) => s.demoDocId);
  const hydrated = useTour((s) => s.hydrated);
  const done = useTour((s) => s.done);
  const hydrate = useTour((s) => s.hydrate);
  const start = useTour((s) => s.start);

  // L'état serveur fait autorité : le `localStorage` du webview ne survit pas à
  // une restauration de sauvegarde, et la visite recommencerait chez quelqu'un
  // qui l'a déjà faite.
  const storedDone = preferences?.preferences.tour_done;
  useEffect(() => {
    if (storedDone === undefined) return;
    hydrate(storedDone === "true");
  }, [storedDone, hydrate]);

  // Premier lancement : la visite part d'elle-même. C'est la seule bascule
  // automatique — partout ailleurs elle se demande.
  useEffect(() => {
    if (!hydrated || done || running) return;
    void start();
  }, [hydrated, done, running, start]);

  // Chaque étape sait où elle se joue ; on s'y rend si on n'y est pas déjà.
  const step = running ? TOUR_STEPS[index] : undefined;
  const route = step ? resolveRoute(step, demoDocId) : undefined;

  // Les commandes de l'application sont neutralisées tant que la visite tourne :
  // un clic sur « Terminer », sur un lien du rail ou sur une carte de document
  // enverrait ailleurs un parcours scripté qui n'a aucun moyen de se rattraper.
  //
  // On intercepte le CLIC, en phase de capture, et rien d'autre. Un calque qui
  // avale tous les événements — la première version — bloquait du même coup le
  // défilement de la page et le glissé horizontal du PDF, c'est-à-dire les
  // gestes que la visite est en train de montrer. Molette, glissé et sélection
  // de texte ne changent l'état de personne : ils restent libres.
  //
  // En capture sur `document`, donc avant que React ne distribue quoi que ce
  // soit : ses écouteurs sont posés sur la racine et sur le conteneur de portail
  // (`body`), tous deux plus bas dans le chemin. La bulle, portée dans `body`
  // par Radix, est la seule exception — sans quoi « Suivant » ne répondrait plus.
  //
  // Seconde exception : la cible d'une étape déclarée `interactive`, où le geste
  // EST la démonstration (retourner une carte, passer à la suivante). Sa cible,
  // et elle seule : le reste de l'écran reste inerte.
  const clickable = step?.interactive ? step.target : null;
  useEffect(() => {
    if (!running) return;
    const swallow = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('[data-slot="popover-content"]')) return;
      if (clickable && target?.closest(`[data-tour="${clickable}"]`)) return;
      event.preventDefault();
      event.stopPropagation();
    };
    document.addEventListener("click", swallow, true);
    return () => document.removeEventListener("click", swallow, true);
  }, [running, clickable]);

  useEffect(() => {
    if (route && location.pathname !== route) navigate(route);
  }, [route, location.pathname, navigate]);

  // La visite se termine TOUJOURS sur l'accueil, qu'on aille au bout (la
  // dernière étape y est déjà) ou qu'on l'abandonne en route. Abandonnée dans le
  // lecteur, elle laissait l'écran tel quel : le sas d'entrée de la démo restait
  // affiché, et « Continuer » ouvrait un document que la visite venait de rendre.
  //
  // `replace` : l'entrée d'historique du lecteur de démo pointe sur un document
  // qui n'existe plus, on ne doit pas pouvoir y revenir d'un « Précédent ».
  const wasRunning = useRef(false);
  useEffect(() => {
    const ended = wasRunning.current && !running;
    wasRunning.current = running;
    if (ended && location.pathname !== "/") navigate("/", { replace: true });
  }, [running, location.pathname, navigate]);

  if (!step) return null;
  return <Coachmark step={step} index={index} />;
}
