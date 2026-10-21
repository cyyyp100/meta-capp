/**
 * La sélection native sur les calques de texte des pages PDF.
 *
 * Un calque n'est fait que de spans posés en absolu : entre deux lignes, dans
 * une marge, autour d'une figure, le pointeur ne survole aucun texte. Le
 * navigateur calcule alors la fin de la sélection à partir du calque lui-même,
 * et la place au début ou à la fin de la page : la sélection sautait d'un coup
 * sur tout le reste de la page, puis revenait au mot suivant.
 *
 * Le remède est celui de PDF.js : chaque calque porte, derrière ses spans, un
 * bloc qui le couvre entier et qu'on ne peut pas sélectionner (« fin de
 * contenu »). Pendant un glissé, on le déplace dans le DOM juste à côté de
 * l'extrémité de la sélection qui bouge : quand le pointeur passe dans un
 * vide, il survole ce bloc, et le navigateur ramène la sélection au point le
 * plus proche dans le DOM — là où elle était. Elle reste en place au lieu de
 * sauter. Le glissé fini, le bloc retourne à la fin du calque.
 *
 * Comme il couvre tout le calque, un appui dans un vide tombe sur lui. Il n'y
 * démarre rien (`onBlankMouseDown`) : WebKit y ancrait sinon une sélection à
 * la fin du calque, du mot visé jusqu'au bas de la page. Il faut partir d'un
 * mot, ou de sa zone de saisie (cf. `layoutTextLayer`).
 */

const END_ATTR = "data-textlayer-end";

/** Calque enregistré -> son bloc de fin de contenu. */
const layers = new Map<HTMLElement, HTMLElement>();
let detach: (() => void) | null = null;

/** Un appui dans le blanc : comme dans un document, il efface la sélection
 *  (et rend le focus à la page) sans en commencer une. */
function onBlankMouseDown(e: MouseEvent): void {
  if (e.button !== 0) return;
  e.preventDefault();
  document.getSelection()?.removeAllRanges();
  const active = document.activeElement;
  if (active instanceof HTMLElement && active !== document.body) active.blur();
}

/** Branche un calque (au montage) ; la fonction rendue le débranche. */
export function registerTextLayer(layer: HTMLElement): () => void {
  const end = document.createElement("div");
  end.setAttribute(END_ATTR, "");
  end.setAttribute("aria-hidden", "true");
  end.addEventListener("mousedown", onBlankMouseDown);
  layer.append(end);
  layers.set(layer, end);
  detach ??= listen();
  return () => {
    layers.delete(layer);
    end.remove();
    if (!layers.size && detach) {
      detach();
      detach = null;
    }
  };
}

/** Le glissé fini, chaque bloc retourne à la fin de son calque — sauf s'il y
 *  est déjà. `append` retire PUIS réinsère, même un dernier enfant : un appui
 *  dans le blanc tombe sur le bloc, et le nœud de l'appui sorti du DOM entre
 *  `pointerup` et `mouseup`, le navigateur n'émet pas de `click`. Le post-it,
 *  qui se pose au clic, ne se posait alors que sur un mot. */
function resetAll(): void {
  for (const [layer, end] of layers) {
    if (layer.lastChild !== end) layer.append(end);
  }
}

/** Le span du calque qui porte l'extrémité mobile de la sélection, ou null. */
function movingSpan(range: Range, atStart: boolean): HTMLElement | null {
  let node: Node | null = atStart ? range.startContainer : range.endContainer;
  if (node.nodeType === Node.TEXT_NODE) node = node.parentNode;
  if (!(node instanceof HTMLElement)) return null;
  const layer = node.parentElement;
  if (!layer || !layers.has(layer)) return null;
  // Fin de sélection au tout début d'un span : c'est le span d'avant qu'on vient
  // de finir. Le bloc se place après lui, pas après celui-ci.
  if (!atStart && range.endOffset === 0 && range.endContainer !== layer) {
    let prev = node.previousElementSibling;
    while (prev && !prev.textContent) prev = prev.previousElementSibling;
    if (prev instanceof HTMLElement) return prev;
  }
  return node;
}

function listen(): () => void {
  let pointerDown = false;
  let prevRange: Range | null = null;

  const onPointerDown = () => {
    pointerDown = true;
    prevRange = null;
  };
  const onRelease = () => {
    pointerDown = false;
    prevRange = null;
    resetAll();
  };
  const onSelectionChange = () => {
    // Seul le glissé de la souris a besoin du bloc : une sélection au clavier,
    // ou effacée par le lecteur, ne déplace rien.
    if (!pointerDown) return;
    const selection = document.getSelection();
    if (!selection || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    // L'extrémité qui bouge : le début si la fin n'a pas changé depuis le
    // dernier événement (on remonte), sinon la fin.
    const atStart =
      prevRange !== null &&
      (range.compareBoundaryPoints(Range.END_TO_END, prevRange) === 0 ||
        range.compareBoundaryPoints(Range.START_TO_END, prevRange) === 0);
    const span = movingSpan(range, atStart);
    const layer = span?.parentElement;
    const end = layer ? layers.get(layer) : undefined;
    // Déjà à sa place : ne rien toucher (une insertion déplace les repères de
    // la sélection posés sur le calque lui-même, et en relancerait une autre).
    if (span && layer && end && (atStart ? span.previousSibling : span.nextSibling) !== end) {
      layer.insertBefore(end, atStart ? span : span.nextSibling);
    }
    prevRange = range.cloneRange();
  };

  document.addEventListener("pointerdown", onPointerDown, true);
  document.addEventListener("pointerup", onRelease, true);
  document.addEventListener("pointercancel", onRelease, true);
  window.addEventListener("blur", onRelease);
  document.addEventListener("selectionchange", onSelectionChange);
  return () => {
    document.removeEventListener("pointerdown", onPointerDown, true);
    document.removeEventListener("pointerup", onRelease, true);
    document.removeEventListener("pointercancel", onRelease, true);
    window.removeEventListener("blur", onRelease);
    document.removeEventListener("selectionchange", onSelectionChange);
  };
}

/**
 * Les mots (`data-wi`) dont la sélection couvre au moins un caractère.
 *
 * `Selection.containsNode(span, true)` comptait aussi un span seulement
 * EFFLEURÉ — une sélection qui s'arrête au tout début d'un mot le prenait —, et
 * le surlignage enregistré débordait d'un mot sur ce que l'élève avait choisi.
 */
export function selectedWordIndices(range: Range, root: ParentNode): number[] {
  const out: number[] = [];
  const word = document.createRange();
  for (const span of root.querySelectorAll<HTMLElement>("[data-wi]")) {
    const text = span.firstChild;
    if (!text || !text.textContent) continue;
    word.selectNodeContents(text);
    // La sélection finit après le début du mot ET commence avant sa fin.
    if (
      range.compareBoundaryPoints(Range.START_TO_END, word) > 0 &&
      range.compareBoundaryPoints(Range.END_TO_START, word) < 0
    ) {
      out.push(Number(span.dataset.wi));
    }
  }
  return out;
}
