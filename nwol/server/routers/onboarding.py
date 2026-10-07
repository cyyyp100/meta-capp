# server/routers/onboarding.py — Le document emprunté par la visite guidée.
#
# AUCUN paramètre d'entrée, comme `updates.py` et pour la même raison : ces deux
# routes agissent sur UN document, celui que le service a lui-même créé. Rien
# dans une requête ne désigne une cible, donc rien ne peut détourner la
# suppression vers un document de l'utilisateur.
#
# Elles restent derrière `LocalOnlyGuard` et exigent le nonce de lancement,
# comme le reste de l'API.
from __future__ import annotations

from fastapi import APIRouter

import i18n
from services.onboarding import discard_demo_document, ensure_demo_document

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/demo")
def borrow_demo() -> dict:
    """Prête le document de démonstration, dans la langue courante.

    Renvoie `{"document": null}` — et non une erreur — quand la ressource est
    absente : la visite doit alors sauter son chapitre lecture, pas s'arrêter.
    Un tutoriel qui échoue est pire qu'un tutoriel incomplet.
    """
    keywords = [k.strip() for k in i18n.t("onboarding.doc_keywords").split(",") if k.strip()]
    document = ensure_demo_document(
        lang=i18n.current_lang(),
        title=i18n.t("onboarding.doc_title"),
        # Une CLÉ de matière (config/subjects.py), traduite par l'interface comme
        # celle de tout document — pas un libellé, qui ferait une matière à part.
        subject="informatique",
        summary=i18n.t("onboarding.doc_summary"),
        keywords=keywords,
    )
    return {"document": document}


@router.delete("/demo")
def return_demo() -> dict:
    """Rend le document de démonstration. Idempotente : rappelable sans risque."""
    discard_demo_document()
    return {"ok": True}
