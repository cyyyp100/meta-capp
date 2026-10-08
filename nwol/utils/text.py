# utils/text.py — Primitives de comparaison textuelle partagées.
#
# Le repli d'accents avait été réécrit dans chaque module qui en avait besoin
# (recherche brainstorming, cartes de langue, recherche de bibliothèque). Deux
# implémentations divergentes du même « est-ce que ces deux textes sont le même
# mot ? » donnent deux résultats de recherche différents pour la même requête.
from __future__ import annotations

import hashlib
import re
import unicodedata


def fold(text: str) -> str:
    """Minuscule + suppression des accents (comparaison robuste).

    « Équations » et « equations » doivent être le même mot pour une recherche.
    """
    decomposed = unicodedata.normalize("NFKD", (text or "").strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fingerprint(*parts: str) -> str:
    """Empreinte stable de textes comparés « au sens », pas à l'octet.

    Chaque partie est pliée (`fold`) et ses blancs sont réduits à un espace :
    « Qu'est-ce que  l'ADN ? » et « qu'est-ce que l'adn ? » donnent la même
    empreinte. Sert de clé de doublon en base (flashcards) : deux clics sur le
    même « + Flashcard », ou la même carte tapée deux fois, n'en font qu'une.
    """
    joined = "\x1f".join(" ".join(fold(part).split()) for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


# ── Renvoi au document ───────────────────────────────────────────────────────
#
# Une question ou une carte qui dit « according to the text », « Based on
# Table 3.5 » ou « mentionnés dans le texte » ne se comprend qu'avec le
# document sous les yeux. Le quiz (sans contexte de lecture) et le sas d'entrée
# (où le document n'est pas ouvert) la servent pourtant seule : l'élève ne peut
# que deviner. UNE liste de patrons, partagée par le quiz
# (db/quiz_questions._is_unusable_for_quiz), les cartes automatiques
# (services/flashcards.create_auto_flashcard) et la migration v41 qui a purgé
# celles déjà créées — deux copies avaient déjà divergé (la liste du quiz ne
# connaissait que le français).
#
# Patrons PRUDENTS : jamais un mot seul (« table » est aussi une table de
# hachage, « tableau » un tableau de valeurs, « figure » une figure de style),
# toujours une tournure qui ne désigne que le document. Ils s'appliquent au
# texte plié (`fold`), apostrophes typographiques ramenées à « ' ».

# Le document lui-même, et ce qu'il montre.
_EN_DOC = (
    r"(?:text|document|passage|paper|article|chapter|excerpt|extract|paragraph|"
    r"section|lesson|course|textbook|handout|slides?|authors?)"
)
_EN_VISUAL = (
    r"(?:table|figure|diagram|graph|chart|plot|image|picture|illustration|map|"
    r"schema|screenshot|photo|histogram)"
)
_FR_DOC = (
    r"(?:texte|document|passage|paragraphe|extrait|article|chapitre|cours|auteurs?|"
    r"autrice|enonce|lecon|polycopie|manuel|section)"
)
# « figure de style » n'est pas une figure du document.
_FR_VISUAL = (
    r"(?:tableau|figure(?!\s+de\s+style)|schema|graphique|diagramme|graphe|"
    r"illustration|image|photo|photographie|courbe|histogramme)"
)
# « the text editor », « the document object », « the graph structure » : le
# nom n'est qu'un premier mot, ce n'est pas le document qu'on désigne.
_EN_NOT_COMPOUND = (
    r"(?![-\s]+(?:box|files?|editor|fields?|messages?|types?|objects?|model|root|head|"
    r"body|size|format|structure|mode|nodes?|strings?|ids?|keys?|database|store|"
    r"class(?:es)?|elements?|area|input|output|plan|habits?)\b)"
)
# « the text of the Constitution », « le texte de loi », « l'article 5 » : un
# texte précis, pas celui qu'on lit.
_EN_NOT_SPECIFIED = r"(?!\s+of\b)"
_FR_NOT_SPECIFIED = r"(?!\s*(?:(?:de|du|des)\b|d'|\(?\d))"
# « the graph above the x-axis », « below 0 °C » : une position, pas un renvoi.
_NOT_A_QUANTITY = r"(?!\s+(?:the|a|an|its|their|this|that|these|those|zero)\b|\s*[-+−]?\d)"
# « dans le texte ? », « dans le tableau, … », « dans le passage qui suit » :
# le nom clôt le groupe. « dans le passage de l'état liquide à l'état gazeux »,
# « dans le tableau périodique » ou « dans le document HTML » continuent.
_FR_CLAUSE_END = (
    r"(?=\s*(?:$|[,.;:?!)\]»\"…]|(?:ci-dess\w*|suivante?s?|precedente?s?|qui|que|ou|et|pour)\b))"
)
_EN_CLAUSE_END = r"(?=\s*(?:$|[,.;:?!)\]\"'…]))"

_EN_PARTICIPLES = (
    r"(?:mentioned|described|shown|presented|discussed|cited|listed|given|defined|"
    r"introduced|outlined|explained|stated|reported|proposed|used|depicted|illustrated|"
    r"displayed|summari[sz]ed|highlighted|provided|referenced|quoted|covered|studied|"
    r"analy[sz]ed|reviewed|detailed|noted|considered|identified|named|evaluated|"
    r"compared|tested|measured)"
)
_EN_SAYING = (
    r"(?:say|says|said|states?|stated|claims?|claimed|suggests?|suggested|argues?|argued|"
    r"mentions?|mentioned|describes?|described|explains?|explained|impl(?:y|ies|ied)|"
    r"indicates?|indicated|notes?|noted|highlights?|highlighted|emphasi[sz]e[sd]?|"
    r"concludes?|concluded|presents?|presented|proposes?|proposed|reports?|reported|"
    r"shows?|showed|shown|demonstrates?|demonstrated|refers?|referred)"
)
# Participes passés repliés, accordés par (?:e|s|es)? : « mentionnés »,
# « décrite », « présentées ».
_FR_PARTICIPLES = (
    r"(?:mentionne|decrit|presente|cite|evoque|aborde|etudie|explique|defini|introduit|"
    r"utilise|propose|illustre|donne|indique|enonce|expose|vu|represente|montre|resume|"
    r"detaille|developpe|souligne|liste|employe|analyse|traite|discute|rapporte|nomme|"
    r"signale|releve|ecrit|precise|reproduit|fourni|compare|observe|mesure)(?:e|s|es)?"
)
_FR_SAYING = (
    r"(?:dit|affirme|mentionne|explique|suggere|indique|evoque|souligne|presente|decrit|"
    r"precise|montre|propose|defend|soutient|avance|conclut|rapporte|cite|aborde|"
    r"illustre|rappelle|insiste|developpe|definit|introduit|compare|critique|denonce)"
)
_FR_SUBJECTS = (
    r"(?:le\s+texte|le\s+document|le\s+passage|l'extrait|l'auteur|l'autrice|les\s+auteurs|"
    r"l'article|le\s+chapitre|le\s+cours|l'enonce)"
)
# Ce qu'on dit d'un texte : son auteur, son idée, son titre.
_EN_ABOUT = (
    r"(?:authors?|title|main\s+(?:idea|point|argument)|central\s+idea|thesis|conclusion|"
    r"introduction|purpose|aim|theme|topic|summary)"
)
_FR_ABOUT = (
    r"(?:auteurs?|autrice|titre|idee\s+(?:principale|centrale)|these|conclusion|"
    r"introduction|theme|objectif|but|propos|message|resume|sujet|problematique)"
)

# Numérotation propre au document : « Table 3.5 », « figure 2 », « Équation (4) »,
# « tableau n° 3 », « chapitre 4 ».
_NUMBERED = re.compile(
    r"\b(?:table|tableau|figure|fig\.?|equation|eqn?\.|section|chapter|chapitre|annexe|"
    r"appendix|exercise|exercice|theorem|theoreme|lemma|lemme|algorithm|algorithme|listing)"
    r"\s*(?:n[°o]\.?\s*)?\(?\d"
    r"|\b(?:a\s+la|en|sur\s+la|on|at)\s+page\s+\d"
)
# Numérotation romaine (« Table I », « Section II ») ou par lettre (« Appendix A ») :
# lue sur le texte NON plié — en minuscules, « table i » ne dit plus rien.
_NUMBERED_CASED = re.compile(
    r"\b(?:Table|TABLE|Tableau|TABLEAU|Figure|FIGURE|Fig\.|Section|SECTION|Chapter|CHAPTER|"
    r"Chapitre|CHAPITRE)\s+[IVX]{1,5}\b"
    r"|\b(?:Appendix|APPENDIX|Annexe|ANNEXE)\s+[A-Z]\b"
)

# Chaque patron porte deux drapeaux :
#   - ANAPHORE : un nom déjà posé plus tôt dans le texte (« Soit un tableau t…
#     Trie ce tableau. », « Consider the list [3, 1, 2]. Sort the list above. »)
#     est repris, pas désigné dans le document ;
#   - VERS LA SUITE : « the following list: 3, 1, 2 », « l'équation ci-dessous :
#     x + 1 = 2 » donnent leur contenu juste après — la carte se suffit à
#     elle-même.
_ANAPHORA, _FORWARD = 1, 2

_REFERENCE_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = tuple(
    (re.compile(pattern), flags)
    for pattern, flags in (
        # « according to the text », « based on the table »
        (
            rf"\b(?:according\s+to|based\s+on|referring\s+to|as\s+per)\s+(?:the|this|that)\s+"
            rf"(?:{_EN_DOC}|{_EN_VISUAL})\b{_EN_NOT_SPECIFIED}{_EN_NOT_COMPOUND}",
            0,
        ),
        # « mentioned in the text », « shown in the figure »
        (
            rf"\b{_EN_PARTICIPLES}\s+(?:in|by|within|throughout|on)\s+(?:the|this|that)\s+"
            rf"(?:{_EN_DOC}|{_EN_VISUAL})\b{_EN_NOT_SPECIFIED}{_EN_NOT_COMPOUND}",
            0,
        ),
        # « in this text », « the given passage », « the previous chapter »
        (
            rf"\b(?:this|the\s+(?:present|given|provided|current|accompanying|attached|"
            rf"previous|preceding))\s+(?P<noun>{_EN_DOC})\b{_EN_NOT_COMPOUND}",
            _ANAPHORA | _FORWARD,
        ),
        # « this table », « this figure »
        (rf"\bthis\s+(?P<noun>{_EN_VISUAL})\b{_EN_NOT_COMPOUND}", _ANAPHORA | _FORWARD),
        # « the following table », « the figure above »
        (
            rf"\bthe\s+(?:following|above|below|preceding|previous|accompanying|attached|"
            rf"adjacent)\s+(?P<noun>{_EN_VISUAL}|list|data|dataset|example|code|snippet|"
            rf"equation|formula|output|excerpt|passage|text|statement|quote|quotation)\b",
            _ANAPHORA | _FORWARD,
        ),
        (
            rf"\b(?P<noun>{_EN_VISUAL}|list|example|code|snippet|equation|formula|excerpt|"
            rf"passage|text|quote)\s+(?:above|below)\b{_NOT_A_QUANTITY}",
            _ANAPHORA | _FORWARD,
        ),
        # « shown above », « listed below »
        (
            r"\b(?:shown|given|listed|presented|described|depicted|illustrated|displayed|"
            r"mentioned|stated|defined|provided|discussed|explained|outlined|written|cited|"
            rf"quoted|seen)\s+(?:above|below)\b{_NOT_A_QUANTITY}",
            _FORWARD,
        ),
        # « what does the text say », « the author argues »
        (
            r"\b(?:the|this)\s+(?:text|document|passage|excerpt|extract|article|paper|chapter|"
            rf"authors?|study)\s+{_EN_SAYING}\b",
            0,
        ),
        # « the main idea of the passage »
        (
            rf"\b{_EN_ABOUT}\s+of\s+(?:the|this)\s+(?:text|document|passage|excerpt|extract|"
            rf"article|paper|chapter|paragraph|section|lesson)\b{_EN_NOT_COMPOUND}",
            0,
        ),
        # « in the text? », « in the chapter, … »
        (
            r"\bin\s+the\s+(?:text|passage|excerpt|extract|article|paper|chapter|reading|"
            rf"lesson)\s*{_EN_CLAUSE_END}",
            0,
        ),
        # « selon le texte », « d'après l'auteur »
        (
            rf"\b(?:selon|d'apres)\s+(?:le|la|l'|les)\s*(?:{_FR_DOC}|tableau|figure|schema|"
            rf"graphique|diagramme)\b{_FR_NOT_SPECIFIED}",
            0,
        ),
        # « mentionnés dans le texte », « représenté sur la figure »
        (
            rf"\b{_FR_PARTICIPLES}\s+(?:dans|par|sur)\s+(?:le|la|l'|ce|cet|cette)\s*"
            rf"(?:{_FR_DOC}|{_FR_VISUAL})\b{_FR_NOT_SPECIFIED}",
            0,
        ),
        # « ce tableau », « cette figure », « dans ce passage », « selon cet auteur »
        (rf"\b(?:ce|cet|cette)\s+(?P<noun>{_FR_DOC}|{_FR_VISUAL})\b", _ANAPHORA | _FORWARD),
        # « dans le tableau », « sur la figure », « dans le passage, … »
        (
            r"\b(?:dans|sur)\s+(?:le|la|l')\s*(?P<noun>texte|document|passage|paragraphe|"
            r"extrait|cours|chapitre|enonce|polycopie|manuel|tableau|figure|schema|graphique|"
            rf"diagramme|illustration)\b{_FR_CLAUSE_END}",
            _ANAPHORA,
        ),
        # « l'auteur affirme », « que dit le texte »
        (rf"\b{_FR_SUBJECTS}\s+{_FR_SAYING}\b", 0),
        (rf"\b{_FR_SAYING}(?:-t-il|-t-elle)?\s+{_FR_SUBJECTS}\b{_FR_NOT_SPECIFIED}", 0),
        # « l'idée principale du texte », « le titre de ce document »
        (
            rf"\b{_FR_ABOUT}\s+(?:du|de\s+(?:ce|cet|cette|la|l'))\s*(?:texte|document|passage|"
            rf"extrait|article|chapitre|paragraphe|cours|lecon|section)\b{_FR_NOT_SPECIFIED}",
            0,
        ),
        # « le tableau suivant », « la figure précédente », « l'exemple ci-dessous »
        (
            rf"\b(?P<noun>{_FR_DOC}|{_FR_VISUAL}|liste|exemple|exercice|code|equation|formule|"
            r"citation|donnees)\s+(?:suivante?s?|precedente?s?|ci-dessus|ci-dessous)\b",
            _ANAPHORA | _FORWARD,
        ),
        # « ci-dessus », « ci-dessous »
        (r"\bci[-\s]?dess(?:us|ous)\b", _FORWARD),
    )
)

# Ce qui suit un renvoi « vers la suite » quand la carte donne elle-même son
# contenu : deux-points ou saut de ligne, puis du texte.
_INLINE_CONTENT = re.compile(r"\s*[:\n]\s*\S.{2,}", re.DOTALL)
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "‘": "'", "`": "'"})


def document_reference(text: str) -> str | None:
    """Le renvoi au document trouvé dans `text` (forme pliée), sinon None.

    « …according to the text… » → « according to the text » ; « Based on
    Table 3.5 » → « table 3 » ; « mentionnés dans le texte » → « mentionnes dans
    le texte ». Un texte qui ne se comprend qu'avec le document sous les yeux ne
    peut être ni une question de quiz sans contexte ni une carte de révision.
    """
    raw = unicodedata.normalize("NFKC", text or "")
    match = _NUMBERED_CASED.search(raw)
    if match:
        return fold(match.group(0))
    folded = fold(raw).translate(_APOSTROPHES)
    if not folded:
        return None
    match = _NUMBERED.search(folded)
    if match:
        return match.group(0)
    for pattern, flags in _REFERENCE_PATTERNS:
        for match in pattern.finditer(folded):
            if flags & _ANAPHORA and re.search(
                rf"\b{re.escape(match.group('noun'))}\b", folded[: match.start()]
            ):
                continue  # le nom a été posé plus tôt : il est repris, pas désigné
            if flags & _FORWARD and _INLINE_CONTENT.match(folded, match.end()):
                continue  # le contenu annoncé suit, dans le texte même
            return match.group(0)
    return None
