# services/lang_games.py — Petits jeux et micro-items, construits depuis le texte (§ 10.3).
#
# Rien n'est demandé à Clikoda : chaque jeu est tiré de l'épisode stocké (jetons,
# glossaire, point du jour, aides calculées), avec une graine dérivée de l'id de
# séance — la variété est reproductible. Tout se joue au tap. Le front reçoit
# les clés pour un retour immédiat, mais le résultat ENREGISTRÉ est recalculé
# ici (`grade`, R23) : la logique vit dans les services.
#
# Un item : {"ref", "kind", "prompt", "options"|..., "expected", "lexemes",
# "units"} — `lexemes` et `units` disent quels mots et quels signes la réponse
# fait travailler (acquisition, P10-P11).
from __future__ import annotations

import random
import unicodedata

from config.settings import LANG_GAMES_AVOID_LAST_RUNS, LANG_GAMES_PER_RUN, LANG_POINT_MICRO_ITEMS
from services import lang_arabic as arabic
from services.lang_scripts import ARABIC_SCRIPT, HANZI_SCRIPT, TONES_SCRIPT, script_units_of_token
from services.lang_text import find_token_span, fold

# Facilité (1 = le plus facile) : le dernier jeu d'une séance est toujours
# pris parmi les plus faciles (R22).
GAMES: dict[str, dict] = {
    "qui_a_dit": {"ease": 1, "families": ("latin", "hanzi", "arabe")},
    "apparier": {"ease": 1, "families": ("latin", "hanzi", "arabe")},
    "retrouver_la_lettre": {"ease": 1, "families": ("arabe",)},
    "caractere_sens": {"ease": 1, "families": ("hanzi",)},
    "completer_replique": {"ease": 2, "families": ("latin", "hanzi", "arabe")},
    "trouver_dans_le_texte": {"ease": 2, "families": ("latin", "hanzi", "arabe")},
    "bonne_forme": {"ease": 2, "families": ("latin", "hanzi", "arabe")},
    "caractere_pinyin": {"ease": 2, "families": ("hanzi",)},
    "lettre_forme": {"ease": 2, "families": ("arabe",)},
    "lire_vocalise": {"ease": 2, "families": ("arabe",)},
    "remettre_en_ordre": {"ease": 3, "families": ("latin", "hanzi", "arabe")},
    "ton_du_caractere": {"ease": 3, "families": ("hanzi",)},
}
ITEMS_PER_GAME = 4
_FORMS = ("isolated", "initial", "medial", "final")
# Jeux déjà joués comme micro-items du point du jour : les petits jeux ne les
# reprennent pas dans la même séance.
POINT_KINDS = ("trouver_dans_le_texte", "bonne_forme")
# Natures qui font un bon appariement ; les mots-outils (« un = un ») n'apprennent rien.
_CONTENT_POS = ("nom", "verbe", "adjectif", "adverbe", "expression", "interjection")


def _word_tokens(line: dict) -> list[int]:
    return [i for i, t in enumerate(line.get("tokens") or []) if t.get("w")]


def _lemma(episode: dict, tok: dict) -> str | None:
    gi = tok.get("g")
    gloss = episode.get("glossary") or []
    if gi is None or not 0 <= gi < len(gloss):
        return None
    return gloss[gi].get("lemma") or gloss[gi].get("form")


def _distinct(values: list[str], rng: random.Random, n: int, exclude: str) -> list[str]:
    pool = []
    seen = {fold(exclude)}
    for v in values:
        if v and fold(v) not in seen:
            seen.add(fold(v))
            pool.append(v)
    rng.shuffle(pool)
    return pool[:n]


def _options(correct: str, others: list[str], rng: random.Random) -> list[str]:
    opts = [correct, *others]
    rng.shuffle(opts)
    return opts


# ── Constructeurs ─────────────────────────────────────────────────────────────

def _names(ep: dict) -> set[str]:
    return {fold(ln["speaker"]) for ln in ep["lines"]}


def _completer_replique(ep: dict, rng: random.Random, family: str) -> list[dict]:
    items = []
    names = _names(ep)
    # Ni prénom en réponse ni prénom en distracteur : trop facile, ou absurde.
    all_words = [ln["tokens"][i]["text"] for ln in ep["lines"] for i in _word_tokens(ln)
                 if fold(ln["tokens"][i]["text"]) not in names]
    lines = [(li, ln) for li, ln in enumerate(ep["lines"]) if len(_word_tokens(ln)) >= 3]
    rng.shuffle(lines)
    for li, ln in lines[:ITEMS_PER_GAME]:
        candidates = [i for i in _word_tokens(ln) if ln["tokens"][i].get("g") is not None
                      and fold(ln["tokens"][i]["text"]) not in names]
        if not candidates:
            continue
        ti = rng.choice(candidates)
        answer = ln["tokens"][ti]["text"]
        others = _distinct(all_words, rng, 3, answer)
        if len(others) < 2:
            continue
        lemma = _lemma(ep, ln["tokens"][ti])
        items.append({
            "prompt": {"line": li, "blank": ti, "translation": ln["translation"]},
            "options": _options(answer, others, rng), "expected": answer,
            "lexemes": [lemma] if lemma else [],
        })
    return items


