# Parcours complet de la méthode « feuilleton » (plan § 10, § 14, § 15 ; V5).
#
# Clikoda est remplacé par tests/lang_fakes.py (sorties valides construites depuis
# les prompts) et la génération est jouée inline : chaque test voit exactement
# ce que verrait l'apprenant, sans Ollama et sans thread.
from datetime import date, timedelta

import pytest

import lang_fakes
from config.settings import LANG_PILOT_LANGUAGES

LANG = "espagnol"


@pytest.fixture
def fake(monkeypatch):
    lang_fakes.install(monkeypatch)
    return lang_fakes


@pytest.fixture
def clock(monkeypatch):
    """Jour d'étude piloté par le test (T1)."""
    from services import lang_activity

    state = {"day": date(2026, 9, 21)}
    monkeypatch.setattr(lang_activity, "study_date", lambda dt=None: state["day"].isoformat())

    def advance(days: int = 1) -> None:
        state["day"] += timedelta(days=days)

    state["advance"] = advance
    return state


def _start(client, mode=None):
    return client.post(f"/api/lang/{LANG}/run/start", json={"mode": mode} if mode else {}).json()


WRITTEN = "Hoy estoy muy bien en la plaza con Carmen y Pablo, y hay una fiesta mañana."


def _play(client, run, *, answers="right", signal="compris", taps=0, translate=(), finish=True, feeling=True,
          write=WRITTEN):
    """Joue une séance : chaque étape est ouverte, jouée, fermée, un lot par étape.
    À la lecture, `taps` mots touchés et les répliques `translate` traduites ;
    à la leçon, ses items comme ceux du texte ; à l'expression, `write` envoyé."""
    rid = run["run_id"]
    ep = run["episodes"].get(str(run.get("episode_id"))) if run.get("episode_id") else None
    for step in run["steps"]:
        events = [{"type": "step", "step": step["key"], "started": True}]
        if step["kind"] == "lecture" and ep:
            words = [(li, ti) for li, ln in enumerate(ep["lines"]) for ti, t in enumerate(ln["tokens"]) if t["w"]]
            for li, ti in words[:taps]:
                events.append({"type": "reveal", "episode_id": ep["id"], "line": li, "token": ti, "pass": "lecture"})
            for li in translate:
                events.append({"type": "line", "episode_id": ep["id"], "line": li, "pass": "lecture"})
        items = [it for g in step.get("games", []) for it in g["items"]] + step.get("items", [])
        if step["kind"] == "lecon":
            items += client.get(f"/api/lang/run/{rid}/lesson").json()["lesson_items"]
        for it in items:
            given = it.get("expected") if answers == "right" else ("__faux__" if answers == "wrong" else None)
            events.append({"type": "answer", "item": it["ref"], "given": given, "ms": 800})
        for line in step.get("lines", []) if step["kind"] == "deuxieme_vague" else []:
            events.append({"type": "rating", "episode_id": step["episode_ref"], "line": line["line"], "rating": "su"})
        if step["kind"] == "expression" and write is not None:
            client.post(f"/api/lang/run/{rid}/writing", json={"text": write})
        events.append({"type": "step", "step": step["key"], "ended": True, "active_s": 60,
                       "signal": signal if step["kind"] == "lecture" else None})
        client.post(f"/api/lang/run/{rid}/events", json={"events": events, "current_step": step["key"]})
    if not finish:
        return None
    body = {"end_reason": "fini"}
    au_revoir = next((s for s in run["steps"] if s["kind"] == "au_revoir"), None)
    if feeling and au_revoir:
        body["feeling"] = au_revoir["feeling"]["options"][1]
    return client.post(f"/api/lang/run/{rid}/complete", json=body).json()


def _onboard(client):
    client.post(f"/api/lang/{LANG}/onboarding", json={"interests": ["cuisine"], "has_studied": False})
    return _play(client, _start(client))  # séance zéro


def _profile():
    from db import lang_episode_db as store
    from db.lang_db import get_or_create_lang_profile

    return store.decode_profile(get_or_create_lang_profile(1, LANG))


def _episode(n):
    from db import lang_episode_db as store

    return store.get_episode_by_n(_profile()["id"], n)


# ── Accueil, onboarding, cohabitation ─────────────────────────────────────────

def test_pilot_language_opens_the_feuilleton_and_others_stay_legacy(client):
    languages = {lang["code"]: lang for lang in client.get("/api/lang/languages").json()}
    # La page ne propose que les langues qui ont un programme : celles du pilote.
    assert set(languages) == set(LANG_PILOT_LANGUAGES)
    assert {lang["flow"] for lang in languages.values()} == {"feuilleton"}
    assert languages["arabe"]["label"] == "Arabe littéraire"
    status = client.get(f"/api/lang/{LANG}/status").json()
    assert status["flow"] == "feuilleton" and status["onboarding_done"] is False
    assert client.get("/api/lang/italien/status").status_code == 404
    # Le flux hérité ne bouge pas (K10).
    assert client.post("/api/lang/lesson/start", json={"language": "italien"}).json()["needs_placement"] is True


def test_beginner_onboarding_writes_episode_one_during_the_zero_run(client, fake, clock):
    assert client.post(f"/api/lang/{LANG}/onboarding", json={"interests": ["cuisine"], "has_studied": False}).json() == {
        "ok": True, "next": "zero"}
    assert _episode(1)["status"] == "ready"
    assert fake.CALLS[:4] == ["bible", "bible", "bible", "arc"]  # bible par défaut, puis arc
    run = _start(client)
    assert run["mode"] == "zero"
    assert [s["kind"] for s in run["steps"]] == ["accueil", "phrases", "au_revoir"]
    assert len(run["steps"][1]["phrases"]) == 10
    done = _play(client, run)
    assert done["ok"] and _profile()["onboarding_done"] == 1


def test_a_second_onboarding_never_resets_the_programme(client, fake, clock):
    _onboard(client)
    _play(client, _start(client))
    order = _profile()["program_order"]
    assert client.post(f"/api/lang/{LANG}/onboarding", json={"interests": ["sport"], "has_studied": False}).json()[
        "next"] == "home"
    assert _profile()["program_order"] == order and _profile()["interests"] == ["sport"]


