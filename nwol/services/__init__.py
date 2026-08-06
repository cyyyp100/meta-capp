# services/ — Couche de service (Python pur, sans Tkinter ni FastAPI).
#
# Frontière partagée : les pages Tkinter ET le futur serveur web/FastAPI
# consomment ces fonctions, qui renvoient des dicts/lists JSON-sérialisables.
# Aucune logique de présentation ici (pas de couleurs, polices, libellés
# traduits) : seulement la lecture des données et les calculs métier.
