# services/ — Couche métier (Python pur, sans FastAPI ni asyncio).
#
# C'est LE domicile de la logique applicative : le serveur web n'y ajoute que le
# transport (HTTP/WebSocket) et la validation d'entrée. Les fonctions renvoient
# des dicts/lists JSON-sérialisables ; aucune logique de présentation ici (pas
# de couleurs, polices, libellés traduits).
#
# Règle de non-duplication : une politique métier vit dans UN seul module. Un
# routeur ne la réimplémente pas, et un seuil déclaré dans `config/settings.py`
# n'est jamais recopié en littéral. La migration de l'ancienne UI vers le web
# avait enfreint les deux, et les copies ont silencieusement divergé.