def test_legacy_profile_switches_and_keeps_its_flashcards(client):
    """K9 : un profil hérité d'une langue du pilote passe au feuilleton ; ses
    cartes de vocabulaire rejoignent le lexique."""
    from services.flashcards import create_lang_vocab_flashcards

    client.post("/api/lang/placement/skip", json={"language": LANG})
    create_lang_vocab_flashcards(LANG, [{"word": "casa", "translation": "maison", "phonetic": "ˈkasa"}])
    status = client.get(f"/api/lang/{LANG}/status").json()
    assert status["words_seen"] == 1
    from db import lang_episode_db as store

    lexeme = store.get_lexeme(_profile()["id"], "casa")
    assert lexeme["translation"] == "maison" and lexeme["card_id"] is not None


# ── Séance « épisode » ────────────────────────────────────────────────────────

def test_an_episode_run_is_assembled_without_any_llm_call(client, fake, clock):
    _onboard(client)
    calls = len(fake.CALLS)
    run = _start(client)
    assert len(fake.CALLS) == calls, "une séance ne doit jamais attendre Clikoda"
    assert run["mode"] == "episode" and run["episode_n"] == 1
    assert run["version"] == 2
    kinds = [s["kind"] for s in run["steps"]]
    assert kinds == ["lecture", "lecon", "expression", "jeux", "au_revoir"]
    assert [s["key"] for s in run["steps"] if s["essential"]] == ["lecture", "expression", "au_revoir"]
    ep = run["episodes"][str(run["episode_id"])]
    assert all("".join(t["text"] for t in ln["tokens"]) for ln in ep["lines"])
    assert any(t.get("g") is not None for ln in ep["lines"] for t in ln["tokens"])
    lecture = run["steps"][0]
    assert lecture["translate_all"] is True and lecture["notes"]  # palier A1 : « Tout traduire » proposé
    lecon = next(s for s in run["steps"] if s["kind"] == "lecon")
    assert lecon["point"]["title"] == "Saluer et se présenter" and len(lecon["items"]) == 3
    assert lecon["lesson"]["rule"] and not lecon["lesson_pending"] and len(lecon["lesson_items"]) == 3
    expression = next(s for s in run["steps"] if s["kind"] == "expression")
    assert expression["task"]["prompt"] and expression["task"]["use_words"]
    assert {k["char"] for g in expression["keyboard"]["groups"] for k in g["keys"]} >= {"ñ", "¿", "á"}
    games = next(s for s in run["steps"] if s["kind"] == "jeux")["games"]
    assert len(games) == 3 and games[-1]["ease"] == min(g["ease"] for g in games)
    assert run["steps"][-1]["essential"] is True


def test_next_episode_is_written_when_the_lesson_step_starts(client, fake, clock):
    _onboard(client)
    run = _start(client)
    rid = run["run_id"]
    client.post(f"/api/lang/run/{rid}/events", json={"events": [
        {"type": "step", "step": "lecture", "ended": True, "active_s": 150, "signal": "compris"},
    ], "current_step": "lecture"})
    assert _episode(2) is None
    client.post(f"/api/lang/run/{rid}/events", json={"events": [{"type": "step", "step": "lecon", "started": True}],
                                                     "current_step": "lecon"})
    assert _episode(2)["status"] == "ready"
    assert _episode(1)["status"] == "played" and _profile()["episode_n"] == 1
    assert _episode(2)["program_point_id"] == "es.a1.ser_identidad"


def test_answers_are_regraded_by_the_service_and_unanswered_is_null(client, fake, clock):
    from db import lang_episode_db as store

    _onboard(client)
    run = _start(client)
    lecon = next(s for s in run["steps"] if s["kind"] == "lecon")
    first, second = lecon["items"][0], lecon["items"][1]
    client.post(f"/api/lang/run/{run['run_id']}/events", json={"events": [
        {"type": "answer", "item": first["ref"], "given": "__faux__"},
        {"type": "answer", "item": second["ref"], "given": None},
        {"type": "answer", "item": "inconnu", "given": "x"},
    ]})
    attempts = {a["item_ref"]: a for a in store.get_attempts(run["run_id"])}
    assert attempts[first["ref"]]["correct"] == 0
    assert attempts[second["ref"]]["correct"] is None  # jamais 1.0
    assert "inconnu" not in attempts


def test_completion_returns_what_was_gained_without_a_score(client, fake, clock):
    _onboard(client)
    done = _play(client, _start(client), taps=3)
    assert done["episode"]["n"] == 1 and done["point"] == "Saluer et se présenter"
    assert done["new_words"] and done["cards_created"] >= 3 and "score" not in done
    from db import get_connection

    card = get_connection().execute("SELECT front, back, source FROM flashcards LIMIT 1").fetchone()
    assert card["source"] == "lang_feuilleton"


def test_every_feuilleton_card_carries_its_pronunciation_on_the_front(client, fake, clock):
    """Langue latine : la prononciation vient du glossaire de Clikoda (rien ne la
    calcule) ; elle accompagne le recto, écrit dans la langue apprise."""
    _onboard(client)
    _play(client, _start(client), taps=3)
    assert all(p["pron"] for p in fake.PROMPTS if p["task"] == "glossary")
    cards = client.get("/api/flashcards").json()
    assert cards and all(c["pronunciation"] and c["pronunciation_side"] == "front" for c in cards)


def test_a_word_without_pronunciation_gets_no_card(client):
    """Pas de carte de langue sans prononciation : le mot cède sa place. Un nom
    allemand dit aussi son article, écrit sur le recto."""
    from db import get_connection
    from db import lang_episode_db as store
    from db.lang_db import get_or_create_lang_profile
    from services.lang_progress import create_episode_flashcards

    profile = {**get_or_create_lang_profile(1, "allemand"), "user_id": 1}
    glossary = [
        {"form": "Hund", "lemma": "Hund", "translation": "chien", "pos": "nom", "gender": "m",
         "article": "der", "pron": "hʊnt", "new": True},
        {"form": "schnell", "lemma": "schnell", "translation": "vite", "pos": "adverbe", "pron": None, "new": True},
    ]
    for entry in glossary:
        store.insert_lexeme(profile["id"], entry, 1)
    assert create_episode_flashcards(profile, "allemand", {"glossary": glossary}, set()) == 1
    rows = get_connection().execute("SELECT front, pronunciation FROM flashcards").fetchall()
    assert [(r["front"], r["pronunciation"]) for r in rows] == [("der Hund", "deːɐ̯ hʊnt")]


