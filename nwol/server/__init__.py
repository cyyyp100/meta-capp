# server/ — API locale FastAPI (127.0.0.1), embarquée dans le logiciel.
#
# Le frontend (navigateur en dev, WebView native en prod via pywebview/Tauri)
# parle à ce serveur uniquement. Les routers sont des adaptateurs fins : ils
# appellent nwol/services/* et sérialisent. Aucune logique métier ici.
