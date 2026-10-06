# tests/lang_fakes.py — Faux Clikoda pour le module langues (méthode feuilleton).
#
# Les fonctions `*_async` du feuilleton sont remplacées par des fakes à la même
# signature (params, ok, err, on_metrics=None) qui renvoient une sortie VALIDE
# construite depuis les paramètres du prompt : bornes du palier, personnages de
# la bible, point du jour. Aucun Ollama n'est requis ; les validateurs et les
# calculs déterministes tournent pour de vrai sur ces sorties.
from __future__ import annotations

import re

SPANISH_LINES = [
    ("Lucía", "Hola, Pablo. ¿Qué tal estás hoy?", "Salut, Pablo. Comment vas-tu aujourd'hui ?"),
    ("Pablo", "Estoy bien, pero llego tarde otra vez.", "Je vais bien, mais j'arrive encore en retard."),
    ("Lucía", "¿Quieres un café con leche?", "Tu veux un café au lait ?"),
    ("Pablo", "Sí, por favor. Un café grande.", "Oui, s'il te plaît. Un grand café."),
    ("Carmen", "Buenos días. ¿Hay pan fresco?", "Bonjour. Il y a du pain frais ?"),
    ("Lucía", "Sí, el pan está en la mesa.", "Oui, le pain est sur la table."),
    ("Carmen", "Gracias, Lucía. Eres muy amable.", "Merci, Lucía. Tu es très aimable."),
    ("Pablo", "Carmen siempre sabe todo del barrio.", "Carmen sait toujours tout du quartier."),
    ("Carmen", "Claro, hablo con todo el mundo.", "Bien sûr, je parle avec tout le monde."),
    ("Lucía", "Hoy la plaza está muy tranquila.", "Aujourd'hui la place est très calme."),
    ("Pablo", "Mañana hay una fiesta en la plaza.", "Demain il y a une fête sur la place."),
    ("Carmen", "¿Una fiesta? ¡Nadie me dice nada!", "Une fête ? Personne ne me dit rien !"),
]
# Les mêmes répliques pour un profil dont la langue d'explication est l'anglais.
ENGLISH_TRANSLATIONS = [
    "Hi, Pablo. How are you today?", "I'm fine, but I'm late again.", "Do you want a white coffee?",
    "Yes, please. A large coffee.", "Good morning. Is there fresh bread?", "Yes, the bread is on the table.",
    "Thanks, Lucía. You're very kind.", "Carmen always knows everything about the neighbourhood.",
    "Of course, I talk to everybody.", "Today the square is very quiet.", "Tomorrow there's a party in the square.",
    "A party? Nobody tells me anything!",
]

GLOSSARY = {
    "hola": ("hola", "salut", "interjection", ""), "qué": ("qué", "quoi", "pronom", ""),
    "tal": ("tal", "tel", "adverbe", ""), "estás": ("estar", "être", "verbe", ""),
    "hoy": ("hoy", "aujourd'hui", "adverbe", ""), "estoy": ("estar", "être", "verbe", ""),
    "bien": ("bien", "bien", "adverbe", ""), "pero": ("pero", "mais", "conjonction", ""),
    "llego": ("llegar", "arriver", "verbe", ""), "tarde": ("tarde", "tard", "adverbe", ""),
    "otra": ("otro", "autre", "adjectif", ""), "vez": ("vez", "fois", "nom", "f"),
    "quieres": ("querer", "vouloir", "verbe", ""), "un": ("un", "un", "déterminant", ""),
    "café": ("café", "café", "nom", "m"), "con": ("con", "avec", "préposition", ""),
    "leche": ("leche", "lait", "nom", "f"), "sí": ("sí", "oui", "adverbe", ""),
    "por": ("por", "par", "préposition", ""), "favor": ("favor", "faveur", "nom", "m"),
    "grande": ("grande", "grand", "adjectif", ""), "buenos": ("bueno", "bon", "adjectif", ""),
    "días": ("día", "jour", "nom", "m"), "hay": ("haber", "il y a", "verbe", ""),
    "pan": ("pan", "pain", "nom", "m"), "fresco": ("fresco", "frais", "adjectif", ""),
    "el": ("el", "le", "déterminant", ""), "está": ("estar", "être", "verbe", ""),
    "en": ("en", "dans", "préposition", ""), "la": ("la", "la", "déterminant", ""),
    "mesa": ("mesa", "table", "nom", "f"), "gracias": ("gracias", "merci", "interjection", ""),
    "eres": ("ser", "être", "verbe", ""), "muy": ("muy", "très", "adverbe", ""),
    "amable": ("amable", "aimable", "adjectif", ""), "siempre": ("siempre", "toujours", "adverbe", ""),
    "sabe": ("saber", "savoir", "verbe", ""), "todo": ("todo", "tout", "pronom", ""),
    "del": ("del", "du", "préposition", ""), "barrio": ("barrio", "quartier", "nom", "m"),
    "claro": ("claro", "bien sûr", "adverbe", ""), "hablo": ("hablar", "parler", "verbe", ""),
    "mundo": ("mundo", "monde", "nom", "m"), "plaza": ("plaza", "place", "nom", "f"),
    "tranquila": ("tranquilo", "calme", "adjectif", ""), "mañana": ("mañana", "demain", "adverbe", ""),
    "una": ("una", "une", "déterminant", ""), "fiesta": ("fiesta", "fête", "nom", "f"),
    "nadie": ("nadie", "personne", "pronom", ""), "me": ("me", "me", "pronom", ""),
    "dice": ("decir", "dire", "verbe", ""), "nada": ("nada", "rien", "pronom", ""),
}