def test_a_known_word_receives_the_pronunciation_it_lacked(client):
    from db import lang_episode_db as store
    from db.lang_db import get_or_create_lang_profile

    pid = get_or_create_lang_profile(1, LANG)["id"]
    entry = {"form": "casa", "lemma": "casa", "translation": "maison"}
    lex_id = store.insert_lexeme(pid, entry, 1)
    assert store.insert_lexeme(pid, {**entry, "translation": "autre", "pron": "ˈkasa"}, 2) == lex_id
    store.insert_lexeme(pid, {**entry, "pron": "autre"}, 3)
    row = store.get_lexeme(pid, "casa")
    assert (row["pron"], row["translation"], row["first_episode_n"]) == ("ˈkasa", "maison", 1)


def test_feeling_answer_joins_the_metacognitive_profile(client, fake, clock, monkeypatch):
    """R8 : la réponse est gardée sur la séance et transmise au profil commun,
    avec la séance de pratique dont les jeux et le « compris » ont fait la
    courbe de jauges. Le ressenti, choix parmi trois, n'est pas noté."""
    from services import session

    calls = []
    monkeypatch.setattr(session, "nudge_metacog_profile", lambda *a, **k: calls.append((a, k)))
    _onboard(client)
    run = _start(client)
    _play(client, run)
    stored = client.get(f"/api/lang/run/{run['run_id']}").json()
    assert stored["status"] == "completed"
    args, kwargs = calls[-1]
    assert kwargs["session_id"] is None and kwargs["practice_session_id"] is not None
    assert kwargs["measures"] > 0 and kwargs["measure_meta"] is False
    assert kwargs["questions"][0].endswith("?") or kwargs["questions"][0].endswith("…")
    assert args[2][0] in ("Juste bien", "Un peu", "Le point du jour", "Pareil", "Moyenne", "En cours")


def test_words_are_acquired_after_recognitions_across_episodes(client, fake, clock):
    _onboard(client)
    for _ in range(3):
        _play(client, _start(client))
        clock["advance"]()
    status = client.get(f"/api/lang/{LANG}/status").json()
    assert status["words_acquired"] > 0 and status["episodes_played"] == 3


def test_hard_reading_triggers_a_respiration_episode(client, fake, clock):
    _onboard(client)
    _play(client, _start(client), taps=20, signal="pas_compris")
    ep2 = _episode(2)
    assert ep2["kind"] == "respiration" and ep2["program_point_id"] == _episode(1)["program_point_id"]
    assert "RESPIRATION" in " ".join(ep2["params"].get("verdict", "") for _ in [0]) or ep2["params"]["verdict"] == "hard"


# ── Repli, reprise, bilan, jalons ─────────────────────────────────────────────

def test_episode_not_ready_falls_back_to_relecture_and_retries(client, fake, clock, monkeypatch):
    from llm import ollama_client

    _onboard(client)
    monkeypatch.setattr(ollama_client, "generate_lang_episode_text_async",
                        lambda params, ok, err, on_metrics=None, model=None: err("panne"))
    _play(client, _start(client))
    assert _episode(2)["status"] == "failed"
    clock["advance"]()
    run = _start(client)
    assert run["mode"] == "relecture" and run["steps"][0]["kind"] == "relecture"
    monkeypatch.setattr(ollama_client, "generate_lang_episode_text_async", fake.fake_text)
    _play(client, run)
    clock["advance"]()
    _start(client)  # la séance suivante retente la génération
    assert _episode(2)["status"] == "ready"


def test_bilan_comes_after_six_episodes_and_consolidates_them(client, fake, clock):
    from db import lang_episode_db as store

    _onboard(client)
    for _ in range(6):
        _play(client, _start(client))
        clock["advance"]()
    assert _episode(7) is None  # l'épisode 7 attend l'arc que le bilan écrit
    run = _start(client)
    assert run["mode"] == "bilan"
    recap = next(s for s in run["steps"] if s["kind"] == "recap")
    assert len(recap["points"]) == 6
    assert _episode(7)["status"] == "ready" and store.get_arc(_profile()["id"], 2)
    _play(client, run)
    progress = store.get_program_progress(_profile()["id"])
    assert sum(1 for p in progress.values() if p["status"] == "consolide") == 6
    clock["advance"]()
    assert _start(client)["mode"] == "episode"


def test_long_absence_rereads_first_and_keeps_the_ready_episode(client, fake, clock):
    """C7 : la reprise ne jette plus l'épisode prêt. Il attend la séance qui
    suit la relecture — le même jour —, et la respiration va à celui d'après."""
    _onboard(client)
    _play(client, _start(client))
    kept = _episode(2)
    assert kept["status"] == "ready" and kept["kind"] == "normal"
    clock["advance"](10)
    run = _start(client)
    assert run["mode"] == "reprise" and run["absence"]["tier"] == "reprise"
    assert [s["kind"] for s in run["steps"]][:3] == ["accueil", "recap", "relecture"]
    assert not any(s["kind"] == "lecture" for s in run["steps"])
    assert run["steps"][0]["kept_episode"] == 2
    ep2 = _episode(2)
    assert (ep2["id"], ep2["status"], ep2["kind"], ep2["title"]) == (kept["id"], "ready", "normal", kept["title"])
    _play(client, run)
    run = _start(client)
    assert run["mode"] == "episode" and run["episode_n"] == 2
    _play(client, run)
    assert _episode(3)["kind"] == "respiration" and _profile()["force_respiration"] == 0


def test_three_weeks_away_adds_a_control_step(client, fake, clock):
    _onboard(client)
    _play(client, _start(client))
    clock["advance"](25)
    run = _start(client)
    assert any(s["kind"] == "controle" for s in run["steps"])


def test_three_days_away_still_plays_the_ready_episode(client, fake, clock):
    _onboard(client)
    _play(client, _start(client))
    clock["advance"](3)
    assert client.get(f"/api/lang/{LANG}/status").json()["relecture_due"] is False
    run = _start(client)
    assert run["mode"] == "episode" and run["episode_n"] == 2 and run["absence"]["tier"] == "normal"


def test_four_days_away_impose_a_relecture_and_keep_the_episode(client, fake, clock):
    """Au-delà de 3 jours : relecture imposée, sans nouvel épisode — même une
    séance courte demandée —, sans respiration avant le palier `reprise`."""
    _onboard(client)
    _play(client, _start(client))
    clock["advance"]()
    _play(client, _start(client))
    kept = _episode(3)
    clock["advance"](4)
    status = client.get(f"/api/lang/{LANG}/status").json()
    assert status["relecture_due"] is True and status["next_status"] == "ready"
    run = _start(client, "court")
    assert run["mode"] == "reprise" and run["absence"]["tier"] == "rappel_long"
    assert [s["kind"] for s in run["steps"]][:3] == ["accueil", "recap", "relecture"]
    assert not any(s["kind"] == "lecture" for s in run["steps"])
    assert _episode(3)["id"] == kept["id"] and _episode(3)["status"] == "ready"
    assert _profile()["force_respiration"] == 0
    _play(client, run)
    assert client.get(f"/api/lang/{LANG}/status").json()["relecture_due"] is False
    run = _start(client)
    assert run["mode"] == "episode" and run["episode_n"] == 3


