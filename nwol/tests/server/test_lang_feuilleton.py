# Parcours complet de la méthode « feuilleton » (plan § 10, § 14, § 15 ; V5).
#
# Gemma est remplacé par tests/lang_fakes.py (sorties valides construites depuis
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


def _play(client, run, *, answers="right", signal="compris", taps=0, finish=True, feeling=True):
    """Joue une séance : chaque étape est ouverte, jouée, fermée, un lot par étape."""
    rid = run["run_id"]
    ep = run["episodes"].get(str(run.get("episode_id"))) if run.get("episode_id") else None
    for step in run["steps"]:
        events = [{"type": "step", "step": step["key"], "started": True}]
        if step["kind"] == "episode_p2" and ep:
            words = [(li, ti) for li, ln in enumerate(ep["lines"]) for ti, t in enumerate(ln["tokens"]) if t["w"]]
            for li, ti in words[:taps]:
                events.append({"type": "reveal", "episode_id": ep["id"], "line": li, "token": ti, "pass": "p2"})
        items = [it for g in step.get("games", []) for it in g["items"]] + step.get("items", [])
        for it in items:
            given = it.get("expected") if answers == "right" else ("__faux__" if answers == "wrong" else None)
            events.append({"type": "answer", "item": it["ref"], "given": given, "ms": 800})
        for line in step.get("lines", []) if step["kind"] == "deuxieme_vague" else []:
            events.append({"type": "rating", "episode_id": step["episode_ref"], "line": line["line"], "rating": "su"})
        events.append({"type": "step", "step": step["key"], "ended": True, "active_s": 60,
                       "signal": signal if step["kind"].startswith("episode") else None})
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
    create_lang_vocab_flashcards(LANG, [{"word": "casa", "translation": "maison"}])
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
    assert len(fake.CALLS) == calls, "une séance ne doit jamais attendre Gemma"
    assert run["mode"] == "episode" and run["episode_n"] == 1
    kinds = [s["kind"] for s in run["steps"]]
    assert kinds == ["episode_p1", "episode_p2", "notes", "point", "jeux", "au_revoir"]
    ep = run["episodes"][str(run["episode_id"])]
    assert all("".join(t["text"] for t in ln["tokens"]) for ln in ep["lines"])
    assert any(t.get("g") is not None for ln in ep["lines"] for t in ln["tokens"])
    point = next(s for s in run["steps"] if s["kind"] == "point")
    assert point["point"]["title"] == "Saluer et se présenter" and len(point["items"]) == 3
    games = next(s for s in run["steps"] if s["kind"] == "jeux")["games"]
    assert len(games) == 2 and games[-1]["ease"] == min(g["ease"] for g in games)
    assert run["steps"][-1]["essential"] is True


def test_next_episode_is_written_when_the_notes_step_starts(client, fake, clock):
    _onboard(client)
    run = _start(client)
    rid = run["run_id"]
    client.post(f"/api/lang/run/{rid}/events", json={"events": [
        {"type": "step", "step": "episode_p1", "ended": True, "active_s": 90},
        {"type": "step", "step": "episode_p2", "ended": True, "active_s": 60, "signal": "compris"},
    ], "current_step": "episode_p2"})
    assert _episode(2) is None
    client.post(f"/api/lang/run/{rid}/events", json={"events": [{"type": "step", "step": "notes", "started": True}],
                                                     "current_step": "notes"})
    assert _episode(2)["status"] == "ready"
    assert _episode(1)["status"] == "played" and _profile()["episode_n"] == 1
    assert _episode(2)["program_point_id"] == "es.a1.ser_identidad"


def test_answers_are_regraded_by_the_service_and_unanswered_is_null(client, fake, clock):
    from db import lang_episode_db as store

    _onboard(client)
    run = _start(client)
    point = next(s for s in run["steps"] if s["kind"] == "point")
    first, second = point["items"][0], point["items"][1]
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


def test_feeling_answer_joins_the_metacognitive_profile(client, fake, clock, monkeypatch):
    """R8 : la réponse est gardée sur la séance et transmise au profil commun,
    sans mesure (lecture jamais notée : les jauges ne bougent pas)."""
    from services import session

    calls = []
    monkeypatch.setattr(session, "nudge_metacog_profile", lambda *a, **k: calls.append((a, k)))
    _onboard(client)
    run = _start(client)
    _play(client, run)
    stored = client.get(f"/api/lang/run/{run['run_id']}").json()
    assert stored["status"] == "completed"
    args, kwargs = calls[-1]
    assert kwargs["measures"] == 0 and kwargs["session_id"] is None
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


