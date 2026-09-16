// Coachmark.tsx — Une bulle ancrée sur un vrai élément de l'interface.
//
// Rien de nouveau n'est installé pour ça : `popover.tsx` (Radix) sait déjà
// positionner une bulle sur un déclencheur en gérant le dépassement de
// viewport, et c'est exactement le primitif d'une coach mark. Une bibliothèque
// de tour apporterait son propre positionnement, son propre voile et son propre
// vocabulaire d'animation — trois doublons.
//
// Le voile est un calque SVG masqué : un rectangle noir à 55 % couvrant l'écran,
// dans lequel un masque perce la (ou les) cible(s) de l'étape. C'était un
// `box-shadow` de très grand rayon, qui ne sait éclairer QU'UNE zone — or une
// étape peut avoir besoin d'en montrer deux (la réponse de Gemma et le passage
// qu'elle surligne dans la page, qui sinon reste dans le noir).
//
// Il ne prend AUCUN événement : ni clic, ni molette, ni glissé. Neutraliser les
// commandes de l'application pendant la visite est nécessaire — un clic de trop
// dans le décor la fait dérailler — mais c'est le travail d'un intercepteur de
// CLIC (`TourHost`), pas d'un calque qui avale tout. Un calque qui avale tout
// gèle aussi le défilement de la page et le glissé du PDF, c'est-à-dire les
// gestes qu'on est justement en train d'expliquer.
import { AnimatePresence, motion, useIsPresent, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";

import { useT } from "../../i18n";
import type { TourStepDef } from "./steps";
import { TOUR_STEPS, useTour } from "./useTour";

/** Marge autour de la découpe : coller au pixel près donne un halo qui « pince »
 *  l'élément. */
const PADDING = 8;

/** Les deux temps d'un changement d'étape, en secondes.
 *
 *  L'étape quittée SORT, puis l'étape suivante ENTRE — jamais les deux à la
 *  fois (`mode="wait"` sur l'`AnimatePresence`). C'était un fondu enchaîné de
 *  280 ms : deux voiles superposés le temps du croisement, et deux bulles à
 *  l'écran, l'ancienne encore pleine sous la nouvelle. Une visite qui explique
 *  l'écran ne peut pas se permettre d'en montrer deux versions à la fois.
 *
 *  La sortie est plus courte que l'entrée : on efface ce qu'on a fini de lire,
 *  on prend le temps de poser ce qu'on va lire. Même courbe que `tokens.css`. */
const LEAVE_S = 0.32;
const ENTER_S = 0.5;
const EASE: [number, number, number, number] = [0.33, 1, 0.68, 1];

/** Sondages infructueux (500 ms chacun) avant de renoncer à une cible.
 *
 *  Cinq secondes, et non deux : une étape qui change de route attend le
 *  chargement du morceau de code de l'écran PUIS la requête du document. Trop
 *  court, la visite sautait l'entrée du lecteur sur une machine lente — un saut
 *  qui ne dit pas son nom, donc le pire des deux comportements. */
const MISSING_LIMIT = 10;

/** Hauteur majorée d'une bulle : un titre sur deux lignes, quatre de texte et
 *  la rangée de boutons. Sert à savoir si elle tiendrait au-dessus ou en
 *  dessous d'une cible — sa largeur, elle, se mesure exactement. */
const BUBBLE_HEIGHT = 240;

/** Largeur réelle de la bulle. `w-80` vaut 20 rem, et la racine est mise à
 *  l'échelle par le réglage de taille de texte : 320 px en dur se tromperait
 *  chez quiconque a grossi l'interface. */
function bubbleWidth(): number {
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  return 20 * rem;
}

function intersectsViewport(rect: DOMRect): boolean {
  return (
    rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth
  );
}

/**
 * L'ancre de la bulle : la partie visible de la cible, rétrécie jusqu'à ce que
 * la bulle tienne du côté demandé.
 *
 * Deux pannes distinctes, un seul remède. D'abord une cible plus grande que la
 * fenêtre — page de PDF, panneau docké de haut en bas : ancrée sur sa boîte
 * COMPLÈTE, la bulle se posait le long d'un bord situé hors cadre, et Radix la
 * tronquait contre la fenêtre. Ensuite, et c'est le cas vicieux : une cible
 * large laisse parfois trop peu de place des DEUX côtés (une page de 820 px
 * dans une fenêtre de 1280 en laisse 230 de chaque côté, la bulle en demande
 * 336). Radix bascule alors d'un côté à l'autre, ne trouve de place nulle part
 * — son `shift` ne joue que sur l'axe transverse — et la laisse déborder.
 *
 * On rétrécit donc l'ANCRE, jamais la découpe : la bulle vient se poser par
 * dessus la cible, ce qui est moins bien qu'à côté et infiniment mieux que hors
 * de l'écran. La découpe, elle, garde la boîte entière — c'est l'objet qu'on
 * désigne, et l'éclairer à moitié parce qu'il dépasse n'aurait aucun sens.
 */
function anchorFor(rect: DOMRect, side: "top" | "right" | "bottom" | "left") {
  const margin = 8;
  const gap = 16; // `sideOffset` de la bulle
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let left = Math.max(rect.left, margin);
  let top = Math.max(rect.top, margin);
  let right = Math.min(rect.right, vw - margin);
  let bottom = Math.min(rect.bottom, vh - margin);
  // Cible entièrement hors cadre : on rend sa boîte telle quelle, Radix fera
  // au mieux — mais `measure()` ne devrait pas nous mettre dans ce cas.
  if (right <= left || bottom <= top) {
    return { top: rect.top, left: rect.left, width: rect.width, height: rect.height };
  }

  const bw = bubbleWidth();
  if (side === "right") right = Math.max(left + 1, Math.min(right, vw - margin - gap - bw));
  if (side === "left") left = Math.min(right - 1, Math.max(left, margin + bw + gap));
  if (side === "bottom") bottom = Math.max(top + 1, Math.min(bottom, vh - margin - gap - BUBBLE_HEIGHT));
  if (side === "top") top = Math.min(bottom - 1, Math.max(top, margin + BUBBLE_HEIGHT + gap));

  return { top, left, width: right - left, height: bottom - top };
}

export function Coachmark({ step, index }: { step: TourStepDef; index: number }) {
  const t = useT();
  const reduce = useReducedMotion();
  const next = useTour((s) => s.next);
  const skip = useTour((s) => s.skip);
  // La cible de l'étape, suivie de ce qu'elle veut révéler en plus. `rects[0]`
  // est toujours la cible : c'est elle qui ancre la bulle.
  const targets = useMemo(() => [step.target, ...(step.reveal ?? [])], [step.target, step.reveal]);
  const [rects, setRects] = useState<DOMRect[]>([]);

  // La cible est résolue par `data-tour` : aucune `ref` à faire remonter, aucune
  // signature de composant modifiée pour la visite.
  //
  // Un attribut, une cible. `querySelector` prend le PREMIER du document : deux
  // éléments portant le même `data-tour` font pointer la bulle sur celui qui
  // est le plus haut dans le DOM, pas sur celui qu'on visait. La barre latérale
  // en portait, et les bulles désignaient le rail au lieu du bouton d'import et
  // du radar.
  useEffect(() => {
    // `measure()` juste en dessous repose ou efface le rectangle : pas besoin de
    // le remettre à zéro ici, ce qui déclencherait un rendu de plus par étape.
    let missing = 0;
    let scrolled = false;
    function measure() {
      const found = targets.map((name) => document.querySelector<HTMLElement>(`[data-tour="${name}"]`));
      const target = found[0];
      if (target) {
        missing = 0;
        // La cible peut être hors du cadre : une bulle ancrée sur un élément
        // qu'on ne voit pas ne montre rien. UNE seule fois, à la découverte :
        // rejouer le défilement à chaque sondage empêcherait de bouger dans la
        // page pendant qu'on lit la bulle.
        //
        // On amène dans le cadre ce que l'étape veut RÉVÉLER en priorité : quand
        // elle en désigne un, sa cible est un panneau flottant (donc déjà
        // visible) et le passage révélé, lui, est dans la page — c'est celui-là
        // qui risque d'être sous la ligne de flottaison.
        //
        // Et SEULEMENT si la cible est entièrement hors du cadre. `nearest` sur
        // un élément plus haut que le cadre en aligne le haut, ce qui glissait
        // la page du lecteur sous sa barre d'outils : la découpe montait alors
        // jusqu'au bord supérieur de la fenêtre, barre comprise, au lieu de
        // s'arrêter au bord de la page. La vue est déjà cadrée par la visite
        // (cf. `pinPassage`) ; elle n'a pas à être corrigée ici.
        if (!scrolled) {
          scrolled = true;
          const scrollTo = found[1] ?? target;
          if (!intersectsViewport(scrollTo.getBoundingClientRect())) {
            scrollTo.scrollIntoView({ block: "nearest", inline: "nearest" });
          }
        }
        setRects(found.filter((el): el is HTMLElement => el !== null).map((el) => el.getBoundingClientRect()));
        return;
      }
      setRects([]);
      missing += 1;
      // Absente au bout de ~3 s : on PASSE à la suite plutôt que de rester
      // planté. Une ancre oubliée sur un écran doit coûter une bulle, jamais
      // la fin de la visite — c'est la seule panne qu'un parcours scripté
      // puisse rencontrer, et elle ne doit pas se voir.
      if (missing >= MISSING_LIMIT) next();
    }
    measure();
    // La cible bouge : défilement, redimensionnement, contenu qui se charge.
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    const timer = window.setInterval(measure, 500);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      window.clearInterval(timer);
    };
  }, [targets, next]);

  // Cible pas encore là : on n'affiche pas une bulle orpheline au milieu de
  // nulle part. Le sondage ci-dessus tranchera dans un sens ou dans l'autre.
  //
  // L'`AnimatePresence` reste monté et c'est son ENFANT qui est conditionnel :
  // un `return null` ici démontait le tout, et le voile de l'étape quittée
  // disparaissait d'un coup dès que la suivante changeait de route, avant même
  // que sa cible ait pu être cherchée.
  const rect = rects[0];
  const visible = rect !== undefined && rect.width > 0;

  const isLast = index === TOUR_STEPS.length - 1;
  // Un identifiant par étape. `mode="wait"` fait que deux voiles ne coexistent
  // jamais, mais un id partagé lierait le masque de l'un aux rectangles de
  // l'autre le jour où ils se recouvriraient — autant ne pas laisser le piège.
  const maskId = `tour-veil-${step.id}`;
  const side = step.side ?? "right";
  const anchor = visible ? anchorFor(rect, side) : null;

  return (
    <AnimatePresence mode="wait">
      {visible && anchor && (
        <motion.div
          key={step.id}
          className="pointer-events-none fixed inset-0 z-[120]"
          initial={reduce ? false : { opacity: 0 }}
          animate={{ opacity: 1, transition: { duration: ENTER_S, ease: EASE } }}
          exit={reduce ? undefined : { opacity: 0, transition: { duration: LEAVE_S, ease: EASE } }}
        >
          {/* Le voile et ses découpes. Le masque est en blanc (= opaque, on
              assombrit) percé de noir (= transparent, on laisse en clair). */}
          <svg aria-hidden className="absolute inset-0 size-full">
            <defs>
              <mask id={maskId}>
                <rect x="0" y="0" width="100%" height="100%" fill="white" />
                {rects.map((r, i) => (
                  <rect
                    key={i}
                    x={r.left - PADDING}
                    y={r.top - PADDING}
                    width={r.width + PADDING * 2}
                    height={r.height + PADDING * 2}
                    rx="6"
                    fill="black"
                    // Les propriétés géométriques SVG sont animables en CSS : la
                    // découpe glisse d'une étape à l'autre au lieu de sauter.
                    style={{ transition: "x 0.2s, y 0.2s, width 0.2s, height 0.2s" }}
                  />
                ))}
              </mask>
            </defs>
            <rect x="0" y="0" width="100%" height="100%" fill="rgba(0,0,0,0.55)" mask={`url(#${maskId})`} />
          </svg>

          <Popover open>
            <PopoverAnchor asChild>
              <span
                aria-hidden
                className="absolute"
                style={{ top: anchor.top, left: anchor.left, width: anchor.width, height: anchor.height }}
              />
            </PopoverAnchor>
            <PopoverContent
              side={side}
              align="start"
              sideOffset={16}
              collisionPadding={16}
              // Radix rendrait le focus au déclencheur en se fermant : ici il n'y
              // a pas de déclencheur, et voler le focus retirerait le curseur du
              // champ dans lequel quelqu'un était peut-être en train d'écrire.
              onOpenAutoFocus={(event) => event.preventDefault()}
              onCloseAutoFocus={(event) => event.preventDefault()}
              // Radix PORTE la bulle dans `body` : elle sort du conteneur de la
              // coach mark et ne profite pas de son `z-120`. Avec le `z-50` par
              // défaut du primitif, elle passait donc SOUS le voile — dont
              // l'ombre de 9999 px la repeignait à 55 % de noir, texte compris —
              // et sous les sas (`z-100`), qui la masquaient entièrement pendant
              // les étapes du lecteur. Elle doit être au-dessus des deux.
              //
              // Le cadre (fond, bordure, ombre, marge intérieure) n'est PAS ici :
              // il est porté par `BubbleBody`, qui est l'élément animé. Tant que
              // le primitif le peignait lui-même, la sortie n'effaçait que le
              // texte — le rectangle blanc, hors du fondu, restait plein jusqu'au
              // démontage et survivait au voile.
              className="pointer-events-auto z-[130] w-80 border-0 bg-transparent p-0 shadow-none"
            >
              <BubbleBody reduce={reduce}>
                <p className="m-0 text-[11px] font-bold tracking-wide text-muted-foreground uppercase">
                  {t(`tour.chapter.${step.chapter}`)} · {t("tour.step", { n: index + 1, total: TOUR_STEPS.length })}
                </p>
                <h3 className="mt-1.5 mb-0 font-serif text-h3 font-bold">{t(`tour.${step.id}.title`)}</h3>
                <p className="mt-2 mb-0 text-sm leading-relaxed text-text-soft">{t(`tour.${step.id}.body`)}</p>
                <div className="mt-4 flex items-center justify-between gap-3">
                  {/* La visite est interruptible à TOUT moment, et le bouton pour en
                      sortir est aussi visible que celui pour continuer. */}
                  <Button variant="ghost" size="sm" onClick={skip}>
                    {t("tour.skip")}
                  </Button>
                  <Button size="sm" onClick={next}>
                    {isLast ? t("tour.done") : t("tour.next")}
                  </Button>
                </div>
              </BubbleBody>
            </PopoverContent>
          </Popover>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/**
 * La bulle elle-même — cadre ET contenu — qui fond au même rythme que le voile.
 *
 * Radix PORTE la bulle dans `body` : elle n'est pas un descendant DOM du calque
 * animé, et l'opacité de celui-ci ne l'atteint pas. La bulle de l'étape quittée
 * restait donc pleine jusqu'à son démontage, pendant que celle de la suivante
 * s'affichait par-dessus. Le contexte de présence de Motion, lui, traverse le
 * portail : ce `motion.div` joue la même sortie que le voile, et
 * l'`AnimatePresence` attend les deux avant de passer à l'étape suivante.
 *
 * Pendant la sortie, la bulle ne prend plus les clics : un second « Suivant »
 * sur une bulle en train de s'effacer avancerait l'étape une fois de trop.
 */
function BubbleBody({ reduce, children }: { reduce: boolean | null; children: ReactNode }) {
  const present = useIsPresent();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0 }}
      animate={{ opacity: 1, transition: { duration: ENTER_S, ease: EASE } }}
      exit={reduce ? undefined : { opacity: 0, transition: { duration: LEAVE_S, ease: EASE } }}
      // Le cadre est ici, et non sur `PopoverContent`, pour que le fondu
      // l'emporte avec le texte (cf. le commentaire du primitif plus haut).
      className="rounded-md border bg-popover p-4 text-popover-foreground shadow-md"
      style={{ pointerEvents: present ? "auto" : "none" }}
    >
      {children}
    </motion.div>
  );
}