def _qui_a_dit(ep: dict, rng: random.Random, family: str) -> list[dict]:
    speakers = list(dict.fromkeys(ln["speaker"] for ln in ep["lines"]))
    if len(speakers) < 2 or ep.get("format") not in ("dialogue", "sms"):
        return []
    lines = list(enumerate(ep["lines"]))
    rng.shuffle(lines)
    return [{
        "prompt": {"line": li}, "options": speakers, "expected": ln["speaker"], "lexemes": [],
    } for li, ln in lines[:ITEMS_PER_GAME]]


def _remettre_en_ordre(ep: dict, rng: random.Random, family: str) -> list[dict]:
    items = []
    lines = [(li, ln) for li, ln in enumerate(ep["lines"]) if 3 <= len(_word_tokens(ln)) <= 8]
    rng.shuffle(lines)
    for li, ln in lines[:3]:
        order = [ln["tokens"][i]["text"] for i in _word_tokens(ln)]
        shuffled = order[:]
        for _ in range(5):
            rng.shuffle(shuffled)
            if shuffled != order:
                break
        items.append({
            "prompt": {"line": li, "translation": ln["translation"]}, "options": shuffled, "expected": order,
            "lexemes": [lem for lem in (_lemma(ep, ln["tokens"][i]) for i in _word_tokens(ln)) if lem],
        })
    return items


def _apparier(ep: dict, rng: random.Random, family: str) -> list[dict]:
    gloss = [g for g in ep.get("glossary") or [] if (g.get("pos") or "") != "nom propre" and g.get("translation")
             and fold(g["form"]) != fold(g["translation"])]
    content = [g for g in gloss if (g.get("pos") or "") in _CONTENT_POS] or gloss
    preferred = [g for g in content if not g.get("transparent")]
    if len(preferred) < 4:
        preferred = content
    uniq = list({fold(g["translation"]): g for g in preferred}.values())
    rng.shuffle(uniq)
    pairs = uniq[:6]
    if len(pairs) < 4:
        return []
    return [{
        "prompt": {"pairs": [{"left": g["form"], "id": i} for i, g in enumerate(pairs)],
                   "right": _options(pairs[0]["translation"], [g["translation"] for g in pairs[1:]], rng)},
        "expected": {g["form"]: g["translation"] for g in pairs},
        "lexemes": [g.get("lemma") or g["form"] for g in pairs],
    }]


def _trouver_dans_le_texte(ep: dict, rng: random.Random, family: str) -> list[dict]:
    items = []
    for example in (ep.get("point") or {}).get("examples") or []:
        for li, ln in enumerate(ep["lines"]):
            span = find_token_span(ln["tokens"], example)
            if not span and family == "arabe":
                bare = arabic.strip_harakat(example)
                span = [i for i in _word_tokens(ln) if arabic.strip_harakat(ln["tokens"][i]["text"]) in bare.split()]
            if span:
                items.append({"prompt": {"line": li, "example": example}, "expected": sorted(span), "lexemes": []})
                break
    return items[:ITEMS_PER_GAME]


def _bonne_forme(ep: dict, rng: random.Random, family: str) -> list[dict]:
    items = []
    for v in (ep.get("point") or {}).get("variants") or []:
        for li, ln in enumerate(ep["lines"]):
            if v["example"] in ln["text"]:
                items.append({
                    "prompt": {"line": li, "sentence": ln["text"].replace(v["example"], "___", 1),
                               "translation": ln["translation"]},
                    "options": _options(v["example"], v["distractors"][:3], rng),
                    "expected": v["example"], "lexemes": [],
                })
                break
    return items[:ITEMS_PER_GAME]


def _han_words(ep: dict) -> list[tuple[dict, dict]]:
    """(entrée de glossaire, pinyin) des mots chinois du glossaire."""
    from services.lang_mandarin import token_pinyin

    out = []
    for g in ep.get("glossary") or []:
        py = token_pinyin(g["form"])
        if py and py["syllables"]:
            out.append((g, py))
    return out


