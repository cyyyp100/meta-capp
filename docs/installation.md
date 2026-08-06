# Meta-Capp — Guide d'installation

## Utilisateur final (binaire)

1. Télécharger `Meta-Capp-vX.Y.Z-macos.zip` (page Releases / site), dézipper,
   glisser `Meta-Capp.app` dans Applications.
2. **IA locale (recommandé)** : installer [Ollama](https://ollama.com) puis :
   ```bash
   ollama pull gemma4:e4b
   ```
   Sans Ollama, l'app fonctionne en mode dégradé (lecture, flashcards, stats —
   pas d'assistant Gemma).
3. Vos données restent sur votre machine :
   `~/Library/Application Support/Meta-Capp/` — sauvegarde/restauration intégrées
   (page Profil → « Mes données »).

## Développeur (depuis les sources)

```bash
conda create -n nwol python=3.11.9 && conda activate nwol
pip install -r requirements.txt
cd frontend && npm install && cd ..
python main.py --web        # UI web dans une fenêtre native
```

Outillage qualité :

```bash
pip install pre-commit && pre-commit install   # ruff + gitleaks avant chaque commit
cd nwol && python -m pytest                    # suite backend
cd frontend && npm run lint && npm test        # eslint + vitest
```