def test_milestone_and_second_wave(client, fake, clock):
    """R7 et R12 sur un historique fabriqué : l'épisode 50 déclenche la
    deuxième vague (épisode 1) et un jalon (relire l'épisode 1)."""
    from db import lang_episode_db as store
    from services import lang_runs

    _onboard(client)
    _play(client, _start(client), taps=4)
    profile = _profile()
    first = _episode(1)
    for n in range(2, 51):
        eid = store.create_episode(profile["id"], n, kind="normal", program_point_id=first["program_point_id"],
                                   format="dialogue", ladder_step=0, params=first["params"])
        store.update_episode(eid, status="played" if n < 50 else "ready", lines=first["lines"],
                             glossary=first["glossary"], notes=first["notes"], point=first["point"],
                             aids=first["aids"], title=f"Épisode {n}", summary=f"Résumé {n}", teaser="…")
    store.update_profile_fields(profile["id"], episode_n=49, last_bilan_episode_n=48)
    run = lang_runs.start_run(LANG)
    kinds = [s["kind"] for s in run["steps"]]
    assert "deuxieme_vague" in kinds and "jalon" in kinds
    wave = next(s for s in run["steps"] if s["kind"] == "deuxieme_vague")
    assert wave["episode_ref"] == first["id"] and 3 <= len(wave["lines"]) <= 6 and wave["lines"][0]["typing"]
    jalon = next(s for s in run["steps"] if s["kind"] == "jalon")
    assert jalon["first_taps"] == 4


# ── Cycle de vie d'une séance ─────────────────────────────────────────────────

def test_same_day_run_is_resumed_and_older_ones_abandoned(client, fake, clock):
    _onboard(client)
    run = _start(client)
    client.post(f"/api/lang/run/{run['run_id']}/events", json={"events": [], "current_step": "lecon"})
    again = _start(client)
    assert again["run_id"] == run["run_id"] and again["resumed"] and again["current_step"] == "lecon"
    clock["advance"]()
    fresh = _start(client)
    assert fresh["run_id"] != run["run_id"]
    assert client.get(f"/api/lang/run/{run['run_id']}").json()["status"] == "abandoned"


def test_duration_cap_skips_to_the_next_essential_step(client, fake, clock):
    """R24 : au plafond, les étapes non essentielles sautent ; l'expression écrite
    et l'au revoir sont toujours joués, dans cet ordre."""
    from config.settings import LANG_RUN_MAX_S

    _onboard(client)
    run = _start(client)
    events = f"/api/lang/run/{run['run_id']}/events"
    res = client.post(events, json={"events": [
        {"type": "step", "step": "lecture", "ended": True, "active_s": LANG_RUN_MAX_S + 100}]}).json()
    assert res["cap_reached"] and res["skip_to"] == "expression"
    res = client.post(events, json={"events": [{"type": "step", "step": "expression", "ended": True}]}).json()
    assert res["skip_to"] == "au_revoir"


def test_short_and_reread_modes_on_request(client, fake, clock):
    _onboard(client)
    court = _start(client, "court")
    assert court["mode"] == "court"
    assert [s["kind"] for s in court["steps"]] == ["rappel", "lecture", "lecon", "au_revoir"]
    assert court["steps"][2]["compact"] is True and court["pregen_step"] == "lecon"
    _play(client, court)
    clock["advance"]()
    relecture = _start(client, "relecture")
    assert relecture["mode"] == "relecture" and relecture["steps"][0]["kind"] == "relecture"


def test_placement_sets_the_starting_point(client, fake, clock):
    items = client.get(f"/api/lang/{LANG}/placement").json()["items"]
    from db import lang_episode_db as store

    keys = {it["id"]: it["answer"] for it in store.get_placement_items(LANG)}
    answers = {it["id"]: keys[it["id"]] for it in items[:9]}  # A1 et A2 réussis
    res = client.post(f"/api/lang/{LANG}/placement/submit", json={"answers": answers}).json()
    assert res["level"] == "A2" and res["start_order"] > 48
    status = client.get(f"/api/lang/{LANG}/status").json()
    assert status["onboarding_done"] and status["next_status"] == "ready"
    run = _start(client)
    assert run["mode"] == "episode"
    ep1 = _episode(1)
    assert store.get_point(LANG, ep1["program_point_id"])["order"] == res["start_order"]


def test_library_episode_view_report_and_compare(client, fake, clock):
    _onboard(client)
    _play(client, _start(client))
    library = client.get(f"/api/lang/{LANG}/library").json()
    assert [e["n"] for e in library] == [1]
    view = client.get(f"/api/lang/episode/{library[0]['id']}").json()
    assert view["lines"] and view["notes"] and view["point"]["title"]
    assert client.get(f"/api/lang/episode/{_episode(2)['id']}").status_code == 404  # pas encore joué
    res = client.post("/api/lang/report", json={"episode_id": library[0]["id"], "line": 0, "token": 0,
                                                 "kind": "traduction", "comment": "faux"}).json()
    assert res["ok"]
    view = client.get(f"/api/lang/episode/{library[0]['id']}").json()
    assert view["lines"][0]["tokens"][0].get("reported") is True
    diff = client.post("/api/lang/compare", json={"original": "Estoy muy bien.", "typed": "estoy bien"}).json()
    assert {"op": "missing", "text": "muy"} in diff["ops"]


def _add_cards(n, *, due, prefix, language=LANG):
    """`n` cartes de la langue, déjà dues (hier) ou à revoir dans dix jours."""
    from db import get_connection

    when = "datetime('now', '-1 day')" if due else "datetime('now', '+10 days')"
    conn = get_connection()
    with conn:
        for i in range(n):
            conn.execute("INSERT INTO flashcards (user_id, front, back, language, source, dedup_key, due_at) "
                         f"VALUES (1, ?, 'x', ?, 'lang_feuilleton', ?, {when})",
                         (f"{prefix}{i}", language, f"{prefix}{i}"))


def _warmup_fronts(client):
    return [c["front"] for c in client.get("/api/lang/warmup-cards", params={"language": LANG}).json()]


