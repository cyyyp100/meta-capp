# Meta-Capp — Guide du testeur (beta)

Merci de tester Meta-Capp ! Cette version est une **pré-release beta** : le binaire
n'est pas encore signé, ton OS va donc afficher un **avertissement de sécurité au
premier lancement** — c'est normal, la marche à suivre est ci-dessous.

> **Aucun compte requis** : tu télécharges, tu lances.

---

## 1. Télécharger

Va sur la page des Releases et prends, dans la version la plus récente (tout en
haut), le zip correspondant à ton système — il est dans la section **Assets** :

**https://github.com/cyyyp100/meta-capp/releases**

- macOS → `Meta-Capp-vX.Y.Z-macos.zip`
- Windows → `Meta-Capp-vX.Y.Z-windows.zip`

Aucun compte GitHub n'est nécessaire : le téléchargement est public.

---

## 2. Installer l'IA locale (Ollama) — **fortement recommandé**

Le cœur de Meta-Capp, c'est l'assistant **Gemma**. Il tourne **en local** via
[Ollama](https://ollama.com). Sans lui, l'app s'ouvre et affiche les PDF, mais
**l'assistant ne répond pas** (lecture / flashcards / stats fonctionnent quand même).

1. Installe **Ollama** : https://ollama.com
2. Télécharge le modèle (plusieurs Go, une seule fois) :
   ```bash
   ollama pull gemma4:e4b
   ```
3. Laisse Ollama tourner en fond pendant que tu utilises Meta-Capp.

---

## 3. Lancer — macOS

1. Dézippe le fichier → tu obtiens **`Meta-Capp.app`**. Glisse-le où tu veux
   (ex. dans **Applications**).
2. Comme l'app n'est pas encore signée, macOS la bloque (« *Meta-Capp est
   endommagé* » ou « *ne peut pas être ouvert, Apple ne peut pas le vérifier* »).
   **Débloque-la une fois** dans le Terminal :
   ```bash
   xattr -dr com.apple.quarantine /Applications/Meta-Capp.app
   ```
   *(adapte le chemin si tu l'as mis ailleurs)*
   Alternative sans Terminal : **Réglages Système → Confidentialité et sécurité**,
   descendre jusqu'au message sur Meta-Capp → **« Ouvrir quand même »**.
3. Double-clique **Meta-Capp.app**. ✅

---

## 4. Lancer — Windows

1. Dézippe le fichier → tu obtiens un **dossier `Meta-Capp\`** (pas un installeur).
   **Garde tout le dossier ensemble**, ne sors pas le `.exe` tout seul.
2. Ouvre le dossier et lance **`Meta-Capp.exe`**.
3. Windows SmartScreen affiche « *Windows a protégé votre PC* » :
   clique **« Informations complémentaires »** → **« Exécuter quand même »**. ✅

> Si l'antivirus met le `.exe` en quarantaine : c'est un faux positif classique
> pour un binaire non signé. Autorise-le, ou signale-le-moi.

---

## 5. Ce à quoi t'attendre

- Au **premier démarrage**, l'app peut mettre quelques secondes à ouvrir sa fenêtre
  (elle lance un petit serveur local en fond).
- **Tout reste sur ta machine** — rien n'est envoyé sur Internet (l'IA est locale).
- Importe un **PDF de cours** pour commencer : la lecture, les surlignages, les
  flashcards, les gauges et l'assistant Gemma s'activent à partir de là.

---

## 6. Faire un retour de bug

Ce qui m'aide le plus : **ce que tu faisais**, **ce qui s'est passé**, et le
**fichier de log** si l'app plante.

Le log se trouve ici :

| OS | Chemin |
|----|--------|
| macOS | `~/Library/Application Support/Meta-Capp/logs/nwol.log` |
| Windows | `%APPDATA%\Meta-Capp\logs\nwol.log` (colle ça dans la barre de l'Explorateur) |

Tes données (base, PDF importés) vivent dans le même dossier `Meta-Capp/` —
tu peux tout supprimer pour repartir de zéro.

---

## 7. Désinstaller

- **macOS** : mets `Meta-Capp.app` à la corbeille. Pour effacer aussi les données :
  supprime `~/Library/Application Support/Meta-Capp/`.
- **Windows** : supprime le dossier `Meta-Capp\` dézippé. Pour les données :
  supprime `%APPDATA%\Meta-Capp\`.

Merci pour ton aide ! 🙏