ENGLISH_GLOSSES = {
    "hola": "hello", "qué": "what", "tal": "such", "estás": "to be", "hoy": "today", "estoy": "to be",
    "bien": "well", "pero": "but", "llego": "to arrive", "tarde": "late", "otra": "other", "vez": "time",
    "quieres": "to want", "un": "a", "café": "coffee", "con": "with", "leche": "milk", "sí": "yes",
    "por": "for", "favor": "favour", "grande": "big", "buenos": "good", "días": "day", "hay": "there is",
    "pan": "bread", "fresco": "fresh", "el": "the", "está": "to be", "en": "in", "la": "the", "mesa": "table",
    "gracias": "thanks", "eres": "to be", "muy": "very", "amable": "kind", "siempre": "always",
    "sabe": "to know", "todo": "everything", "del": "of the", "barrio": "neighbourhood", "claro": "of course",
    "hablo": "to speak", "mundo": "world", "plaza": "square", "tranquila": "quiet", "mañana": "tomorrow",
    "una": "a", "fiesta": "party", "nadie": "nobody", "me": "me", "dice": "to say", "nada": "nothing",
}

CALLS: list[str] = []
PROMPTS: list[dict] = []
_WORDS = [
    "parapluie", "horloge", "violon", "tempête", "boussole", "girafe", "bibliothèque", "lanterne",
    "marathon", "citrouille", "télescope", "carnaval", "pingouin", "volcan", "trompette", "éventail",
    "aquarium", "dinosaure", "papillon", "grenier", "moustache", "cerf-volant", "fromagerie", "cathédrale",
    "sous-marin", "feu d'artifice", "perroquet", "labyrinthe", "chocolatier", "montgolfière", "hérisson",
]


def _en(params) -> bool:
    return params.get("explain_lang") == "en"


def _count(params) -> int:
    m = re.search(r"(?:entre|between) (\d+) (?:et|and) (\d+) (?:répliques|lines)", params.get("constraints", ""))
    lo, hi = (int(m.group(1)), int(m.group(2))) if m else (6, 8)
    return max(lo, min(hi, len(SPANISH_LINES)))


def fake_bible(params, ok, err, on_metrics=None, model=None):
    CALLS.append("bible")
    PROMPTS.append({**params, "task": "bible"})
    err("Ollama indisponible (tests)")  # la bible par défaut de la langue prend le relais


def fake_arc(params, ok, err, on_metrics=None, model=None):
    CALLS.append("arc")
    PROMPTS.append({**params, "task": "arc"})
    if _en(params):
        ok({"beats": [{"n": i + 1, "beat": f"Beat {i + 1}: {p['title']}", "hook": "More tomorrow."}
                      for i, p in enumerate(params["points"])]})
        return
    ok({"beats": [{"n": i + 1, "beat": f"Temps fort {i + 1} : {p['title']}", "hook": "La suite demain."}
                  for i, p in enumerate(params["points"])]})


