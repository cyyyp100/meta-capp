// features/library/folderTree.ts — Helpers purs sur l'arbre de dossiers.
//
// Aucun React ici : ces fonctions sont testables seules, et `isDescendant` est
// le garde-fou qui décide, PENDANT un survol de glisser-déposer, si le dépôt est
// légal. Le serveur revalide (400) — le client ne fait que l'ergonomie.
import type { FolderNode } from "../../api/types";

/** Le dossier sélectionné dans le rail. */
export type Selection =
  | { kind: "all" }
  | { kind: "recent" }
  | { kind: "unfiled" }
  | { kind: "folder"; id: number };

/** Un dossier aplati, avec sa profondeur — pour une liste indentée. */
export interface FlatFolder extends FolderNode {
  depth: number;
}

export function flattenFolders(tree: FolderNode[], depth = 0): FlatFolder[] {
  return tree.flatMap((node) => [
    { ...node, depth },
    ...flattenFolders(node.children, depth + 1),
  ]);
}

export function findFolder(tree: FolderNode[], id: number): FolderNode | null {
  for (const node of tree) {
    if (node.id === id) return node;
    const found = findFolder(node.children, id);
    if (found) return found;
  }
  return null;
}

/**
 * `candidateId` est-il `folderId` lui-même ou l'un de ses descendants ?
 *
 * Déplacer un dossier dans son propre sous-arbre le détacherait de la racine :
 * invisible dans le rail, donc irrattrapable à la souris.
 */
export function isDescendant(tree: FolderNode[], candidateId: number, folderId: number): boolean {
  if (candidateId === folderId) return true;
  const folder = findFolder(tree, folderId);
  if (!folder) return false;
  return flattenFolders(folder.children).some((child) => child.id === candidateId);
}

/** Les ids de tous les dossiers de l'arbre — pour purger un état de dépliage. */
export function allFolderIds(tree: FolderNode[]): number[] {
  return flattenFolders(tree).map((folder) => folder.id);
}

/** Chaîne des ancêtres de `id`, de la racine jusqu'à son parent direct. */
export function ancestorIds(tree: FolderNode[], id: number): number[] {
  const path: number[] = [];
  const walk = (nodes: FolderNode[], trail: number[]): boolean => {
    for (const node of nodes) {
      if (node.id === id) {
        path.push(...trail);
        return true;
      }
      if (walk(node.children, [...trail, node.id])) return true;
    }
    return false;
  };
  walk(tree, []);
  return path;
}
