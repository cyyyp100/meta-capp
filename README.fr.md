<div align="center">

# Meta-Capp

### Le compagnon d'apprentissage cognitif, nativement IA, pour les PDF éducatifs

[English](README.md) · **Français**

**Votre PDF, exactement tel que son auteur l'a conçu, avec à côté un compagnon de lecture IA bien vivant : il observe comment vous apprenez, répond dans le contexte, et ne prend la parole que lorsque cela aide vraiment.**

[![Licence : MIT](https://img.shields.io/badge/License-MIT-000000.svg?style=flat-square)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/cyyyp100/meta-capp/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/cyyyp100/meta-capp/actions/workflows/ci.yml)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/Ollama-local%20LLM-000000?style=flat-square&logo=ollama&logoColor=white)](https://ollama.com)
[![100 % hors ligne](https://img.shields.io/badge/100%25-offline-2ea44f?style=flat-square)](#pourquoi-une-ia-locale)
[![PRs bienvenues](https://img.shields.io/badge/PRs-welcome-blueviolet?style=flat-square)](CONTRIBUTING.md)

[**Pourquoi**](#lidée-centrale) · [**Fonctionnalités**](#fonctionnalités-principales) · [**Installation**](#installation) · [**Architecture**](#stack-technique) · [**Éditions**](#éditions--local-vs-pro) · [**Contribuer**](CONTRIBUTING.md)

</div>

---

<div align="center">

|  |  |  |
|:--:|:--:|:--:|
| **📄 Aucune reconstruction** | **🧠 Moteur cognitif silencieux** | **🔒 Rien ne quitte votre machine** |
| Le PDF est affiché tel quel, fidèle à l'original, en défilement libre. Ni découpage, ni remise en page, ni verrou. | Six jauges cachées, des questions adaptatives, des flashcards et une mémoire de session tournent derrière la page. | Inférence locale avec Ollama. Ni compte, ni télémétrie, ni cloud, ni abonnement. |

</div>

---

## L'idée centrale

Les grands modèles de langage ont rendu l'accès à l'information presque sans effort.

**Mais un accès sans effort n'est pas un apprentissage.**

Les outils d'IA actuels encouragent souvent :

- la consommation passive,
- les réponses instantanées,
- la dépendance intellectuelle,
- une compréhension superficielle,
- et l'illusion de compétence.

Meta-Capp est né de la philosophie inverse.

Au lieu de remplacer l'effort, il utilise l'IA pour **structurer l'effort intelligemment**.

Au lieu d'optimiser pour des « réponses rapides », il optimise pour :

- la compréhension,
- la réflexion,
- la mémorisation,
- la curiosité,
- et la conscience métacognitive.

Le but n'est pas de rendre l'apprenant passif.

**Le but est de l'aider à se construire un esprit plus solide.**

---

## Ce qu'est Meta-Capp

Meta-Capp n'essaie **pas** de reproduire ni de reconstruire le PDF. Le document s'affiche exactement tel que son auteur l'a conçu : pages entières, défilement libre, aucun verrou, aucune barrière.

Ce qui change, c'est tout ce qu'il y a *autour* du document :

<table>
<tr>
<td width="50%" valign="top">

### 📖 Un lecteur en défilement libre

Le PDF entier, rendu progressivement page par page, en pleine fidélité. Vous lisez à votre rythme.

</td>
<td width="50%" valign="top">

### 👁️ Un assistant incarné : Clikoda

Une petite bulle animée flotte au-dessus du PDF. Elle a des yeux. Elle lit quand vous lisez, réfléchit quand vous posez une question, s'endort quand le modèle local est hors ligne. Cliquez dessus, demandez ce que vous voulez : la réponse s'appuie sur la page visible au moment précis où vous appuyez sur *Envoyer*, même si vous faites défiler pendant qu'elle réfléchit.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🧩 Un moteur pédagogique silencieux

En coulisse, tout le système métacognitif continue de tourner : sessions, jauges cognitives, questions adaptatives, réponses évaluées, flashcards automatiques, réflexion de fin de session. Les jauges ne s'affichent plus pendant la lecture : elles sont calculées, enregistrées et transmises à l'IA au lieu de vous être mises sous le nez.

</td>
<td width="50%" valign="top">

### ✋ Des interventions autonomes

L'assistant remarque quand vous vous attardez sur une page, y revenez sans cesse, posez plusieurs fois la même question sur un passage, ou butez sur un mur de mathématiques. Il *décide* alors, grâce au LLM, s'il propose de l'aide, pose une question pédagogique, suggère une pause ou propose de reformuler la page. Des délais de repos l'empêchent d'être bavard. Le mode *discret* le fait taire complètement ; le mode *coach* le rend plus entreprenant.

</td>
</tr>
</table>

---

## Pourquoi ce projet existe

> **Les PDF éducatifs sont des interfaces cognitivement mortes.**

- Les lecteurs classiques affichent des pages.
- Les chatbots classiques répondent aux questions sans contexte.
- Les chaînes RAG classiques découpent le texte et perdent le document.

Aucun ne comprend l'apprenant.

Apprendre est un processus cognitif actif qui mobilise l'attention, la mémoire, l'incertitude, la réflexion, la confusion, la reconstruction et l'effort.

Meta-Capp a été conçu pour rétablir ces mécanismes à l'ère de l'IA, **sans s'interposer entre le lecteur et le document.**

---

## Une autre philosophie de l'IA

La plupart des systèmes éducatifs à base d'IA cherchent à supprimer la friction.

Meta-Capp introduit une **friction productive**, mais jamais imposée.

Les premiers prototypes bloquaient le passage à la page suivante derrière des questions. Cette version fait confiance au lecteur : le défilement est libre, et le système gagne l'attention au lieu de l'exiger. L'assistant :

- répond d'abord à partir de la page visible, ensuite à partir de ses connaissances générales,
- pose de vraies questions pédagogiques dont les réponses sont évaluées,
- transforme les bons échanges en flashcards,
- met à jour un profil cognitif à partir de tout ce que vous faites,
- et termine chaque session par une réflexion métacognitive.

> L'IA ne sert pas à remplacer la pensée.
> **L'IA sert à mieux penser.**

---

## Pourquoi une IA locale

Meta-Capp tourne entièrement en local, avec **Gemma 4 via [Ollama](https://ollama.com)**.

| ❌ Pas d'abonnement | ❌ Pas de dépendance au cloud | ❌ Pas de surveillance éducative | ❌ Pas de collecte de données |
|---|---|---|---|

Les données d'apprentissage restent sur la machine de l'apprenant : erreurs, doutes, faiblesses, confusions, curiosité, réflexions. **Elles ne doivent pas devenir des produits du cloud.**

Si Ollama est hors ligne, rien ne casse : le lecteur reste entièrement utilisable et l'assistant s'endort, visiblement.

### L'éducation pour tous, partout

L'accès à l'éducation ne devrait dépendre ni d'une connexion fibre, ni d'un forfait de données, ni d'un abonnement cloud. Installer Meta-Capp demande un seul téléchargement, que l'on peut copier d'une machine à l'autre ; ensuite, il n'a **plus besoin d'aucune connexion** : dans un village isolé, sur un bateau, dans une région où le réseau va et vient, dans une salle de classe sans Wi-Fi.

Et là où les professeurs manquent, un compagnon patient, qui explique la page, pose des questions en retour et transforme ce que vous avez appris en flashcards, peut vraiment changer les choses. Non pas pour remplacer les professeurs, mais pour accompagner les apprenants qui n'en ont pas sous la main.

Ce qu'apporte une IA qui tourne en local :

- **Aucune connexion nécessaire** : pas de panne de service, pas de limite de requêtes, pas d'aller-retour réseau ; l'app fonctionne dans un avion comme à la maison.
- **Gratuite à l'usage** : aucun coût par question, aucun abonnement, aucun quota.
- **Confidentielle par construction** : rien n'est envoyé, donc rien ne peut fuiter, être revendu ou servir à entraîner un modèle. Aucun tiers ne traite les données de l'apprenant.
- **Tourne sur du matériel modeste** : d'un portable de 4 Go (petit modèle, mode économe) à une station de travail, avec ou sans GPU.
- **Aucune dépendance à un fournisseur** : modèles à poids ouverts et code open source ; l'app continue de fonctionner quoi qu'un fournisseur décide de ses prix, de ses conditions ou de son service.
- **Vérifiable** : tout ce que fait l'assistant est dans ce dépôt, et tout ce qu'il enregistre tient dans un seul fichier SQLite que l'apprenant peut exporter ou effacer.

### Conçu en tenant compte de l'AI Act européen

Meta-Capp est conçu en cohérence avec le règlement européen sur l'IA (AI Act, règlement (UE) 2024/1689) :

- **Transparence** : Clikoda se présente comme une IA, et l'app précise qu'elle peut se tromper. Personne n'est amené à croire qu'il parle à un humain.
- **Ni reconnaissance des émotions, ni biométrie** : les jauges sont déduites du comportement de lecture (temps passé sur une page, questions, réponses). Ni caméra, ni micro, ni donnée biométrique.
- **L'apprenant garde la main** : aucune note, aucune décision d'admission ou d'orientation. Chaque intervention peut être ignorée, le mode *discret* fait taire Clikoda complètement, et une pause fige tout.
- **Ouvert et local** : code source sous licence MIT, modèles locaux, données qui ne quittent jamais la machine.

Ce paragraphe décrit la conception du logiciel ; ce n'est pas une certification juridique.

---

## Fonctionnalités principales

| Fonctionnalité | Description |
|---|---|
| **Lecteur PDF en défilement libre** | Document complet, rendu progressif des pages en haute résolution, aucun verrou de progression |
| **Bulle d'assistant incarnée** | Personnage animé en Canvas, déplaçable, avec des états repos / lecture / réflexion / réponse / intervention / sommeil |
| **Contexte capturé à l'envoi** | Chaque question reçoit une réponse fondée sur un instantané de la page visible au moment précis où vous appuyez sur Envoyer |
| **Interventions autonomes** | Propositions d'aide, questions, suggestions de pause, reformulations de page, décidées par le LLM, avec des délais de repos globaux et par page |
| **Modes de l'assistant** | *discret* (ne parle jamais en premier), *normal*, *coach* (intervient davantage), mémorisés par utilisateur |
| **Questionnement adaptatif** | Chaîne complète question → réponse → évaluation → retour → flashcard, sans jamais bloquer la lecture |
| **Jauges cognitives cachées** | Attention, compréhension, curiosité, mémorisation, créativité, métacognition : calculées et enregistrées, jamais insistantes |
| **Mémoire de session** | Pages vues, temps passé, retours en arrière, questions par page, difficultés détectées |
| **Flashcards manuelles** | Un clic transforme une réponse utile de l'assistant en flashcard |
| **Synthèse de session enrichie** | La synthèse de fin de session cite les pages sur lesquelles vous avez demandé le plus d'aide |
| **Repérage des chapitres** | Index des chapitres calculé (table des matières ou taille des polices), transmis à l'IA et à la barre de navigation |
| **Lecture de code source** | Importez un fichier source : il est paginé en blocs de code lisibles, avec le même compagnon par-dessus |
| **Bilingue (FR / EN)** | L'interface *et* la langue des prompts du LLM changent ensemble, et le choix est conservé d'un lancement à l'autre |
| **IA entièrement locale** | Gemma 4 via Ollama, fonctionnement dégradé en douceur hors ligne |

---

## Le déroulé d'une lecture

```
  Import  →  Sas  →  Révision éclair  →  Lecture libre  →  Défi  →  Synthèse
```

1. **Importez un PDF.** Pas de choix de chapitre : la session, c'est le document entier.
2. **Sas de concentration.** Un rituel de ralentissement de 30 secondes, avec une accroche de curiosité générée par l'IA.
3. **Révision éclair.** Jusqu'à 5 flashcards dues sur ce document.
4. **Lisez librement.** Le PDF entier, en défilement, avec Clikoda qui flotte au-dessus.
5. **Demandez ce que vous voulez.** Cliquez sur la bulle, tapez, appuyez sur Entrée. La réponse cite la page sur laquelle vous étiez au moment de la question.
6. **Relevez des défis.** Parfois, c'est Clikoda qui *vous* pose une question. Répondez-y (la réponse est évaluée, nourrit votre profil et peut devenir une flashcard), ou fermez-la.
7. **Terminez la session.** Synthèse, questions métacognitives, mise à jour du profil.

---

## Le rôle de Gemma 4

<table>
<tr><td width="50%" valign="top">

**Réponses en contexte**
Répond aux questions à partir d'un `PageContextSnapshot` : texte de la page, image allégée de la page, chapitre estimé, jauges en cours et échanges récents.

</td><td width="50%" valign="top">

**Décisions d'intervention**
Reçoit les signaux observés (temps passé, retours en arrière, attention faible, densité mathématique, questions répétées) et renvoie une décision structurée :
`{should_intervene, kind, message, question}`.

</td></tr>
<tr><td width="50%" valign="top">

**Génération pédagogique**
Questions adaptatives, évaluation des réponses avec signaux métacognitifs, reformulations, flashcards, accroches de curiosité.

</td><td width="50%" valign="top">

**Analyse métacognitive**
Synthèses de fin de session, questions de réflexion et mises à jour du profil.

</td></tr>
</table>

---

## Le profil cognitif

Six jauges évoluent pendant chaque session et se consolident en un profil à long terme : **compréhension du contexte, créativité, mémorisation, curiosité, attention, métacognition**, plus un niveau par matière, détecté à partir de vos documents.

Pendant la lecture, elles sont invisibles. Elles pilotent pourtant tout : la difficulté des questions, les seuils d'intervention, les synthèses de session et le ton de l'assistant.

---

## Installation

Meta-Capp tourne sur **macOS, Windows et Linux**, avec ou sans GPU.

### Configuration requise

| | L'app seule | Avec Clikoda (l'assistant) |
|---|---|---|
| **Système** | macOS (Apple Silicon ou Intel), Windows 10/11 x64, Linux x86_64 (glibc 2.35+) | idem |
| **Mémoire vive** | toute machine récente | **12 Go ou plus** pour le modèle standard ; 8 Go font tourner le modèle léger, 4 Go le plus petit, en mode économe (voir plus bas) |
| **Disque** | ~400 Mo | **+1,4 à 20 Go** selon le modèle, plus 0,6 Go pour `embeddinggemma`, facultatif |
| **GPU** | aucun | facultatif : Apple Silicon (Metal), NVIDIA (CUDA), certains AMD (ROCm) ; le CPU seul fonctionne, lentement |

Clikoda est facultatif : sans [Ollama](https://ollama.com), le lecteur, les flashcards et
les statistiques fonctionnent toujours, et l'assistant s'endort, visiblement.

**Les machines lentes sont prises en charge, pas seulement tolérées.** Les budgets de temps
de génération sont calculés à partir de la vitesse *mesurée* de Clikoda sur votre machine
(un court appel de calibrage au démarrage, puis à chaque réponse) : un portable sans GPU
obtient des réponses lentes plutôt que des expirations. En dessous de ~2 tokens/s (8 fois
plus lent que la machine Apple Silicon de référence), les budgets cessent de s'allonger
et les longues réponses abandonnent plutôt que de laisser l'écran en attente indéfiniment
(jusqu'à ~0,9 token/s en mode économe, jamais plus d'un quart d'heure par réponse). Si le
modèle ne tient pas en mémoire, le lecteur le dit clairement.

**Le mode économe** (Réglages ▸ Clikoda) est ce qui rend un portable de 4 Go utilisable :
un seul contexte pour toutes les demandes afin que le modèle ne soit jamais rechargé,
des prompts compacts qui y tiennent, aucun travail en arrière-plan (fiches des documents,
épisodes de langue), aucune aide spontanée, recherche lexicale uniquement, modèle
déchargé après cinq minutes d'inactivité ; et le lecteur annonce l'attente (« réponse
dans N min au plus ») avec un bouton **Annuler**. « Automatique » l'active avec le plus
petit modèle ou en dessous de 8 Go de mémoire vive ; vous pouvez le forcer dans un sens
comme dans l'autre.

### Versions prêtes à l'emploi

Chaque [release](https://github.com/cyyyp100/meta-capp/releases/latest) fournit une
archive par plateforme, avec un `SHA256SUMS.txt` :

| Plateforme | Archive | Remarques |
|---|---|---|
| Mac Apple Silicon | `macos-arm64.zip` | déplacez `Meta-Capp.app` dans Applications, puis ouvrez-la |
| Mac Intel | `macos-x86_64.zip` | compilée sur le dernier runner Intel de GitHub, disponible jusqu'en août 2027 |
| Windows 10/11 x64 | `windows.zip` | gardez le dossier décompressé entier ; utilise WebView2 (intégré à Windows 11 et à Windows 10 à jour) |
| Linux x86_64 | `linux-x86_64.tar.gz` | lancez `./Meta-Capp/Meta-Capp` depuis un terminal et laissez-le ouvert ; l'app s'ouvre dans votre navigateur |

**Premier lancement d'une version pas encore signée** (les bêtas peuvent ne pas l'être) :

- **macOS** : le premier double-clic est refusé. Ouvrez *Réglages Système ▸ Confidentialité
  et sécurité*, descendez jusqu'au message concernant Meta-Capp et cliquez sur
  **Ouvrir quand même** (une seule fois). Si macOS dit plutôt que l'app *est endommagée*,
  le téléchargement a perdu sa signature en route :
  `xattr -dr com.apple.quarantine /Applications/Meta-Capp.app` la rétablit.
- **Windows** : SmartScreen affiche *Windows a protégé votre ordinateur* :
  **Informations complémentaires ▸ Exécuter quand même**.

Les versions signées et notarisées s'ouvrent comme n'importe quelle application. Dans tous
les cas, vérifiez l'archive avec `SHA256SUMS.txt` (`shasum -a 256 <fichier>` /
`certutil -hashfile <fichier> SHA256`).

### Télécharger un modèle

Clikoda tourne sur la famille **gemma4**, plus un petit modèle pour les machines de 4 Go,
et le choix du modèle est un réglage, pas un nom écrit en dur.
« Automatique » (par défaut) choisit le modèle le plus performant que vous avez installé,
que la mémoire de votre machine peut réellement charger **et qui y reste fluide** : un
modèle dont la vitesse d'écriture, mesurée au démarrage, tombe sous 15 tokens/s est mis de
côté au profit du suivant (pendant 14 jours, sur cette machine ; toute mesure ultérieure
au-dessus du seuil le rétablit). **Réglages ▸ Clikoda** indique ce qui a été choisi et
pourquoi (y compris quel modèle a été écarté, et à quelle vitesse), ainsi que la commande
`ollama pull` pour tout ce qui vous manque. Un choix explicite est toujours respecté. La
table se trouve dans `nwol/config/settings.py:LLM_MODELS`.

| modèle | téléchargement | mémoire vive | pour |
|---|---|---|---|
| `qwen3:1.7b` | 1,4 Go | 4 Go | un portable de 4 Go : plus lent, plus d'erreurs, texte seul (sans image de la page), mode économe activé |
| `gemma4:e2b` | 7,2 Go | 8 Go | une machine légère |
| `gemma4:e4b` | 9,6 Go | 12 Go | le choix standard |
| `gemma4:12b` | 8,0 Go | 12 Go | de meilleures réponses, beaucoup plus lent (~12 tokens/s contre ~30 pour e4b sur un Apple M4 de 16 Go) |
| `gemma4:26b` / `gemma4:31b` | 18–20 Go | 32 Go | une station de travail |

```bash
ollama pull gemma4:e4b       # ou e2b sur une machine plus légère, qwen3:1.7b sur une machine de 4 Go
ollama pull embeddinggemma   # facultatif (~600 Mo) : recherche par le sens dans le document que vous lisez
```

> Sans `embeddinggemma`, la recherche de Clikoda dans le document en cours reste lexicale (BM25).

### Depuis les sources

Nécessite **Python 3.11** et **Node 20+** (pour compiler l'interface web).

```bash
git clone https://github.com/cyyyp100/meta-capp.git
cd meta-capp

python -m venv .venv
source .venv/bin/activate     # Windows : .venv\Scripts\activate

pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### Lancement

```bash
python main.py                       # fenêtre native (compile l'interface si besoin)
python main.py chemin/vers/document.pdf  # importe et ouvre directement un document
python main.py --browser             # ouvre dans le navigateur par défaut au lieu d'une fenêtre
python main.py --debug               # journalisation DEBUG
```

**Pas de fenêtre native ? L'app s'ouvre dans votre navigateur.** La fenêtre a besoin d'un
moteur web natif : WebKit (macOS), WebView2 (Windows), GTK ou Qt (Linux). Quand aucun
n'est utilisable, ou avec `--browser`, Meta-Capp sert la même app, derrière les mêmes
protections, dans votre navigateur par défaut. Pour quitter, choisissez **Quitter Meta-Capp**
dans le menu du profil, ou fermez simplement l'onglet : l'app s'arrête d'elle-même trois
minutes après la fermeture du dernier onglet. Importer un document envoie alors une copie
dans le dossier de données, supprimée avec le document. Relancer l'app pendant qu'elle
tourne la rouvre.

<details>
<summary><b>Linux : obtenir une fenêtre native</b></summary>

Choisissez **une seule** option, dans l'environnement Python de Meta-Capp.

**GTK** (GNOME, Xfce…) demande d'abord des bibliothèques système :

```bash
# Debian / Ubuntu
sudo apt install libgirepository1.0-dev libcairo2-dev pkg-config python3-dev gir1.2-webkit2-4.1
# Fedora
sudo dnf install gobject-introspection-devel cairo-gobject-devel pkgconf python3-devel webkit2gtk4.1
# Arch
sudo pacman -S gobject-introspection cairo pkgconf webkit2gtk-4.1

pip install "pywebview[gtk]"
```

**Qt** (KDE) s'installe avec pip seul (~200 Mo) :

```bash
pip install "pywebview[qt]"
sudo apt install libxcb-cursor0   # Debian/Ubuntu, si Qt ne peut pas charger le plugin « xcb »
```

Les noms de paquets varient selon les distributions : la référence est le
[guide d'installation de pywebview](https://pywebview.flowrl.com/guide/installation.html).
Si la fenêtre ne peut toujours pas s'ouvrir, Meta-Capp se replie sur le navigateur et
journalise pourquoi (`Fenêtre native indisponible : …`).

</details>

<details>
<summary><b>Dépannage</b></summary>

- **Clikoda reste endormi** : Ollama ne tourne pas, ou aucun modèle n'est installé.
  **Réglages ▸ Clikoda** indique lequel des deux, nomme le modèle qu'il utiliserait et
  donne la commande `ollama pull` à copier.
- **Clikoda est très lent** : `ollama ps` montre où tourne le modèle (`PROCESSOR` : GPU,
  CPU ou partagé). Sur CPU, c'est normal : le lecteur annonce l'attente et propose
  **Annuler**, et le journal affiche la vitesse mesurée au démarrage (`Débit de Clikoda
  sur cette machine`). Un modèle plus léger, le mode économe et la fermeture des
  applications gourmandes en mémoire aident.
- **« Clikoda ne tient pas dans la mémoire de cet ordinateur »** : le message indique ce
  dont le modèle a besoin ; libérez de la mémoire vive ou choisissez un modèle plus léger
  dans Réglages ▸ Clikoda (`qwen3:1.7b` tourne dès 4 Go). Le reste de l'app continue de
  fonctionner.
- **« Le port 8756 est occupé… »** : un autre programme, ou une instance qui ne peut pas
  être rouverte (une version plus ancienne), occupe le port : fermez-le ou redémarrez.
- **Derrière un proxy** (réseau d'école ou d'entreprise) : rien à configurer, Meta-Capp
  ne fait jamais passer son trafic local (l'app, Ollama) par le proxy du système.
- **Journaux** : Réglages ▸ Aide ▸ *Signaler un problème* les exporte ; ils se trouvent
  dans `logs/`, dans le dossier de données (voir [Vos données](#vos-données)).

</details>

Pour itérer, le backend et le frontend peuvent tourner séparément :

```bash
cd nwol && python -m server.main     # FastAPI sur 127.0.0.1:8756
cd frontend && npm run dev           # Vite sur :5173, relaie /api
```

<details>
<summary><b>Empaqueter un binaire de bureau</b></summary>

```bash
pip install -r requirements-build.txt            # PyInstaller en version figée
cd frontend && npm run build && cd ..            # compiler l'interface d'abord
pyinstaller desktop/metacapp.spec --noconfirm    # résultat dans dist_app/
```

PyInstaller compile pour l'architecture de la machine sur laquelle il tourne : le workflow
de release compile sur des runners Apple Silicon, macOS Intel, Windows et Ubuntu 22.04,
et teste chaque binaire au démarrage. Sur macOS, `./scripts/build_app.sh` fait les deux
étapes, teste le binaire figé et l'installe (`--desktop` le place sur le Bureau,
`--no-install` se contente de compiler).

</details>

---

## Stack technique

| Couche | Technologie | Rôle |
|---|---|---|
| Rendu PDF | **pypdfium2** (PDFium) | Rendu des pages, texte des pages, détection des chapitres |
| Intelligence sémantique | **Gemma 4 via Ollama** | Réponses en contexte, interventions, raisonnement pédagogique |
| Moteur cognitif | **Système métacognitif maison** | Jauges, profil, réflexion, mémoire de session |
| Interface | **FastAPI + React (Vite) dans pywebview** | Lecteur, assistant flottant, statistiques, flashcards, langues |
| Persistance | **SQLite** | Documents, sessions, questions, réponses, jauges, flashcards, préférences |

**Organisation du code** : la logique métier, indépendante de l'interface, vit dans `nwol/services/` ; l'app FastAPI et ses routeurs dans `nwol/server/` ; le lecteur est un flux WebSocket ; la coque de bureau est `desktop/pywebview_main.py`. Les conventions qui maintiennent cette organisation sont documentées dans [CONTRIBUTING.md](CONTRIBUTING.md).

```
meta-capp/
├── main.py               # point d'entrée : lance l'app de bureau
├── desktop/              # coque native (pywebview) + spec PyInstaller
├── frontend/             # interface React 18 + Vite + TypeScript
└── nwol/
    ├── services/         # ← logique métier : le seul endroit où vit le comportement
    ├── server/           # fabrique de l'app FastAPI + routeurs montés sous /api
    ├── llm/              # client Ollama, prompts, schémas JSON
    ├── metacog/          # jauges, profil à long terme, réflexion
    ├── db/               # connexion SQLite + migrations versionnées
    ├── config/           # réglages : la source de vérité de chaque seuil
    └── tests/            # suites backend + services
```

---

## Vérification

```bash
cd nwol && python -m pytest                     # suite backend
cd nwol && ruff check .                         # lint
cd frontend && npm run build && npx vitest run  # vérification des types, bundle, tests de l'interface
python -m compileall nwol                       # vérification statique
python desktop/pywebview_main.py --server-only  # test de démarrage du serveur sans fenêtre
```

La CI lance la suite backend, la compilation du frontend et les analyses de sécurité (`pip-audit`, `npm audit`, recherche de secrets) à chaque push et à chaque pull request.

---

## Éditions — Local vs Pro

**Ce dépôt est l'édition locale complète, gratuite pour toujours sous licence MIT.** Ce n'est pas une démo bridée : le lecteur, l'assistant, le moteur métacognitif, les jauges, les flashcards et la mémoire de session sont tous là, tous fonctionnels, tous hors ligne.

Meta-Capp **Pro** est une édition hébergée distincte, pour celles et ceux qui veulent la même pédagogie avec une IA plus performante, sans posséder de GPU.

| | **Local** — ce dépôt | **Pro** — hébergée |
|---|:--:|:--:|
| Prix | **Gratuit**, MIT | Abonnement |
| Installation | Installer Ollama, télécharger un modèle | Rien à installer |
| Modèle d'IA | Sur votre machine (la famille gemma4, ou un petit modèle sur 4 Go, au choix) | Modèles hébergés plus performants |
| Réponses et corrections sur les contenus difficiles | Limitées par votre matériel | Plus approfondies et plus fiables |
| Épisodes de langue (histoire, leçon, correction écrite) | Écrits sur votre machine, quelques minutes chacun, en arrière-plan | Générés bien plus vite |
| Fonctionne sans GPU / sur un portable modeste | En mode dégradé | ✅ |
| Même lecteur, moteur cognitif, jauges, flashcards | ✅ | ✅ |
| Fonctionne hors ligne | ✅ | ❌ Connexion nécessaire |
| Vos données restent en local | ✅ Toujours | Traitement à distance |

> **Intéressé par Pro ou par un accès anticipé ?**
> Ouvrez une [discussion](https://github.com/cyyyp100/meta-capp/discussions) : c'est le moyen le plus rapide de joindre le mainteneur.

Les contributions à ce dépôt restent dans ce dépôt, sous licence MIT. Tout ce qui communique avec un service distant, vérifie un abonnement ou réserve une fonctionnalité à une offre payante n'a **pas** sa place ici : voir [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Vos données

Tout ce que Meta-Capp sait de vous tient dans un seul fichier SQLite, sur votre propre
disque : `data/nwol.db` quand l'app tourne depuis les sources, le dossier de données
d'application du système quand elle est empaquetée (`~/Library/Application Support/Meta-Capp/`
sur macOS, `%APPDATA%\Meta-Capp\` sur Windows, `~/.local/share/Meta-Capp/` sur Linux).

- **Ni télémétrie, ni pistage, ni rapport de plantage automatique.**
- **Ni compte, ni activation, ni clé à saisir.**
- Le serveur de l'application écoute sur `127.0.0.1` et refuse tout ce qui vient
  d'ailleurs. Par défaut, la seule connexion qu'ouvre l'app est vers Ollama, sur votre
  propre machine.
- **Une seule exception, sur activation : la vérification des mises à jour.** Désactivée
  par défaut. Une fois activée (Réglages ▸ Mises à jour), *Vérifier maintenant* envoie une
  seule requête à l'API publique de GitHub pour lire le dernier numéro de version, sans
  identifiant ni paramètre ; comme pour toute requête web, GitHub voit votre adresse IP et
  la version de l'app. Rien n'est téléchargé ni installé automatiquement.
- **Portabilité** : exportez tout en un clic (Réglages ▸ Données ▸ *Exporter mes données*) ;
  c'est un fichier SQLite standard que vous pouvez ouvrir vous-même.
- **Effacement** : un bouton *Tout effacer* supprime le profil, les questions, les
  flashcards, les documents, les journaux et la copie de sécurité conservée lors de la
  restauration d'une sauvegarde. Supprimer le dossier de données de l'application efface
  le reste. Rien ne subsiste ailleurs.
- **Les journaux** restent sur votre disque jusqu'à ce que vous les exportiez (*Signaler un
  problème*). Ils contiennent des noms de fichiers et des traces d'erreur, jamais le texte
  de vos documents ; votre dossier personnel y apparaît sous la forme `~`. Relisez-les
  avant de les joindre à une issue publique.

La politique de confidentialité complète se trouve dans [PRIVACY.md](PRIVACY.md), également
accessible depuis Réglages ▸ Aide ▸ À propos, à côté des licences des composants tiers.

---

## Contribuer

Les issues, idées et pull requests sont les bienvenues, en particulier sur la pédagogie, l'accessibilité et les cas limites des PDF.

- Lisez [CONTRIBUTING.md](CONTRIBUTING.md) pour l'installation, les conventions et la liste de vérification des revues.
- En participant, vous acceptez le [Code de conduite](CODE_OF_CONDUCT.md).
- Vous avez trouvé une vulnérabilité ? Suivez [SECURITY.md](SECURITY.md) plutôt que d'ouvrir une issue publique.

Si Meta-Capp vous parle, **mettez une étoile au dépôt** : c'est la façon la plus simple de l'aider à atteindre les apprenants pour qui il a été conçu.

---

## Philosophie éducative

Meta-Capp est construit autour d'une idée centrale :

> ### L'IA ne doit pas rendre les humains cognitivement passifs.

L'avenir de l'IA éducative ne devrait pas être fait de réponses instantanées, de pensée automatisée et de boucles de dépendance. Elle devrait aider les humains à mieux raisonner, à se souvenir plus longtemps, à réfléchir plus profondément et à rester intellectuellement actifs.

Meta-Capp explore ce que devient un logiciel éducatif quand l'IA sert non pas à remplacer la cognition, mais à la renforcer, et quand l'IA elle-même devient une présence discrète et incarnée à côté du document plutôt qu'un mur entre le lecteur et la page.

---

## Licence

Publié sous [licence MIT](LICENSE) — © 2026 Cyprien Vial.

Les composants tiers conservent leur propre licence, toutes gratuites et permissives
(MIT, BSD, Apache-2.0, ISC, PSF, SIL OFL pour les polices) ; le seul composant à copyleft
faible est `certifi` (MPL-2.0, non modifié). Le moteur PDF est **pypdfium2** (Apache-2.0 ou
BSD-3-Clause, qui encapsule PDFium, BSD-3-Clause) plutôt que PyMuPDF, sous AGPL-3.0, qui
imposerait sinon cette licence à tout dérivé à code fermé. Chaque release embarque
`THIRD_PARTY_NOTICES.txt`, généré par `scripts/third_party_notices.py`, que la CI exécute
aussi pour refuser toute dépendance sous copyleft ou sans licence.

Les modèles de langage ne font pas partie de Meta-Capp : Ollama les télécharge sur votre
machine selon leurs propres conditions (Gemma 4 : Apache-2.0 ; EmbeddingGemma : Gemma
Terms of Use).
