import {
  forwardRef,
  useLayoutEffect,
  useRef,
  type CSSProperties,
  type KeyboardEvent,
  type TextareaHTMLAttributes,
} from "react";

type Props = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "onSubmit" | "rows"> & {
  value: string;
  /**
   * Appelé quand l'utilisateur valide avec Entrée (sans Maj). Si fourni, Entrée
   * valide et Maj+Entrée insère un saut de ligne. Sans cette prop, Entrée se
   * comporte normalement (saut de ligne).
   */
  onSubmit?: () => void;
  /** Hauteur (px) à laquelle le champ cesse de grandir et devient scrollable. */
  maxHeight?: number;
};

/**
 * Zone de saisie qui s'allonge avec son contenu : chaque nouvelle ligne agrandit
 * la zone — vers le haut quand le champ est ancré en bas de son conteneur —
 * jusqu'à `maxHeight`, au-delà duquel on peut scroller pour remonter au début du
 * texte. Tout ce que tape l'utilisateur reste visible sous ce seuil.
 */
export const AutoGrowTextarea = forwardRef<HTMLTextAreaElement, Props>(function AutoGrowTextarea(
  { value, onSubmit, maxHeight = 168, onKeyDown, style, ...rest },
  ref,
) {
  const innerRef = useRef<HTMLTextAreaElement | null>(null);

  function setRefs(el: HTMLTextAreaElement | null) {
    innerRef.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) ref.current = el;
  }

  // Recalcule la hauteur à chaque changement de contenu : on remet à zéro pour
  // mesurer le contenu réel, puis on borne par maxHeight (au-delà → scroll).
  useLayoutEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    el.style.height = "auto";
    // box-sizing: border-box → scrollHeight ignore les bordures, on les rajoute
    // pour ne pas rogner la dernière ligne.
    const borderY = el.offsetHeight - el.clientHeight;
    const content = el.scrollHeight + borderY;
    el.style.height = `${Math.min(content, maxHeight)}px`;
    el.style.overflowY = content > maxHeight ? "auto" : "hidden";
  }, [value, maxHeight]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    onKeyDown?.(e);
    if (e.defaultPrevented) return;
    // Entrée valide ; Maj+Entrée saute une ligne. On ignore la saisie IME en cours.
    if (onSubmit && e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      onSubmit();
    }
  }

  return (
    <textarea
      ref={setRefs}
      value={value}
      rows={1}
      onKeyDown={handleKeyDown}
      style={{ ...baseStyle, ...style }}
      {...rest}
    />
  );
});

const baseStyle: CSSProperties = {
  resize: "none",
  overflowY: "hidden",
  font: "inherit",
  lineHeight: 1.4,
  display: "block",
};
