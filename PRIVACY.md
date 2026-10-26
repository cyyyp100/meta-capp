# Privacy policy — Meta-Capp (local edition)

*Last updated: 26 October 2026.* — [Version française plus bas](#politique-de-confidentialité--meta-capp-édition-locale)

## The principle: your data never leaves your computer

Meta-Capp is **local** software. Imported documents, questions and answers,
learning profile, flashcards, language sessions and statistics are stored
**only** on your computer, in the application's data folder:

| System | Folder |
|---|---|
| macOS | `~/Library/Application Support/Meta-Capp/` |
| Windows | `%APPDATA%\Meta-Capp\` |
| Linux | `~/.local/share/Meta-Capp/` |

The assistant, Clikoda, is an AI: a language model that runs **locally**
through Ollama. Your content is sent to no server, neither ours nor anyone
else's. The publisher of Meta-Capp receives, sees and keeps none of your data:
there is no Meta-Capp server for the application to talk to.

The application's internal server listens on `127.0.0.1` (your computer only)
and refuses any request coming from elsewhere.

## The only possible Internet connection, off by default

**Update check** (Settings ▸ Updates): until you turn it on, no request is
made. Once on, the « Check now » button sends a single request to GitHub's
public API to read the number of the latest release. It carries no identifier
and none of your data; like any web request, GitHub (Microsoft) sees your IP
address and the application's version. Nothing is downloaded or installed
automatically. You can turn the option off at any time.

Downloading the AI model (`ollama pull`) is done by Ollama, outside Meta-Capp,
under Ollama's terms.

## What we do not collect

- No telemetry, no tracking, no automatic crash reports.
- No online account, no activation, no key to enter.

## Your rights and your tools

- **Access and portability**: export all your data in one click (Settings ▸
  Data ▸ « Export my data »). The file is a standard SQLite database, readable
  by any tool.
- **Erasure**: « Erase everything » deletes the profile, questions, flashcards,
  imported documents, logs and the safety copy made during a restore
  (irreversible, confirmation required). Deleting the data folder above erases
  everything. Nothing remains anywhere else.
- **Restore**: restoring a backup keeps a copy of your current data, just in
  case; only the most recent one is kept, and « Erase everything » deletes it.

## Technical logs

The application keeps a technical log in its data folder, to diagnose
problems. It contains file names, durations and errors, **never the text of
your documents or your answers**; the path of your home folder appears as `~`.
It leaves your computer only if you export it yourself (Settings ▸ Help ▸
« Report a problem »). Read it before attaching it to a public message.

## Minors

Since Meta-Capp collects no data, it asks for no age and no parental consent.
The data stays on the learner's device, under the control of whoever uses it.

## Contact

A question about this policy: open an issue on
https://github.com/cyyyp100/meta-capp/issues.

---

# Politique de confidentialité — Meta-Capp (édition locale)

*Dernière mise à jour : 26 octobre 2026.*

## Le principe : vos données ne quittent pas votre machine

Meta-Capp est un logiciel **local**. Documents importés, questions et réponses,
profil d'apprentissage, flashcards, séances de langue et statistiques sont
stockés **uniquement** sur votre ordinateur, dans le dossier de données de
l'application :

| Système | Dossier |
|---|---|
| macOS | `~/Library/Application Support/Meta-Capp/` |
| Windows | `%APPDATA%\Meta-Capp\` |
| Linux | `~/.local/share/Meta-Capp/` |

L'assistante Clikoda est une IA : un modèle de langue qui s'exécute
**localement** via Ollama. Vos contenus ne sont envoyés à aucun serveur, ni à
nous, ni à un tiers. L'éditeur de Meta-Capp ne reçoit, ne voit et ne conserve
aucune de vos données : il n'existe aucun serveur Meta-Capp auquel
l'application parlerait.

Le serveur interne de l'application écoute sur `127.0.0.1` (votre machine
seulement) et refuse toute requête venue d'ailleurs.

## La seule connexion à Internet possible, et elle est désactivée par défaut

**Vérification des mises à jour** (Réglages ▸ Mises à jour) : tant que vous ne
l'activez pas, aucune requête ne part. Une fois activée, le bouton « Vérifier
maintenant » envoie une seule requête à l'API publique de GitHub pour lire le
numéro de la dernière version. Elle ne contient aucun identifiant ni aucune de
vos données ; comme toute requête web, GitHub (Microsoft) voit votre adresse IP
et la version de l'application. Rien n'est téléchargé ni installé
automatiquement. Vous pouvez désactiver l'option à tout moment.

Le téléchargement du modèle d'IA (`ollama pull`) se fait par Ollama, hors de
Meta-Capp, selon les conditions d'Ollama.

## Ce que nous ne collectons pas

- Aucune télémétrie, aucun traçage, aucun rapport de plantage automatique.
- Aucun compte en ligne, aucune activation, aucune clé à saisir.

## Vos droits et vos outils

- **Accès et portabilité** : exportez l'intégralité de vos données en un clic
  (Réglages ▸ Données ▸ « Exporter mes données »). Le fichier est une base
  SQLite standard, lisible par n'importe quel outil.
- **Effacement** : « Tout effacer » supprime profil, questions, flashcards,
  documents importés, journaux et la copie de sécurité créée lors d'une
  restauration (action irréversible, confirmation exigée). Supprimer le dossier
  de données ci-dessus efface la totalité. Rien ne subsiste ailleurs.
- **Restauration** : restaurer une sauvegarde garde une copie de vos données du
  moment, au cas où ; seule la plus récente est conservée, et « Tout effacer »
  la supprime.

## Journaux techniques

L'application tient un journal technique dans son dossier de données, pour
diagnostiquer un problème. Il contient des noms de fichiers, des durées et des
erreurs, **jamais le texte de vos documents ni vos réponses** ; le chemin de
votre dossier personnel y apparaît sous la forme `~`. Il ne quitte votre
ordinateur que si vous l'exportez vous-même (Réglages ▸ Aide ▸ « Signaler un
problème »). Relisez-le avant de le joindre à un message public.

## Mineurs

Meta-Capp ne collectant aucune donnée, il ne demande ni âge ni autorisation
parentale. Les données restent sur l'appareil de l'élève, sous le contrôle de
la personne qui l'utilise.

## Contact

Une question sur cette politique : ouvrez une issue sur
https://github.com/cyyyp100/meta-capp/issues.