def test_warmup_cards_are_capped_due_first_and_of_the_language(client, fake, clock):
    from config.settings import WARMUP_MAX_CARDS

    _onboard(client)
    _add_cards(WARMUP_MAX_CARDS + 3, due=True, prefix="du")
    _add_cards(3, due=False, prefix="nv")  # plus récentes, mais pas dues
    _add_cards(3, due=True, prefix="it", language="italien")
    assert _warmup_fronts(client) == [f"du{i}" for i in range(WARMUP_MAX_CARDS)]


def test_warmup_cards_fall_back_on_recent_cards(client, fake, clock):
    """Peu de cartes dues : les plus récentes complètent, pour qu'il y ait un warm-up."""
    from config.settings import WARMUP_MAX_CARDS

    _onboard(client)
    _add_cards(2, due=True, prefix="du")
    _add_cards(WARMUP_MAX_CARDS, due=False, prefix="nv")
    fronts = _warmup_fronts(client)
    assert len(fronts) == WARMUP_MAX_CARDS == len(set(fronts))
    assert fronts[:2] == ["du0", "du1"] and all(f.startswith("nv") for f in fronts[2:])


def test_warmup_skips_the_cards_of_todays_open_run(client, fake, clock):
    """Reprise d'une séance du jour : son étape `cartes` les révisera, pas le sas."""
    _onboard(client)
    _add_cards(4, due=True, prefix="du")
    _add_cards(2, due=False, prefix="nv")
    run = _start(client, "relecture")
    planned = {c["front"] for s in run["steps"] for c in s.get("cards") or []}
    assert planned == {f"du{i}" for i in range(4)}
    assert sorted(_warmup_fronts(client)) == ["nv0", "nv1"]


def test_warmup_cards_count_against_the_run_cap(client, fake, clock):
    """P13 : le plafond de cartes vaut pour la séance entière, sas d'entrée compris
    (le compte envoyé par le client est borné à WARMUP_MAX_CARDS)."""
    from config.settings import LANG_DUE_CARDS_CAP, WARMUP_MAX_CARDS

    _onboard(client)
    _add_cards(LANG_DUE_CARDS_CAP + 5, due=True, prefix="du")
    run = client.post(f"/api/lang/{LANG}/run/start", json={"mode": "relecture", "warmup": 99}).json()
    cartes = next(s for s in run["steps"] if s["kind"] == "cartes")
    assert len(cartes["cards"]) == LANG_DUE_CARDS_CAP - WARMUP_MAX_CARDS


def test_generation_is_single_flight_and_requeued_at_startup(client, fake):
    from db import lang_episode_db as store
    from services import lang_episodes

    lang_runs_profile = _profile()
    store.create_episode(lang_runs_profile["id"], 1, kind="normal", program_point_id="es.a1.saludos",
                         format="dialogue", ladder_step=0, params={"tier_index": 0})
    key = (lang_runs_profile["id"], 1)
    assert lang_episodes._GENERATIONS.claim(key) is None
    try:
        assert lang_episodes.trigger_generation(lang_runs_profile["id"], 1) is False
    finally:
        lang_episodes._GENERATIONS.release(key)
    store.update_episode(_episode(1)["id"], status="generating")
    assert lang_episodes.requeue_stuck() == 1 and _episode(1)["status"] == "queued"


# ── Épisodes en attente : relancés sans attendre une séance ──────────────────

def _failing_episode_two(client, monkeypatch, fake, failures: int = 1) -> dict:
    """L'épisode 2 réservé puis raté (`failures` échecs journalisés)."""
    from db import lang_episode_db as store
    from llm import ollama_client

    _onboard(client)
    monkeypatch.setattr(ollama_client, "generate_lang_episode_text_async",
                        lambda params, ok, err, on_metrics=None, model=None: err("panne"))
    _play(client, _start(client))
    episode = _episode(2)
    assert episode["status"] == "failed"
    store.update_episode(episode["id"], generation={**episode["generation"], "failures": failures})
    monkeypatch.setattr(ollama_client, "generate_lang_episode_text_async", fake.fake_text)
    return _episode(2)


@pytest.fixture
def ollama_up(monkeypatch):
    from llm import ollama_client

    monkeypatch.setattr(ollama_client, "is_ollama_available", lambda: True)


def test_an_episode_interrupted_by_closing_the_app_restarts_at_startup(
        client, fake, clock, ollama_up, monkeypatch, no_startup_relaunch):
    """L'application fermée pendant l'écriture : au démarrage, l'épisode repasse
    en file ET repart, sans attendre une séance qui retombe en relecture."""
    import threading

    from db import lang_episode_db as store
    from services import lang_runs

    _failing_episode_two(client, monkeypatch, fake)
    store.update_episode(_episode(2)["id"], status="generating")
    monkeypatch.setattr(lang_runs, "relaunch_pending_episodes", no_startup_relaunch)
    lang_runs.on_startup()
    for thread in threading.enumerate():
        if thread.name == "lang-episodes-relaunch":
            thread.join(timeout=30)
    assert _episode(2)["status"] == "ready"


def test_a_failed_episode_is_retried_below_the_pro_threshold_only(client, fake, clock, ollama_up, monkeypatch):
    from config.settings import LANG_GEN_FAILURES_PRO_HINT
    from services import lang_episodes

    episode = _failing_episode_two(client, monkeypatch, fake, failures=LANG_GEN_FAILURES_PRO_HINT)
    calls = len(fake.CALLS)
    assert lang_episodes.relaunch_pending() == []
    assert _episode(2)["status"] == "failed" and len(fake.CALLS) == calls  # la séance reste le seul essai

    from db import lang_episode_db as store

    store.update_episode(episode["id"], generation={**episode["generation"], "failures": 1})
    assert lang_episodes.relaunch_pending() == [episode["id"]]
    assert _episode(2)["status"] == "ready"


def test_nothing_restarts_and_nothing_counts_while_ollama_is_down(client, fake, clock, monkeypatch):
    """Ollama éteint : une panne n'est pas un échec d'écriture."""
    from services import lang_episodes

    _failing_episode_two(client, monkeypatch, fake)
    calls = len(fake.CALLS)
    assert lang_episodes.relaunch_pending() == []
    episode = _episode(2)
    assert episode["status"] == "failed" and episode["generation"]["failures"] == 1
    assert len(fake.CALLS) == calls
    assert client.post(f"/api/lang/{LANG}/next/ensure").json()["relaunched"] == []


