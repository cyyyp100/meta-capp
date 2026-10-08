# services/flashcards.py — Opérations flash cards (lecture + écriture).
#
# Enveloppe les CRUD de db.flashcards derrière une frontière stable que les
# pages Tk et le futur serveur web partagent. La génération de tags par LLM
# (asynchrone/streamée) n'est PAS ici : elle relève de services.assistant
# (couche d'événements, étape ultérieure).
from __future__ import annotations

import logging

from config.subjects import canonical_subject
from db.documents import get_document_subject
from db.flashcards import (
    delete_flashcard as _delete_flashcard,
    fill_lang_flashcard_pronunciation,
    find_flashcard_id,
    flashcard_key,
    get_due_flashcards,
    get_existing_tags,
    get_flashcards,
    get_session_start_pool,
    lang_flashcard_exists,
    save_flashcard,
    update_review,
)
from db.user import DEFAULT_USER_ID
from services import selection
from utils.tags import fallback_flashcard_tags
from utils.text import document_reference

logger = logging.getLogger("services.flashcards")

__all__ = [
    "DEFAULT_USER_ID",
    "list_flashcards",
    "existing_tags",
    "create_flashcard",
    "create_auto_flashcard",
    "find_flashcard",
    "create_lang_vocab_flashcards",
    "review_flashcard",
    "delete_flashcards",
    "fallback_tags",
    "due_flashcards",
    "session_start_cards",
    "with_pronunciation_side",
]

# Face d'une carte de langue écrite dans la langue apprise : c'est elle que la
# prononciation accompagne. Vocabulaire hérité : recto « bientôt en anglais »,
# verso « soon » ; feuilleton : recto = le mot, verso = sa traduction.
_TARGET_SIDE = {"lang_vocab": "back", "lang_feuilleton": "front"}


def with_pronunciation_side(card: dict) -> dict:
    """La carte, avec `pronunciation_side` : "front" ou "back", la face où
    afficher la prononciation ; None pour une carte qui n'en a pas."""
    side = _TARGET_SIDE.get(card.get("source") or "", "back") if card.get("pronunciation") else None
    return {**card, "pronunciation_side": side}


def due_flashcards(doc_id: int | None = None, limit: int = 5, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Cartes dont l'échéance de révision est passée (warm-up du SAS d'entrée)."""
    return [with_pronunciation_side(c) for c in get_due_flashcards(user_id, limit, doc_id)]


def session_start_cards(doc_id: int | None = None, limit: int = 5, user_id: int = DEFAULT_USER_ID) -> list[dict]:
    """Cartes de l'échauffement du sas d'entrée d'un document : LA MATIÈRE
    D'ABORD, la date ensuite.

    Deux paliers, dans l'ordre :
      1. les cartes de la matière du document — pour un document de turc, celles
         du module Langues en turc ;
      2. les autres disciplines et les cartes sans matière. Jamais une autre
         langue (le vivier les exclut) : réviser du turc avant un cours
         d'informatique n'échauffe à rien.
    Dans chaque palier, les cartes dues (les plus en retard d'abord) puis le
    tirage pondéré. Matière du document encore inconnue (fiche en cours) :
    palier 2 seul.

    Avant, les cartes dues de TOUTES les matières prenaient d'abord les places,
    et la matière ne faisait que doubler un poids ensuite : un cours
    d'informatique s'ouvrait sur quatre cartes de turc en retard.
    """
    subject = canonical_subject(get_document_subject(doc_id)) if doc_id else None
    pool = get_session_start_pool(user_id, subject)
    if not pool:
        logger.info("Sas d'entrée : aucune flashcard disponible")
        return []
    same = [c for c in pool if subject and canonical_subject(c.get("card_subject")) == subject]
    others = [c for c in pool if not (subject and canonical_subject(c.get("card_subject")) == subject)]
    logger.info(
        "Sas d'entrée : matière=%s, %d carte(s) de la matière, %d autre(s)",
        subject or "—", len(same), len(others),
    )
    picked: list[dict] = []
    for tier in (same, others):
        if len(picked) >= limit:
            break
        picked += _due_then_weighted(tier, limit - len(picked))
    for card in picked:
        logger.info(
            "  → carte id=%s matière=%s due=%s | %s",
            card["id"], card.get("card_subject") or "—", bool(card.get("is_due")),
            (card.get("front") or "")[:60],
        )
    return [with_pronunciation_side(c) for c in picked]


def _due_then_weighted(cards: list[dict], n: int) -> list[dict]:
    """`n` cartes d'un palier : les dues, les plus en retard d'abord, puis un
    tirage pondéré SANS remise (fraîcheur bornée × amortissement « déjà vue »).

    Le tirage évite trois pièges de la version d'origine : un vivier de 60
    cartes, une demi-vie de récence de 7 jours qui éteignait le stock
    d'avant-hier, et un `random.choices` AVEC remise dont les collisions étaient
    rebouchées dans l'ordre de récence. L'amortissement lit `last_reviewed`,
    que l'échauffement écrit lui-même (WarmUp appelle `/review` sur chaque carte
    montrée)."""
    from config.settings import (
        FLASHCARD_RECENCY_FLOOR,
        FLASHCARD_RECENCY_HALF_LIFE_DAYS,
        FLASHCARD_REVIEW_COOLDOWN_DAYS,
        FLASHCARD_REVIEW_FLOOR,
    )

    if n <= 0 or not cards:
        return []
    due = sorted((c for c in cards if c.get("is_due")), key=lambda c: str(c.get("due_at") or ""))[:n]
    if len(due) >= n:
        return due
    rest = [c for c in cards if not c.get("is_due")]
    weights = []
    for card in rest:
        # Fraîcheur bornée : le matériel récent garde un avantage, sans écraser
        # le reste du stock.
        recency = max(
            FLASHCARD_RECENCY_FLOOR,
            selection.decay(selection.age_days(card.get("created_at")), FLASHCARD_RECENCY_HALF_LIFE_DAYS),
        )
        seen = selection.cooldown(
            card.get("last_reviewed"), FLASHCARD_REVIEW_COOLDOWN_DAYS, FLASHCARD_REVIEW_FLOOR,
        )
        weights.append(recency * seen)
        logger.debug(
            "  carte id=%s matière=%s fraîcheur=%.3f vue=%.3f | %s",
            card["id"], card.get("card_subject") or "—", recency, seen, (card.get("front") or "")[:60],
        )
    return due + selection.weighted_sample(rest, weights, n - len(due))


def list_flashcards(user_id: int = DEFAULT_USER_ID, **filters) -> list[dict]:
    """Liste filtrée des cartes (filtres : document_id, tags, difficulty...)."""
    return [with_pronunciation_side(c) for c in get_flashcards(user_id, **filters)]


def existing_tags(user_id: int = DEFAULT_USER_ID, limit: int = 100) -> list[str]:
    return get_existing_tags(user_id, limit)


def find_flashcard(
    front: str,
    back: str,
    user_id: int = DEFAULT_USER_ID,
) -> int | None:
    """Id de la carte qui existe déjà pour ce recto/verso (au sens, pas à
    l'octet : casse, accents et blancs ne comptent pas), None sinon.

    Pour une carte issue d'un échange avec Clikoda, passer l'échange BRUT —
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
    pronunciation: str | None = None,
) -> int:
    """Crée une carte — ou renvoie l'id de celle qui existe déjà.

    LA politique de doublon : une carte est identifiée par ce dont elle est
    issue. D'ordinaire son recto/verso ; pour une carte que le LLM a réécrite
    depuis un échange avec Clikoda, l'échange brut (`origin`) — la réécriture
    change à chaque appel, deux clics sur « + Flashcard » donneraient sinon deux
    cartes différentes du même échange. L'index UNIQUE (v29) fait le reste :
    on ne crée jamais deux fois la même carte, quel que soit le chemin
    (manuel, auto à la bonne réponse, échange, vocabulaire de langue).

    Avec `origin`, le recto/verso réécrit est AUSSI vérifié : si le LLM retombe
    sur une carte que l'utilisateur a déjà (tapée à la main, ou créée à une
    bonne réponse), c'est elle qu'on rend. Sans cela, deux cartes au texte
    identique cohabitaient sous deux clés différentes — un doublon visible que
    l'index, qui ne connaît que la clé, ne pouvait pas empêcher.
    """
    if origin is not None:
        same_text = find_flashcard_id(user_id, flashcard_key(front, back))
        if same_text is not None:
            return same_text
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
        pronunciation=pronunciation,
    )