def _caractere_sens(ep: dict, rng: random.Random, family: str) -> list[dict]:
    words = _han_words(ep)
    rng.shuffle(words)
    items = []
    translations = [g["translation"] for g, _ in words]
    for g, _py in words[:ITEMS_PER_GAME]:
        others = _distinct(translations, rng, 3, g["translation"])
        if len(others) < 2:
            continue
        items.append({
            "prompt": {"hanzi": g["form"]}, "options": _options(g["translation"], others, rng),
            "expected": g["translation"], "lexemes": [g.get("lemma") or g["form"]],
            "units": [[HANZI_SCRIPT, c] for c in g["form"] if "一" <= c <= "鿿"],
        })
    return items


def _caractere_pinyin(ep: dict, rng: random.Random, family: str) -> list[dict]:
    words = _han_words(ep)
    rng.shuffle(words)
    items = []
    readings = [" ".join(s["mark"] for s in py["syllables"]) for _, py in words]
    for g, py in words[:ITEMS_PER_GAME]:
        answer = " ".join(s["mark"] for s in py["syllables"])
        others = _distinct(readings, rng, 3, answer)
        if len(others) < 2:
            continue
        items.append({
            "prompt": {"hanzi": g["form"]}, "options": _options(answer, others, rng), "expected": answer,
            "lexemes": [g.get("lemma") or g["form"]],
            "units": [[HANZI_SCRIPT, s["hanzi"]] for s in py["syllables"]],
        })
    return items


def _ton_du_caractere(ep: dict, rng: random.Random, family: str) -> list[dict]:
    syllables = [s for _, py in _han_words(ep) for s in py["syllables"] if s["tone"] in (1, 2, 3, 4)]
    uniq = list({s["hanzi"]: s for s in syllables}.values())
    rng.shuffle(uniq)
    return [{
        "prompt": {"hanzi": s["hanzi"], "bare": s["num"][:-1].replace("v", "ü")},
        "options": ["1", "2", "3", "4", "5"], "expected": str(s["tone"]), "lexemes": [],
        "units": [[TONES_SCRIPT, f"zh.t.{s['tone']}"], [HANZI_SCRIPT, s["hanzi"]]],
    } for s in uniq[:ITEMS_PER_GAME]]


def _arabic_words(ep: dict) -> list[str]:
    return [ln["tokens"][i]["text"] for ln in ep["lines"] for i in _word_tokens(ln)]


def _lettre_forme(ep: dict, rng: random.Random, family: str) -> list[dict]:
    from services.lang_static import script_registry

    letters = {letter["char"]: letter for letter in script_registry("arabic").get("letters") or []}
    candidates = []
    for word in _arabic_words(ep):
        for i, ch in enumerate(arabic.letters_of(word)):
            if ch in letters:
                candidates.append((word, i, ch))
    rng.shuffle(candidates)
    items, used = [], set()
    for word, i, ch in candidates:
        position = arabic.contextual_form(word, i)
        if ch in used or position == "isolated":
            continue
        used.add(ch)
        forms = letters[ch]["forms"]
        items.append({
            "prompt": {"word": arabic.strip_harakat(word), "letter": ch, "position": position},
            "options": [forms[f] for f in _FORMS], "expected": forms[position], "lexemes": [],
            "units": [[ARABIC_SCRIPT, letters[ch]["id"]]],
        })
        if len(items) >= ITEMS_PER_GAME:
            break
    return items


def _lire_vocalise(ep: dict, rng: random.Random, family: str) -> list[dict]:
    words = list(dict.fromkeys(w for w in _arabic_words(ep) if len(arabic.letters_of(w)) >= 2))
    rng.shuffle(words)
    translits = [arabic.transliterate_word(w) for w in words]
    items = []
    for w in words[:ITEMS_PER_GAME]:
        answer = arabic.transliterate_word(w)
        others = _distinct(translits, rng, 3, answer)
        if len(others) < 2:
            continue
        items.append({
            "prompt": {"word": w}, "options": _options(answer, others, rng), "expected": answer, "lexemes": [],
            "units": [list(u) for u in script_units_of_token("arabe", w)],
        })
    return items


def _retrouver_la_lettre(ep: dict, rng: random.Random, family: str) -> list[dict]:
    from services.lang_scripts import _arabic_char_units

    units = _arabic_char_units()
    lines = list(enumerate(ep["lines"]))
    rng.shuffle(lines)
    items = []
    for li, ln in lines:
        letters = [ch for i in _word_tokens(ln) for ch in arabic.letters_of(ln["tokens"][i]["text"]) if ch in units]
        if not letters:
            continue
        letter = rng.choice(letters)
        expected = [i for i in _word_tokens(ln) if letter in arabic.letters_of(ln["tokens"][i]["text"])]
        items.append({"prompt": {"line": li, "letter": letter}, "expected": expected, "lexemes": [],
                      "units": [[ARABIC_SCRIPT, units[letter]]]})
        if len(items) >= 3:
            break
    return items