def test_the_language_home_relaunches_the_next_episode_once(client, fake, clock, ollama_up, monkeypatch):
    """`POST …/next/ensure` : même règle, pour ce profil ; le GET `status` ne
    relance rien. Rappelé, il ne refait rien."""
    episode = _failing_episode_two(client, monkeypatch, fake)
    calls = len(fake.CALLS)
    client.get(f"/api/lang/{LANG}/status")
    assert _episode(2)["status"] == "failed" and len(fake.CALLS) == calls

    first = client.post(f"/api/lang/{LANG}/next/ensure").json()
    assert first["relaunched"] == [episode["id"]] and _episode(2)["status"] == "ready"
    calls = len(fake.CALLS)
    assert client.post(f"/api/lang/{LANG}/next/ensure").json()["relaunched"] == []
    assert len(fake.CALLS) == calls
    assert client.get(f"/api/lang/{LANG}/status").json()["next_status"] == "ready"


def test_upcoming_names_the_next_episode_of_each_open_language(client, fake, clock):
    """L'annonce « épisode prêt » et les pastilles de la page Langues : en
    lecture seule — aucun profil créé, rien de relancé."""
    from db.lang_db import get_all_lang_profiles

    assert client.get("/api/lang/upcoming").json() == []
    assert get_all_lang_profiles(1) == []
    client.post("/api/lang/lesson/start", json={"language": "italien"})  # flux hérité : pas d'épisode
    _onboard(client)
    entry = {"language": LANG, "episode_n": 1, "status": "ready", "generating": False, "relecture_due": False}
    assert client.get("/api/lang/upcoming").json() == [entry]
    _play(client, _start(client))
    assert client.get("/api/lang/upcoming").json() == [{**entry, "episode_n": 2}]
    clock["advance"](4)
    assert client.get("/api/lang/upcoming").json() == [{**entry, "episode_n": 2, "relecture_due": True}]
    assert {p["language"] for p in get_all_lang_profiles(1)} == {LANG, "italien"}


# ── Langue d'explication (§ 14, n° 14) ────────────────────────────────────────

@pytest.fixture
def english_ui(client):
    """Interface en anglais pour la durée du test (la langue est globale)."""
    import i18n

    client.post("/api/preferences/lang", json={"lang": "en"})
    yield
    i18n.set_lang("fr")


def test_an_english_interface_gets_an_english_feuilleton(client, fake, clock, english_ui):
    """Clikoda écrivait tout en français, même pour une interface anglaise : la
    langue d'explication est désormais celle de l'interface au début du
    parcours, et TOUT ce qu'écrit Clikoda la suit — prompts, consigne système,
    bible de secours, traductions, notes, point du jour."""
    _onboard(client)
    assert _profile()["explain_lang"] == "en"
    tasks = {p["task"]: p for p in fake.PROMPTS}
    assert all(p.get("explain_lang") == "en" for p in fake.PROMPTS)
    assert "between" in tasks["text"]["constraints"] and "English translation" in tasks["text"]["line_schema"]
    from db import lang_episode_db as store

    bible = store.get_latest_bible(_profile()["id"])
    assert bible["source"] == "defaut" and bible["characters"][0]["role"] == "owner of a small café in Salamanca"
    run = _start(client)
    assert run["mode"] == "episode" and run["explain_lang"] == "en"
    ep = run["episodes"][str(run["episode_id"])]
    assert ep["explain_lang"] == "en" and ep["lines"][0]["translation"] == "Hi, Pablo. How are you today?"
    assert any(g["translation"] == "hello" for g in ep["glossary"])
    notes = next(s for s in run["steps"] if s["kind"] == "lecture")["notes"]
    assert notes[0]["text"].startswith("Hola is used")
    lecon = next(s for s in run["steps"] if s["kind"] == "lecon")
    point = lecon["point"]
    assert point["title"] == "Greeting and introducing yourself" and point["learner_goal"].startswith("Can ")
    assert lecon["lesson"]["rule"].startswith("Estar describes")  # leçon écrite en anglais pour lui
    task = next(s for s in run["steps"] if s["kind"] == "expression")["task"]
    assert task["explain_lang"] == "en" and "words" in task["prompt"]
    assert client.get(f"/api/lang/{LANG}/status").json()["program"]["point"] == "Greeting and introducing yourself"
    # La langue reste celle du feuilleton si l'interface change ensuite.
    client.post("/api/preferences/lang", json={"lang": "fr"})
    _play(client, run)
    assert _profile()["explain_lang"] == "en" and _episode(2)["lines"][0]["translation"].startswith("Hi")


def test_the_zero_run_shows_english_survival_phrases(client, fake, clock, english_ui):
    client.post(f"/api/lang/{LANG}/onboarding", json={"interests": ["food"], "has_studied": False})
    phrases = _start(client)["steps"][1]["phrases"]
    assert phrases[0]["translation"] == "Hi, how are you?"
    assert phrases[5] == {"target": "¿Habla usted inglés?", "translation": "Do you speak English?", "note": None}


def test_english_is_explained_in_french(client, fake, clock, english_ui):
    """On n'explique pas une langue dans elle-même : l'anglais reste expliqué en français."""
    client.post("/api/lang/anglais/onboarding", json={"interests": [], "has_studied": False})
    from db import lang_episode_db as store
    from db.lang_db import get_or_create_lang_profile

    assert store.decode_profile(get_or_create_lang_profile(1, "anglais"))["explain_lang"] == "fr"


def test_placement_items_follow_the_explanation_language(client, fake, clock, english_ui):
    client.post(f"/api/lang/{LANG}/onboarding", json={"interests": [], "has_studied": True})
    items = {it["id"]: it for it in client.get(f"/api/lang/{LANG}/placement").json()["items"]}
    assert items["es.p02"]["prompt"].endswith("The person is asking…")
    assert items["es.p02"]["choices"][1] == "where the station is"
    assert items["es.p01"]["prompt"] == "Yo ___ francés."  # item en langue cible : inchangé


# ── Porte V17 : pas de mandarin sans pypinyin (§ 14, n° 8) ────────────────────

def test_mandarin_is_closed_without_pypinyin(client, monkeypatch):
    from services import lang_mandarin

    monkeypatch.setattr(lang_mandarin, "PINYIN_AVAILABLE", False)
    status = client.get("/api/lang/mandarin/status").json()
    assert status["unavailable"] == "pinyin" and "onboarding_done" not in status
    assert client.post("/api/lang/mandarin/onboarding", json={"interests": [], "has_studied": False}).status_code == 404
    assert client.post("/api/lang/mandarin/run/start", json={}).status_code == 404
    assert client.get(f"/api/lang/{LANG}/status").json().get("unavailable") is None


