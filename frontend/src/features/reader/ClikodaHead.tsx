// features/reader/ClikodaHead.tsx — La tête de Clikoda, le cachalot du logo.
//
// Les tracés sont ceux de `desktop/icons/source/clikoda-tete.svg` (viewBox
// 164 × 94, tête tournée vers la droite), séparés ici en corps, mâchoire et œil
// pour pouvoir animer l'œil seul. Trois usages :
//   * plein, œil en trou      — l'en-tête de la zone de discussion ;
//   * plein, œil peint `eye`  — la bulle fermée : l'œil cligne (`blink`) ;
//   * contour (`outline`)     — Clikoda réfléchit, la zone ouverte.
// `coda` ajoute les trois clics devant la mâchoire, émis l'un après l'autre :
// le coda, la « phrase » sonore d'un cachalot. Les animations vivent dans
// `theme/tokens.css` (classes `clikoda-*`), coupées sous `prefers-reduced-motion`.
import type { CSSProperties } from "react";

const BODY =
  "M2 22C26 8 68 2 120 2Q162 2 162 38L162 56C162 70 154 76 140 76L54 76C53.42 76 52.84 76.01 52.26 76.02" +
  "Q47.97 73.99 46.37 69.21Q45.98 68.02 45.19 67.63Q44.4 67.23 43.21 67.63Q40.84 68.42 41.63 70.79" +
  "Q42.7 74 44.89 76.42C28.58 77.95 14.15 83.54 4 92C14 70 14 44 2 22Z";
const JAW = "M54 83L134 83C141 83 141 90 134 90L68 92C58 92 52 89 54 83Z";
const EYE = { cx: 64, cy: 56, r: 5 };
const EYE_HOLE = "M69 56C69 53.24 66.76 51 64 51C61.24 51 59 53.24 59 56C59 58.76 61.24 61 64 61C66.76 61 69 58.76 69 56Z";
// Les clics : à hauteur de mâchoire, devant elle (le symbole du logo les pose là).
const CODA_X = [164, 192, 220];
const CODA_Y = 86;
const CODA_R = 11;
const WIDTH = 164;
const HEIGHT = 94;
const CODA_WIDTH = CODA_X[CODA_X.length - 1] + CODA_R + 2;

interface Props {
  /** Contour (trait de `currentColor`) qui se trace en apparaissant ; la mâchoire,
   *  trop fine pour un contour à ces tailles, reste pleine. */
  outline?: boolean;
  /** Couleur de l'œil peint ; absent, l'œil est un trou (le fond transparaît). */
  eye?: string;
  /** L'œil cligne de temps en temps (avec `eye` seulement). */
  blink?: boolean;
  /** Les trois clics du coda, devant la mâchoire. */
  coda?: boolean;
  /**
   * Les clics débordent de la boîte au lieu de l'élargir : la bulle garde la
   * tête à sa taille et laisse le signal sortir du disque.
   */
  codaOverflow?: boolean;
  className?: string;
  style?: CSSProperties;
}

export function ClikodaHead({ outline = false, eye, blink = false, coda = false, codaOverflow = false, className, style }: Props) {
  const width = coda && !codaOverflow ? CODA_WIDTH : WIDTH;
  return (
    <svg
      viewBox={`0 0 ${width} ${HEIGHT}`}
      overflow="visible"
      aria-hidden
      focusable="false"
      data-clikoda-head={outline ? "outline" : "fill"}
      className={className}
      style={style}
    >
      {outline ? (
        <>
          <path
            d={BODY}
            pathLength={100}
            className="clikoda-trace"
            fill="none"
            stroke="currentColor"
            strokeWidth={7}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          <path d={JAW} fill="currentColor" />
          <circle {...EYE} fill="currentColor" />
        </>
      ) : eye ? (
        <>
          <path d={BODY + JAW} fill="currentColor" />
          {/* Un demi-point de plus que le trou : sur la bulle, l'œil fait 3 px. */}
          <circle {...EYE} r={EYE.r + 0.5} fill={eye} className={blink ? "clikoda-blink" : undefined} />
        </>
      ) : (
        <path d={BODY + JAW + EYE_HOLE} fill="currentColor" fillRule="evenodd" />
      )}
      {coda && (
        <g className="clikoda-coda" fill="var(--accent)" data-clikoda-coda="">
          {CODA_X.map((cx) => (
            <circle key={cx} cx={cx} cy={CODA_Y} r={CODA_R} />
          ))}
        </g>
      )}
    </svg>
  );
}