def fake_text(params, ok, err, on_metrics=None, model=None):
    CALLS.append("text")
    PROMPTS.append({**params, "task": "text"})
    n = params["episode_n"]
    lines = [{"speaker": s, "text": t, "translation": ENGLISH_TRANSLATIONS[i] if _en(params) else tr}
             for i, (s, t, tr) in enumerate(SPANISH_LINES[:_count(params)])]
    if on_metrics:
        on_metrics([{"task": "lang_episode_text", "wall_s": 1.0, "prompt_tokens": 900, "output_tokens": 400}])
    a, b, c = (_WORDS[(n * k) % len(_WORDS)] for k in (1, 7, 13))
    if _en(params):
        ok({"title": f"The {a} and the {b}", "lines": lines,
            "summary": f"A {a}, a {b} and then a {c}: episode {n}.", "teaser": "Tomorrow, a surprise awaits Pablo."})
        return
    ok({
        "title": f"{a.capitalize()} et {b}",
        "lines": lines,
        # Un résumé propre à chaque épisode : G9 refuse les redites.
        "summary": f"{a.capitalize()}, {b} puis {c} : épisode {n}.",
        "teaser": "Demain, une surprise attend Pablo.",
    })


def fake_glossary(params, ok, err, on_metrics=None, model=None):
    """Une entrée par mot demandé (le service fournit la liste), plus une expression ;
    une prononciation par entrée quand le prompt la demande (langues latines)."""
    CALLS.append("glossary")
    PROMPTS.append({**params, "task": "glossary"})
    entries = []
    for word in params["words"]:
        lemma, tr, pos, g = GLOSSARY.get(word.lower(), (word.lower(), f"({word})", "expression", ""))
        if _en(params):
            tr = ENGLISH_GLOSSES.get(word.lower(), f"({word})")
        entries.append([word, lemma, tr, pos, g])
    text = " ".join(t for t, _ in params["lines"])
    please = "please" if _en(params) else "s'il te plaît"
    expressions = [["por favor", "por favor", please, "expression", ""]] if "por favor" in text else []
    fields = ("form", "lemma", "translation", "pos", "gender", "pron")

    def entry(e):
        return dict(zip(fields, [*e, f"ˈ{e[1]}" if params.get("pron") else ""]))

    ok({"entries": [entry(e) for e in entries], "expressions": [entry(e) for e in expressions]})


def fake_notes(params, ok, err, on_metrics=None, model=None):
    CALLS.append("notes")
    PROMPTS.append({**params, "task": "notes"})
    lines = [t for t, _ in params["lines"]]
    if _en(params):
        ok({
            "notes": [
                {"line": 1, "anchor": "Hola", "kind": "usage", "text": "Hola is used to greet people at any time of day."},
                {"line": 2, "anchor": "Estoy bien", "kind": "grammar", "text": "Estar describes a passing state."},
                {"line": 3, "anchor": "café", "kind": "culture", "text": "A café con leche is a morning drink."},
            ],
            "point": {
                "observation": "Which verbs say how someone feels?",
                "explanation": "Estar is used for a passing state: estoy bien, está tranquila.",
                "examples": ["Estoy bien", "está muy tranquila" if any("está muy tranquila" in ln for ln in lines) else "está en la mesa"],
                "variants": [{"example": "Estoy bien", "distractors": ["Soy bien", "Estás bien"]}],
            },
        })
        return
    ok({
        "notes": [
            {"line": 1, "anchor": "Hola", "kind": "usage", "text": "Hola sert à saluer à toute heure."},
            {"line": 2, "anchor": "Estoy bien", "kind": "grammaire", "text": "Estar pour un état passager."},
            {"line": 3, "anchor": "café", "kind": "culture", "text": "Le café con leche se boit le matin."},
        ],
        "point": {
            "observation": "Quels verbes disent comment on va ?",
            "explanation": "On emploie estar pour un état passager : estoy bien, está tranquila.",
            "examples": ["Estoy bien", "está muy tranquila" if any("está muy tranquila" in ln for ln in lines) else "está en la mesa"],
            "variants": [{"example": "Estoy bien", "distractors": ["Soy bien", "Estás bien"]}],
        },
    })


def install(monkeypatch):
    """Remplace les appels Clikoda du feuilleton et joue la génération inline."""
    from llm import ollama_client
    from services import lang_activity, lang_episodes

    CALLS.clear()
    PROMPTS.clear()
    monkeypatch.setattr(lang_episodes, "RUN_IN_BACKGROUND", False)
    monkeypatch.setattr(lang_activity, "RUN_IN_BACKGROUND", False)
    monkeypatch.setattr(ollama_client, "generate_lang_story_bible_async", fake_bible)
    monkeypatch.setattr(ollama_client, "generate_lang_story_arc_async", fake_arc)
    monkeypatch.setattr(ollama_client, "generate_lang_episode_text_async", fake_text)
    monkeypatch.setattr(ollama_client, "generate_lang_episode_glossary_async", fake_glossary)
    monkeypatch.setattr(ollama_client, "generate_lang_episode_notes_point_async", fake_notes)