# ── Jour d'étude commun, avec ou sans ressenti (§ 14, n° 11) ──────────────────

def test_a_run_without_feeling_still_counts_as_a_study_day(client, fake, clock, monkeypatch):
    from services import session

    calls = []
    monkeypatch.setattr(session, "nudge_metacog_profile", lambda *a, **k: calls.append((a, k)))
    _onboard(client)
    _play(client, _start(client), feeling=False)
    args, kwargs = calls[-1]
    assert args[2] == [] and kwargs["questions"] == []


def test_the_common_streak_moves_without_a_feeling(client, fake, clock):
    from db.user import get_streak

    assert get_streak()["last_study_day"] is None
    client.post(f"/api/lang/{LANG}/onboarding", json={"interests": [], "has_studied": False})
    _play(client, _start(client), feeling=False)
    assert get_streak()["last_study_day"] is not None


# ── Les jauges bougent, la séance rejoint « Ma progression » ─────────────────

def test_a_played_run_draws_its_gauges_and_moves_the_profile(client, fake, clock):
    """Jeux réussis et « compris » : la courbe de la séance monte sur la
    compréhension et la rétention, le profil glisse vers elle, et la séance
    figure dans « Ma progression » avec ce qu'elle a gagné — jamais de score."""
    from db.metacog import get_history
    from db.practice_sessions import find_practice_session

    _onboard(client)
    run = _start(client)
    _play(client, run, answers="right", signal="compris")

    practice = find_practice_session(lang_run_id=run["run_id"])
    assert practice is not None and practice["kind"] == "lang"
    detail = client.get(f"/api/progress/practice/{practice['id']}").json()
    assert detail["lang"]["language"] == LANG and detail["lang"]["flow"] == "feuilleton"
    assert detail["lang"]["episode"]["n"] == 1 and detail["lang"]["new_words"]
    assert "score" not in detail["lang"]
    gauges = detail["gauges"]
    assert gauges["axis"] == "time"
    assert {"retention", "context_comprehension"} <= set(gauges["measured"])
    assert not {"curiosity", "creativity", "meta_cognition"} & set(gauges["measured"])
    assert gauges["series"]["context_comprehension"][-1]["value"] > gauges["seed"]["context_comprehension"]
    assert [row for row in get_history() if row["practice_session_id"] == practice["id"]]

    rows = client.get("/api/progress/sessions", params={"kind": "lang"}).json()["sessions"]
    assert practice["id"] in {row["session_id"] for row in rows}


def test_wrong_answers_and_not_understood_lower_the_run_gauges(client, fake, clock):
    from db.practice_sessions import find_practice_session

    _onboard(client)
    run = _start(client)
    _play(client, run, answers="wrong", signal="pas_compris")
    practice = find_practice_session(lang_run_id=run["run_id"])
    gauges = client.get(f"/api/progress/practice/{practice['id']}").json()["gauges"]
    assert gauges["series"]["context_comprehension"][-1]["value"] < gauges["seed"]["context_comprehension"]


def test_a_run_without_any_measure_counts_without_moving_the_profile(client, fake, clock):
    """La séance zéro ne joue aucun jeu et ne lit aucun épisode : elle compte (la
    série, le nombre de séances), elle ne déplace rien — un silence ne se note pas."""
    from db.metacog import ensure_profile, get_history

    _onboard(client)
    assert int(ensure_profile()["sessions_count"]) == 1
    assert get_history() == []


# ── Génération fiable, limites du modèle local ────────────────────────────────

def test_a_reprise_respiration_starts_from_the_step_of_the_played_episode(client, fake, clock):
    """Base de dev : l'épisode 3, décidé d'avance un cran plus haut, a été
    redécidé en respiration par une reprise… en montant encore (3 → 4).
    Seul un épisode pas encore écrit est redécidé : un épisode prêt est gardé."""
    from db import lang_episode_db as store

    _onboard(client)
    _play(client, _start(client))
    played_step = _episode(1)["ladder_step"]
    store.update_episode(_episode(2)["id"], ladder_step=played_step + 1, status="queued")
    store.update_profile_fields(_profile()["id"], ladder_step=played_step + 1)
    clock["advance"](10)
    assert _start(client)["mode"] == "reprise"
    assert _episode(2)["kind"] == "respiration" and _episode(2)["ladder_step"] == played_step
    assert _profile()["ladder_step"] == played_step


def test_feuilleton_cards_are_never_reimported_backwards(client):
    """Les cartes du feuilleton ont le mot cible au recto : un profil recréé ne
    les importe pas comme des cartes héritées (verso = mot cible)."""
    _add_cards(2, due=True, prefix="du")
    assert client.get(f"/api/lang/{LANG}/status").json()["words_seen"] == 0


def test_status_names_the_local_model_and_when_to_mention_its_limits(client, fake, clock, monkeypatch):
    from config.settings import OLLAMA_MODEL
    from db import lang_episode_db as store
    from llm import ollama_client

    _onboard(client)
    status = client.get(f"/api/lang/{LANG}/status").json()
    assert status["model"] == OLLAMA_MODEL and status["pro_hints"] == [] and status["generation_failures"] == 0
    monkeypatch.setattr(ollama_client, "generate_lang_episode_text_async",
                        lambda params, ok, err, on_metrics=None, model=None: err("panne"))
    _play(client, _start(client))  # l'épisode 2 échoue une fois…
    assert client.get(f"/api/lang/{LANG}/status").json()["pro_hints"] == []
    # Un échec journalisé avant que le compte existe vaut un, ici comme au générateur.
    failed = _episode(2)
    legacy = {k: v for k, v in failed["generation"].items() if k != "failures"}
    store.update_episode(failed["id"], generation=legacy)
    assert legacy.get("error") and client.get(f"/api/lang/{LANG}/status").json()["generation_failures"] == 1
    clock["advance"]()
    _start(client)  # … et une deuxième à la séance suivante
    status = client.get(f"/api/lang/{LANG}/status").json()
    assert status["generation_failures"] == 2 and status["pro_hints"] == ["generation"]
    assert _episode(2)["generation"]["failures"] == 2
    store.update_profile_fields(_profile()["id"], program_order=store.program_size(LANG))
    assert "program_end" in client.get(f"/api/lang/{LANG}/status").json()["pro_hints"]


