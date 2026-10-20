import { memo, useLayoutEffect, useMemo, useRef, type CSSProperties } from "react";

import type { PageWord } from "../../api/types";
import { fitScaleX, layoutTextLayer, measureText } from "./textLayer";
import { registerTextLayer } from "./textSelection";

/** Aucun passage caché : la même liste à chaque rendu (le calque est mémoïsé). */
const NOTHING_HIDDEN: number[][] = [];

/** Une longueur en points PDF, mise à l'échelle par la variable `--s` du calque. */
const pt = (value: number) => `calc(var(--s) * ${Math.round(value * 100) / 100}px)`;

// Recouvrement (points PDF) des sélections voisines : deux spans qui se
// touchent à une fraction de pixel laissaient, sous WebKit, un liseré clair
// entre deux mots ou deux lignes. Le calque est aplati avant d'être rendu
// translucide (theme/tokens.css) : le recouvrement ne se voit pas, le liseré
// disparaît. Il est trop fin pour déplacer un clic d'un mot à l'autre.
const SEAM_PT = 0.3;

/**
 * Calque de texte transparent posé sur l'image d'une page : c'est lui qui rend
 * le PDF sélectionnable et copiable, et qui porte les `data-wi` d'où le lecteur
 * tire les rects d'un surlignage.
 *
 * Mots, espaces et sauts de ligne viennent de `layoutTextLayer`, dans l'ordre
 * de lecture. Chaque span est comprimé horizontalement pour couvrir exactement
 * sa boîte (`fitScaleX`) : la largeur naturelle d'un mot dans la police du
 * navigateur n'a aucune raison de coïncider avec celle du PDF, et la sélection
 * dériverait le long de la ligne. Sa hauteur de ligne couvre la bande du texte
 * ET sa zone de saisie : la sélection se dessine en blocs continus, d'une
 * ligne à l'autre, et on l'attrape sans viser au pixel près.
 *
 * Positions et tailles sont écrites en points, multipliés par `--s` : changer
 * de zoom ne touche qu'une variable, pas les quelque mille spans d'une page.
 * Les styles communs (absolu, transparent, `::selection`, fin de contenu)
 * vivent dans theme/tokens.css (`[data-textlayer]`).
 */
export const PageTextLayer = memo(function PageTextLayer({
  words,
  scale,
  hidden = NOTHING_HIDDEN,
}: {
  words: PageWord[];
  scale: number;
  /** Boîtes (points PDF) dont les mots sont retirés du calque : le cache d'un rappel libre. */
  hidden?: number[][];
}) {
  const layerRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => (layerRef.current ? registerTextLayer(layerRef.current) : undefined), []);

  // Le facteur de compression ne dépend pas du zoom (rapport de deux largeurs) :
  // on ne mesure qu'à l'arrivée des mots, pas à chaque changement d'échelle.
  // Les éléments eux-mêmes sont mémoïsés : un nouveau zoom ne les recrée pas.
  const spans = useMemo(
    () =>
      layoutTextLayer(words, hidden).map((item, i) => {
        if (item.kind === "break") return <br key={`b${i}`} />;
        if (item.kind === "space") {
          const scaleX = fitScaleX(" ", item.height, Math.max(item.width, 0) + 2 * SEAM_PT, measureText);
          return (
            <span
              key={`s${i}`}
              style={{
                left: pt(item.left - SEAM_PT),
                top: pt(item.top - item.padTop - SEAM_PT),
                fontSize: pt(item.height),
                lineHeight: pt(item.height + item.padTop + item.padBottom + 2 * SEAM_PT),
                transform: `scaleX(${scaleX})`,
              }}
            >
              {" "}
            </span>
          );
        }
        if (item.rotated) {
          // Mot pivoté : l'em se lit sur la largeur de la boîte, le texte court
          // sur sa hauteur. La rotation part du coin BAS-gauche de la boîte, le
          // texte remonte donc dans la colonne.
          const scaleX = fitScaleX(item.text, item.width, item.height, measureText);
          return (
            <span
              key={`w${item.wi}`}
              data-wi={item.wi}
              style={{
                left: pt(item.left),
                top: pt(item.top + item.height),
                fontSize: pt(item.width),
                lineHeight: 1,
                transform: `rotate(-90deg) scaleX(${scaleX})`,
              }}
            >
              {item.text}
            </span>
          );
        }
        const scaleX = fitScaleX(item.text, item.height, item.width, measureText);
        // La compression s'applique aussi aux marges : on les écrit d'avance
        // divisées par elle, pour qu'elles fassent leur taille une fois comprimées.
        const style: CSSProperties = {
          left: pt(item.left - item.padLeft),
          top: pt(item.top - item.padTop - SEAM_PT),
          fontSize: pt(item.height),
          lineHeight: pt(item.height + item.padTop + item.padBottom + 2 * SEAM_PT),
          transform: `scaleX(${scaleX})`,
        };
        if (item.padLeft) style.paddingLeft = pt(item.padLeft / scaleX);
        if (item.padRight) style.paddingRight = pt(item.padRight / scaleX);
        return (
          <span key={`w${item.wi}`} data-wi={item.wi} style={style}>
            {item.text}
          </span>
        );
      }),
    [words, hidden],
  );

  return (
    <div ref={layerRef} data-textlayer style={{ "--s": scale } as CSSProperties}>
      {spans}
    </div>
  );
});