def test_long_absence_gives_a_reprise_then_a_respiration(client, fake, clock):
    _onboard(client)
    _play(client, _start(client))
    clock["advance"](10)
    run = _start(client)
    assert run["mode"] == "reprise" and run["absence"]["tier"] == "reprise"
    assert [s["kind"] for s in run["steps"]][:3] == ["accueil", "recap", "relecture"]
    assert _episode(2)["kind"] == "respiration"
    _play(client, run)
    clock["advance"]()
    assert _start(client)["mode"] == "episode"


def test_three_weeks_away_adds_a_control_step(client, fake, clock):
    _onboard(client)
    _play(client, _start(client))
    clock["advance"](25)
    run = _start(client)
    assert any(s["kind"] == "controle" for s in run["steps"])


def test_a_few_days_away_gives_a_long_recall(client, fake, clock):
    _onboard(client)
    _play(client, _start(client))
    clock["advance"]()
    _play(client, _start(client))
    clock["advance"](4)
    run = _start(client)
    assert run["mode"] == "episode"
    recall = run["steps"][0]
    assert recall["kind"] == "rappel" and recall["long"] is True
    assert any(s["kind"] == "relecture" for s in run["steps"])


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
    client.post(f"/api/lang/run/{run['run_id']}/events", json={"events": [], "current_step": "episode_p2"})
    again = _start(client)
    assert again["run_id"] == run["run_id"] and again["resumed"] and again["current_step"] == "episode_p2"
    clock["advance"]()
    fresh = _start(client)
    assert fresh["run_id"] != run["run_id"]
    assert client.get(f"/api/lang/run/{run['run_id']}").json()["status"] == "abandoned"


def test_duration_cap_sends_the_learner_to_goodbye(client, fake, clock):
    _onboard(client)
    run = _start(client)
    res = client.post(f"/api/lang/run/{run['run_id']}/events", json={"events": [
        {"type": "step", "step": "episode_p1", "ended": True, "active_s": 1300}]}).json()
    assert res["cap_reached"] and res["skip_to"] == "au_revoir"


def test_short_and_reread_modes_on_request(client, fake, clock):
    _onboard(client)
    court = _start(client, "court")
    assert court["mode"] == "court"
    assert [s["kind"] for s in court["steps"]] == ["rappel", "episode_p1", "episode_p2", "point", "au_revoir"]
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


def test_warmup_cards_are_capped_and_only_due(client, fake, clock):
    from config.settings import LANG_DUE_CARDS_CAP
    from db import get_connection

    _onboard(client)
    conn = get_connection()
    with conn:
        for i in range(LANG_DUE_CARDS_CAP + 5):
            conn.execute("INSERT INTO flashcards (user_id, front, back, language, source, dedup_key, due_at) "
                         "VALUES (1, ?, 'x', ?, 'lang_feuilleton', ?, datetime('now', '-1 day'))",
                         (f"mot{i}", LANG, f"k{i}"))
    cards = client.get("/api/lang/warmup-cards", params={"language": LANG}).json()
    assert len(cards) == LANG_DUE_CARDS_CAP


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


# ── Langue d'explication (§ 14, n° 14) ────────────────────────────────────────

@pytest.fixture
def english_ui(client):
    """Interface en anglais pour la durée du test (la langue est globale)."""
    import i18n

    client.post("/api/preferences/lang", json={"lang": "en"})
    yield
    i18n.set_lang("fr")


def test_an_english_interface_gets_an_english_feuilleton(client, fake, clock, english_ui):
    """Gemma écrivait tout en français, même pour une interface anglaise : la
    langue d'explication est désormais celle de l'interface au début du
    parcours, et TOUT ce qu'écrit Gemma la suit — prompts, consigne système,
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
    notes = next(s for s in run["steps"] if s["kind"] == "notes")["notes"]
    assert notes[0]["text"].startswith("Hola is used")
    point = next(s for s in run["steps"] if s["kind"] == "point")["point"]
    assert point["title"] == "Greeting and introducing yourself" and point["learner_goal"].startswith("Can ")
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
    assert args[2] == [] and kwargs["questions"] == [] and kwargs["measures"] == 0


def test_the_common_streak_moves_without_a_feeling(client, fake, clock):
    from db.user import get_streak

    assert get_streak()["last_study_day"] is None
    client.post(f"/api/lang/{LANG}/onboarding", json={"interests": [], "has_studied": False})
    _play(client, _start(client), feeling=False)
    assert get_streak()["last_study_day"] is not None
