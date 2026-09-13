# services/flashcards.py — Opérations flash cards (lecture + écriture).
#
# Enveloppe les CRUD de db.flashcards derrière une frontière stable que les
# pages Tk et le futur serveur web partagent. La génération de tags par LLM
# (asynchrone/streamée) n'est PAS ici : elle relève de services.assistant
# (couche d'événements, étape ultérieure).
from __future__ import annotations

import logging

from db.flashcards import (
    delete_flashcard as _delete_flashcard,
    find_flashcard_id,
    flashcard_key,
    get_due_flashcards,
    get_existing_tags,
    get_flashcards,
    get_session_start_cards,
    lang_flashcard_exists,
    save_flashcard,
    update_review,
)
from db.user import DEFAULT_USER_ID
from utils.tags import fallback_flashcard_tags

logger = logging.getLogger("services.flashcards")

__all__ = [
    "DEFAULT_USER_ID",
    "list_flashcards",
    "existing_tags",
    "create_flashcard",
    "find_flashcard",
    "create_lang_vocab_flashcards",
    "review_flashcard",
    "delete_flashcards",
    "fallback_tags",
    "due_flashcards",
    "session_start_cards",
]


def due_flashcards(doc_id: int | None = None, limit: int = 5, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Cartes dont l'échéance de révision est passée (warm-up du SAS d'entrée)."""
    return get_due_flashcards(user_id, limit, doc_id)


def session_start_cards(doc_id: int | None = None, limit: int = 5, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Cartes du warm-up de début de session (dues prioritaires + pondération
    récence × bonus de matière). Sélection pertinente pour le SAS d'entrée web."""
    return get_session_start_cards(user_id, n=limit, doc_id=doc_id)


def list_flashcards(user_id: int = DEFAULT_USER_ID, **filters) -> list[dict]:
    """Liste filtrée des cartes (filtres : document_id, tags, difficulty...)."""
    return get_flashcards(user_id, **filters)


def existing_tags(user_id: int = DEFAULT_USER_ID, limit: int = 100) -> list[str]:
    return get_existing_tags(user_id, limit)


def find_flashcard(
    front: str,
    back: str,
    user_id: int = DEFAULT_USER_ID,
) -> int | None:
    """Id de la carte qui existe déjà pour ce recto/verso (au sens, pas à
    l'octet : casse, accents et blancs ne comptent pas), None sinon.

    Pour une carte issue d'un échange avec Gemma, passer l'échange BRUT —
    c'est lui qui sert de clé, cf. `create_flashcard(origin=...)`."""
    return find_flashcard_id(user_id, flashcard_key(front, back))


def create_flashcard(
    user_id: int = DEFAULT_USER_ID,
    *,
    front: str,
    back: str,
    tags: list[str] | None = None,
    difficulty: int = 2,
    source: str = "manual",
    question_id: int | None = None,
    document_id: int | None = None,
    chapter_id: int | None = None,
    session_id: int | None = None,
    asset_paths: list[str] | None = None,
    language: str | None = None,
    origin: tuple[str, str] | None = None,
) -> int:
    """Crée une carte — ou renvoie l'id de celle qui existe déjà.

    LA politique de doublon : une carte est identifiée par ce dont elle est
    issue. D'ordinaire son recto/verso ; pour une carte que le LLM a réécrite
    depuis un échange avec Gemma, l'échange brut (`origin`) — la réécriture
    change à chaque appel, deux clics sur « + Flashcard » donneraient sinon deux
    cartes différentes du même échange. L'index UNIQUE (v29) fait le reste :
    on ne crée jamais deux fois la même carte, quel que soit le chemin
    (manuel, auto à la bonne réponse, échange, vocabulaire de langue).
    """
    return save_flashcard(
        user_id,
        question_id=question_id,
        front=front,
        back=back,
        tags=tags,
        difficulty=difficulty,
        source=source,
        document_id=document_id,
        chapter_id=chapter_id,
        session_id=session_id,
        asset_paths=asset_paths,
        language=language,
        dedup_key=flashcard_key(*origin) if origin else None,
    )


def create_lang_vocab_flashcards(
    language: str,
    items: list[dict],
    user_id: int = DEFAULT_USER_ID,
) -> int:
    """Crée des flashcards de vocabulaire depuis un exercice de langue.

    Recto = mot connu **+ la langue cible à produire** (ex. « bientôt en anglais ») ;
    verso = mot dans la langue cible (ex. « soon ») : l'apprenant sait ainsi dans quelle
    langue donner la traduction. Le code langue est déjà le nom français de la langue
    (« anglais », « mandarin »…), d'où le suffixe « en {language} ». Dédup sur
    (utilisateur, langue, recto) pour ne pas réaccumuler le même mot. Renvoie le nb créé.
    """
    created = 0
    for it in items or []:
        if not isinstance(it, dict):
            continue
        # `translation` = mot connu ; `word` = langue cible (verso).
        gloss = (it.get("translation") or "").strip()
        back = (it.get("word") or "").strip()
        if not gloss or not back:
            continue
        front = f"{gloss} en {language}"
        if lang_flashcard_exists(user_id, language, front):
            continue
        try:
            create_flashcard(
                user_id,
                front=front,
                back=back,
                tags=[language],
                source="lang_vocab",
                language=language,
            )
            created += 1
        except Exception:  # une carte ratée ne doit pas casser la génération d'exercice
            logger.warning("Flashcard de vocabulaire non créée (%s -> %s)", front, back, exc_info=True)
    return created


def review_flashcard(card_id: int, verdict: str) -> None:
    """Enregistre une révision (répétition espacée gérée côté DB)."""
    update_review(card_id, verdict)


def delete_flashcards(card_ids: list[int]) -> int:
    """Supprime un lot de cartes ; renvoie le nombre supprimé."""
    count = 0
    for card_id in card_ids:
        _delete_flashcard(card_id)
        count += 1
    return count


def fallback_tags(front: str, back: str, existing_tags: list[str] | None = None) -> list[str]:
    """Tags de repli (sans LLM), pour le chemin d'erreur de génération."""
    return fallback_flashcard_tags(front, back, existing_tags=existing_tags or [])