def test_the_journal_says_what_was_estimated_and_repaired(client, fake, clock):
    _onboard(client)
    gen = _episode(1)["generation"]
    assert gen["soft_accepted"] == [] and gen["lemma_repairs"] == [] and gen["failures"] == 0
    assert gen["new_words_estimate"]["checked"] is False  # lexique vide : rien à contrôler
    assert gen["new_words_estimate"]["estimate"] > 0


def test_a_placed_learner_is_never_refused_for_new_words(client, fake, clock):
    """Les deux profils placés de la base de dev : leur lexique ne dit rien de
    ce qu'ils savent, le contrôle ne s'applique pas à eux."""
    from db import lang_episode_db as store

    items = client.get(f"/api/lang/{LANG}/placement").json()["items"]
    keys = {it["id"]: it["answer"] for it in store.get_placement_items(LANG)}
    client.post(f"/api/lang/{LANG}/placement/submit", json={"answers": {it["id"]: keys[it["id"]] for it in items[:5]}})
    for i in range(80):
        store.insert_lexeme(_profile()["id"], {"form": f"x{i}", "lemma": f"x{i}", "translation": "y"}, 1)
    _play(client, _start(client))
    gen = _episode(2)["generation"]
    assert _episode(2)["status"] == "ready" and gen["new_words_estimate"]["checked"] is False


# ── Une seule lecture, aide à la demande ──────────────────────────────────────

def test_a_translated_line_counts_as_an_exposure_only(client, fake, clock):
    """Une réplique dont la traduction a été montrée ne dit rien de ce que
    l'apprenant lit seul : ses mots ne sont ni reconnus ni ratés."""
    from db import lang_episode_db as store

    _onboard(client)
    run = _start(client)
    ep = run["episodes"][str(run["episode_id"])]
    _play(client, run, translate=range(len(ep["lines"])), answers=None)  # les jeux compteraient aussi
    lexicon = store.get_lexicon(_profile()["id"])
    assert lexicon and all(row["recognitions_ok"] == 0 and row["recognitions_ko"] == 0 for row in lexicon.values())
    assert all(row["exposures"] >= 1 for row in lexicon.values())
    clock["advance"]()
    run = _start(client)
    _play(client, run, answers=None)  # lue seule, la même lecture reconnaît ses mots
    assert any(row["recognitions_ok"] for row in store.get_lexicon(_profile()["id"]).values())


def test_translate_all_at_a1_is_never_a_hard_verdict(client, fake, clock):
    """« Tout traduire » est une aide prévue au palier A1 : la séance suivante
    n'est pas une respiration."""
    _onboard(client)
    run = _start(client)
    ep = run["episodes"][str(run["episode_id"])]
    _play(client, run, translate=range(len(ep["lines"])))
    signals = client.get(f"/api/lang/run/{run['run_id']}").json()["signals"]
    assert signals["translated_share"] == 1.0 and signals["reveal_rate"] is None and signals["tier_index"] == 0
    assert _episode(2)["kind"] == "normal" and _episode(2)["params"]["verdict"] != "hard"


def test_an_open_run_of_the_old_format_is_abandoned(client, fake, clock):
    """Une séance ouverte aux passages 1 et 2 (plan v1) n'est pas reprise : le
    front n'en a plus les vues. Elle est abandonnée et une neuve est bâtie."""
    from db import lang_episode_db as store

    _onboard(client)
    run = _start(client)
    old_plan = {**store.get_run(run["run_id"])["plan"]}
    old_plan.pop("version")
    store.update_run(run["run_id"], plan=old_plan, current_step="episode_p2")
    fresh = _start(client)
    assert fresh["run_id"] != run["run_id"] and not fresh["resumed"] and fresh["version"] == 2
    assert client.get(f"/api/lang/run/{run['run_id']}").json()["status"] == "abandoned"


# ── La leçon du point ─────────────────────────────────────────────────────────

def test_a_lesson_written_after_assembly_is_served_when_its_step_starts(client, fake, clock, monkeypatch):
    """Tout premier épisode : sa leçon n'est pas encore écrite quand la séance
    s'assemble. L'étape la redemande en y entrant — sans attente — et ses items
    rejoignent le plan, corrigés comme les autres."""
    from db import lang_episode_db as store
    from llm import ollama_client
    from services import lang_point_lesson

    monkeypatch.setattr(ollama_client, "generate_lang_point_lesson_async",
                        lambda params, ok, err, on_metrics=None, model=None: err("panne"))
    _onboard(client)
    assert _episode(1)["status"] == "ready"  # l'échec de la leçon ne touche jamais l'épisode
    run = _start(client)
    lecon = next(s for s in run["steps"] if s["kind"] == "lecon")
    assert lecon["lesson_pending"] and lecon["lesson"] is None and lecon["lesson_source"] == "fallback"
    assert lecon["items"]  # les items du texte, eux, sont là
    rid = run["run_id"]
    fallback = client.get(f"/api/lang/run/{rid}/lesson").json()
    assert fallback == {"lesson": None, "lesson_source": "fallback", "lesson_pending": True, "lesson_items": []}
    monkeypatch.setattr(ollama_client, "generate_lang_point_lesson_async", fake.fake_lesson)
    point_id = _episode(1)["program_point_id"]
    store.save_point_lesson(LANG, point_id, "fr", status="failed", lesson=None, point_hash="", model="m",
                            attempts=0, generation={})
    assert lang_point_lesson.ensure_point_lesson(LANG, point_id, "fr") == "ready"
    served = client.get(f"/api/lang/run/{rid}/lesson").json()
    assert served["lesson"]["rule"] and not served["lesson_pending"] and len(served["lesson_items"]) == 3
    item = served["lesson_items"][0]
    client.post(f"/api/lang/run/{rid}/events", json={"events": [
        {"type": "answer", "item": item["ref"], "given": item["expected"]}]})
    attempts = {a["item_ref"]: a for a in store.get_attempts(rid)}
    assert attempts[item["ref"]]["correct"] == 1 and attempts[item["ref"]]["step"] == "lecon"


def test_the_bilan_and_the_library_reuse_the_lesson(client, fake, clock):
    _onboard(client)
    for _ in range(6):
        _play(client, _start(client))
        clock["advance"]()
    run = _start(client)
    recap = next(s for s in run["steps"] if s["kind"] == "recap")
    assert all(p.get("rule") and p.get("remember") for p in recap["points"])
    library = client.get(f"/api/lang/{LANG}/library").json()
    view = client.get(f"/api/lang/episode/{library[0]['id']}").json()
    assert view["lesson"]["rule"] and view["lesson"]["examples"]