_BUILDERS = {
    "completer_replique": _completer_replique, "qui_a_dit": _qui_a_dit,
    "remettre_en_ordre": _remettre_en_ordre, "apparier": _apparier,
    "trouver_dans_le_texte": _trouver_dans_le_texte, "bonne_forme": _bonne_forme,
    "caractere_sens": _caractere_sens, "caractere_pinyin": _caractere_pinyin,
    "ton_du_caractere": _ton_du_caractere, "lettre_forme": _lettre_forme,
    "lire_vocalise": _lire_vocalise, "retrouver_la_lettre": _retrouver_la_lettre,
}


def build_game(kind: str, episode: dict, family: str, seed: int, prefix: str) -> dict | None:
    items = _BUILDERS[kind](episode, random.Random(seed), family)
    if not items:
        return None
    for i, it in enumerate(items):
        it["ref"] = f"{prefix}.{kind}.{i}"
        it["kind"] = kind
        it["episode_id"] = episode.get("id")
    return {"kind": kind, "ease": GAMES[kind]["ease"], "items": items}


def choose_games(episode: dict, family: str, seed: int, recent_kinds: list[list[str]],
                 exclude: tuple[str, ...] = POINT_KINDS) -> list[dict]:
    """R6 + R22 : deux jeux, jamais ceux des LANG_GAMES_AVOID_LAST_RUNS séances
    précédentes quand c'est possible, le dernier toujours parmi les plus faciles.
    Les formes déjà jouées au point du jour (`exclude`) n'y reviennent pas."""
    avoid = {k for kinds in recent_kinds[:LANG_GAMES_AVOID_LAST_RUNS] for k in kinds}
    rng = random.Random(seed)
    catalogue = [k for k, meta in GAMES.items() if family in meta["families"] and k not in exclude]
    built = {}
    for kind in catalogue:
        game = build_game(kind, episode, family, seed + len(built) * 7919, prefix="jeux")
        if game:
            built[kind] = game
    if not built:
        return []
    fresh = [k for k in built if k not in avoid] or list(built)
    easiest = min(GAMES[k]["ease"] for k in built)
    easy = [k for k in fresh if GAMES[k]["ease"] == easiest] or [k for k in built if GAMES[k]["ease"] == easiest]
    last = rng.choice(sorted(easy))
    first_pool = [k for k in fresh if k != last and GAMES[k]["ease"] >= GAMES[last]["ease"]] or \
                 [k for k in built if k != last]
    chosen = [rng.choice(sorted(first_pool))] if first_pool and LANG_GAMES_PER_RUN > 1 else []
    return [built[k] for k in chosen] + [built[last]]


def point_micro_items(episode: dict, family: str, seed: int) -> list[dict]:
    """R5 / G14 : trois micro-manipulations autour du point du jour — repérer une
    forme dans le texte, puis choisir la bonne forme ; complétées par une
    réplique à trous si le point manque d'exemples."""
    rng = random.Random(seed)
    items: list[dict] = []
    for kind in ("trouver_dans_le_texte", "bonne_forme", "completer_replique"):
        game = build_game(kind, episode, family, rng.randint(0, 10**6), prefix="point")
        if not game:
            continue
        take = 1 if kind == "trouver_dans_le_texte" else LANG_POINT_MICRO_ITEMS - len(items)
        items += game["items"][:max(0, take)]
        if len(items) >= LANG_POINT_MICRO_ITEMS:
            break
    return items[:LANG_POINT_MICRO_ITEMS]


# ── Correction (R23) ──────────────────────────────────────────────────────────

def _same(a, b) -> bool:
    """Égalité stricte à la casse près : les accents COMPTENT (« esta » n'est
    pas « está », et c'est exactement ce que `bonne_forme` fait travailler)."""
    norm = lambda x: unicodedata.normalize("NFC", str(x)).strip().casefold()  # noqa: E731
    return norm(a) == norm(b)


def grade(item: dict, given) -> bool | None:
    """Corrigé déterministe ; `None` si rien n'a été répondu (jamais 1.0)."""
    if given is None or given == "" or given == [] or given == {}:
        return None
    expected = item.get("expected")
    kind = item.get("kind")
    if kind == "apparier":
        if not isinstance(given, dict):
            return False
        return all(_same(given.get(k, ""), v) for k, v in expected.items())
    if kind in ("trouver_dans_le_texte", "retrouver_la_lettre"):
        try:
            return sorted(int(x) for x in given) == sorted(int(x) for x in expected)
        except (TypeError, ValueError):
            return False
    if kind == "remettre_en_ordre":
        if not isinstance(given, list) or len(given) != len(expected):
            return False
        return all(_same(a, b) for a, b in zip(given, expected))
    return _same(given, expected)
