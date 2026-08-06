# Politique de confidentialité — Meta-Capp

## Le principe : vos données ne quittent pas votre machine

Meta-Capp est un logiciel **local**. Documents PDF, questions/réponses, profil
d'apprentissage, flashcards et statistiques sont stockés **uniquement** sur votre
ordinateur (`~/Library/Application Support/Meta-Capp/`). L'intelligence
artificielle (Gemma) s'exécute **localement** via Ollama : vos contenus ne sont
envoyés à aucun serveur, ni à nous, ni à un tiers.

Le serveur applicatif écoute sur `127.0.0.1` et refuse toute requête venue
d'ailleurs. La seule connexion sortante possible est celle d'Ollama, sur votre
propre machine.

## Ce que nous ne collectons pas

- Aucune télémétrie, aucun tracking, aucun rapport de crash automatique.
- Aucun compte en ligne, aucune activation, aucune clé à saisir.

## Vos droits et vos outils

- **Portabilité** : exportez l'intégralité de vos données en un clic
  (Profil → « Mes données » → Exporter) — le fichier est une base SQLite standard.
- **Effacement** : bouton « Tout effacer » dans l'application (profil, questions,
  flashcards, documents, journaux — irréversible, confirmation exigée). La
  suppression du dossier de données de l'application efface la totalité. Rien ne
  subsiste ailleurs.
- **Diagnostic volontaire** : vous pouvez exporter vos journaux techniques (zip)
  pour les joindre à un rapport de bug. Ils ne contiennent pas le texte de vos
  documents. Rien n'est transmis sans ce geste explicite de votre part.