def create_auto_flashcard(
    card: dict | None,
    *,
    verdict: str | None,
    question_id: int | None,
    document_id: int | None,
    session_id: int | None,
    user_id: int = DEFAULT_USER_ID,
) -> bool:
    """LA politique des cartes AUTOMATIQUES, celles que Clikoda propose après une
    bonne réponse en lecture. Renvoie True si une carte NEUVE a été créée — c'est
    elle seule qu'on annonce à l'élève.

    Refusée :
      - une réponse fausse (seuls `correct` et `partial` en créent) ;
      - une carte déjà connue (même recto/verso au sens près) : ni recréée ni
        annoncée ;
      - une carte dont le recto ou le verso renvoie au document (« according to
        the text », « Based on Table 3.5 »…, `utils.text.document_reference`) :
        le sas d'entrée la servirait sans lui, et l'élève ne pourrait que deviner.
        Le prompt le demande déjà au LLM ; cette vérification ne dépend pas de
        son obéissance.

    Une carte refusée est journalisée, jamais signalée. « + Flashcard » (le choix
    explicite de l'élève) ne passe pas par ici : il n'est pas filtré."""
    if not isinstance(card, dict) or verdict not in ("correct", "partial"):
        return False
    front = str(card.get("front") or "").strip()
    back = str(card.get("back") or "").strip()
    if not front or not back:
        return False
    reference = document_reference(front) or document_reference(back)
    if reference:
        logger.info("Flashcard automatique refusée : renvoi au document « %s » | %s", reference, front[:80])
        return False
    if find_flashcard(front, back, user_id) is not None:
        return False
    create_flashcard(
        user_id,
        question_id=question_id,
        front=front,
        back=back,
        tags=card.get("tags"),
        difficulty=card.get("difficulty") or 2,
        source="auto",
        document_id=document_id,
        session_id=session_id,
    )
    return True


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

    La prononciation (`phonetic` de l'item : transcription, ou translittération
    tonée pour un script non latin) va dans sa propre colonne, jamais dans le
    verso, qui reste la réponse attendue. Pas de carte de langue sans elle : un
    item que Clikoda a laissé sans prononciation n'en crée pas (le mot reviendra
    dans un autre exercice) ; une carte déjà connue qui n'en avait pas la reçoit
    au passage.
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
        pronunciation = (it.get("phonetic") or "").strip()
        if lang_flashcard_exists(user_id, language, front):
            fill_lang_flashcard_pronunciation(user_id, language, front, pronunciation)
            continue
        if not pronunciation:
            logger.debug("Vocabulaire sans prononciation, pas de carte (%s -> %s)", front, back)
            continue
        try:
            create_flashcard(
                user_id,
                front=front,
                back=back,
                tags=[language],
                source="lang_vocab",
                language=language,
                pronunciation=pronunciation,
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
