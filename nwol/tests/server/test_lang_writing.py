# L'expression écrite d'une séance (étape « expression ») : consigne, envoi,
# correction en arrière-plan, mesure (service et routes).
#
# Clikoda est remplacé par tests/lang_fakes.py et la correction est jouée
# inline : on voit ce que verrait l'apprenant, sans Ollama ni thread.
import unicodedata

import pytest

import lang_fakes
from services import lang_writing as writing

LANG = "espagnol"


@pytest.fixture
def fake(monkeypatch):
    lang_fakes.install(monkeypatch)
    return lang_fakes


@pytest.fixture
def clock(monkeypatch):
    from datetime import date

    from services import lang_activity

    monkeypatch.setattr(lang_activity, "study_date", lambda dt=None: date(2026, 9, 21).isoformat())


def _episode_run(client, language=LANG):
    client.post(f"/api/lang/{language}/onboarding", json={"interests": [], "has_studied": False})
    zero = client.post(f"/api/lang/{language}/run/start", json={}).json()
    client.post(f"/api/lang/run/{zero['run_id']}/complete", json={"end_reason": "fini"})
    run = client.post(f"/api/lang/{language}/run/start", json={}).json()
    assert run["mode"] == "episode"
    return run


def _task(run):
    return next(s for s in run["steps"] if s["kind"] == "expression")["task"]


# ── La consigne ───────────────────────────────────────────────────────────────

def test_the_task_is_deterministic_and_in_the_explanation_language(client, fake, clock):
    run = _episode_run(client)
    task = _task(run)
    assert task["kind"] == "repondre" and task["speaker"] and task["speaker"] in task["prompt"]
    assert task["length"] == {"min": 15, "max": 40, "unit": "words"} and "15 à 40 mots" in task["prompt"]
    assert len(task["use_words"]) == 3 and all(w["translation"] for w in task["use_words"])
    assert task["use_forms"] and task["bank"]
    from db import lang_episode_db as store

    episode = store.get_episode(run["episode_id"])
    assert writing.writing_task(LANG, episode, "fr") == task  # rien d'aléatoire
    english = writing.writing_task(LANG, episode, "en")
    assert "15 to 40 words" in english["prompt"] and english["explain_lang"] == "en"


def test_checks_count_words_and_spot_the_words_of_the_day():
    task = {"length": {"min": 5, "max": 20, "unit": "words"},
            "use_words": [{"form": "estar", "match": ["estar", "estoy"]}, {"form": "plaza", "match": ["plaza"]}],
            "use_forms": ["muy bien"]}
    out = writing.checks(LANG, "Hoy estamos muy bien en la plaza.", task)
    assert out["length"] == {"value": 7, "min": 5, "max": 20, "unit": "words", "ok": True}
    assert [w["used"] for w in out["words_used"]] == [True, True]  # « estamos » : estar fléchi
    assert out["forms_used"] == [{"form": "muy bien", "used": True}] and out["script"]["ok"]
    short = writing.checks(LANG, "Hola.", task)
    assert short["length"]["ok"] is False and not short["words_used"][0]["used"]


def test_mandarin_counts_characters_and_flags_pinyin():
    task = {"length": {"min": 5, "max": 40, "unit": "chars"}, "use_words": [{"form": "朋友", "match": ["朋友"]}],
            "use_forms": []}
    out = writing.checks("mandarin", "我的朋友很好。", task)
    assert out["length"]["value"] == 6 and out["words_used"][0]["used"] and out["script"]["ok"]
    pinyin = writing.checks("mandarin", "wo de pengyou hen hao", task)
    assert pinyin["script"]["ok"] is False and pinyin["length"]["value"] == 0


# ── Envoi et correction ───────────────────────────────────────────────────────

def test_a_writing_is_corrected_in_the_background_and_measured(client, fake, clock):
    run = _episode_run(client)
    rid = run["run_id"]
    text = "Hoy estoy muy bien en la plaza con Carmen."
    res = client.post(f"/api/lang/run/{rid}/writing", json={"text": text}).json()
    assert res["status"] == "ready" and res["text"] == text  # correction jouée inline par les tests
    feedback = res["feedback"]
    assert feedback["verdict"] == "partial" and feedback["errors"][0]["original"] == "Hoy"
    assert res["checks"]["length"]["value"] == 9
    # Une seule par séance : un second envoi rend la première.
    again = client.post(f"/api/lang/run/{rid}/writing", json={"text": "Otra cosa."}).json()
    assert again["id"] == res["id"] and again["text"] == text
    assert client.get(f"/api/lang/writing/{res['id']}").json()["feedback"] == feedback
    done = client.post(f"/api/lang/run/{rid}/complete", json={"end_reason": "fini"}).json()
    assert done["writing"] == {"id": res["id"], "status": "ready"}
    from services.lang_runs import _run_measures
    from db import lang_episode_db as store

    measures = _run_measures(rid, store.get_run(rid)["plan"])
    assert {"verdict": "partial", "targets": ("retention", "context_comprehension")} in [
        {k: m[k] for k in ("verdict", "targets")} for m in measures]


def test_a_correction_not_ready_at_closing_is_not_a_measure(client, fake, clock, monkeypatch):
    from db import lang_episode_db as store
    from services.lang_runs import _run_measures

    monkeypatch.setattr(writing, "RUN_IN_BACKGROUND", True)
    monkeypatch.setattr(writing, "schedule_correction", lambda writing_id: True)  # jamais arrivée
    run = _episode_run(client)
    res = client.post(f"/api/lang/run/{run['run_id']}/writing", json={"text": "Hoy estoy muy bien."}).json()
    assert res["status"] == "pending" and res["feedback"] is None
    client.post(f"/api/lang/run/{run['run_id']}/complete", json={"end_reason": "fini"})
    measures = _run_measures(run["run_id"], store.get_run(run["run_id"])["plan"])
    assert not any(m["targets"] == ("retention", "context_comprehension") for m in measures)
    # Elle arrive après la séance : l'accueil la propose, puis elle est vue.
    assert writing.correct(res["id"]) == "ready"
    status = client.get(f"/api/lang/{LANG}/status").json()
    assert status["unseen_writing"] == {"id": res["id"], "run_id": run["run_id"]}
    client.post(f"/api/lang/writing/{res['id']}/seen")
    assert client.get(f"/api/lang/{LANG}/status").json()["unseen_writing"] is None


def test_the_status_cycle_and_a_failed_correction(client, fake, clock, monkeypatch):
    from db import lang_episode_db as store
    from llm import ollama_client

    monkeypatch.setattr(ollama_client, "generate_lang_writing_feedback_async",
                        lambda params, ok, err, on_metrics=None, model=None: err("panne"))
    run = _episode_run(client)
    res = client.post(f"/api/lang/run/{run['run_id']}/writing", json={"text": "Hoy estoy muy bien."}).json()
    assert res["status"] == "failed" and res["feedback"] is None
    # Une correction interrompue par la fermeture repart au démarrage.
    store.update_writing(res["id"], status="correcting")
    monkeypatch.setattr(ollama_client, "generate_lang_writing_feedback_async", lang_fakes.fake_writing_feedback)
    assert writing.requeue_stuck() == 1
    assert store.get_writing(res["id"])["status"] == "ready"


@pytest.mark.parametrize("text", ["", "   ", "Je suis allé au marché et il est très content avec nous."])
def test_an_empty_text_or_one_in_the_learners_language_is_skipped(client, fake, clock, text):
    run = _episode_run(client)
    res = client.post(f"/api/lang/run/{run['run_id']}/writing", json={"text": text}).json()
    assert res["status"] == "skipped" and "writing" not in fake.CALLS


def test_the_text_is_normalized_and_capped(client, fake, clock):
    from config.settings import LANG_WRITING_MAX_CHARS

    run = _episode_run(client)
    decomposed = unicodedata.normalize("NFD", "Mañana está en la plaza. ") * 80
    res = client.post(f"/api/lang/run/{run['run_id']}/writing", json={"text": decomposed}).json()
    assert len(res["text"]) == LANG_WRITING_MAX_CHARS
    assert res["text"] == unicodedata.normalize("NFC", res["text"]) and "ñ" in res["text"]


@pytest.mark.parametrize("language,text", [
    ("arabe", "أَنَا بِخَيْرٍ وَالْحَمْدُ لِلّٰهِ"),
    ("mandarin", "我今天很好，我的朋友也很好。"),
])
def test_arabic_and_chinese_round_trip(client, fake, clock, monkeypatch, language, text):
    """Le texte revient tel qu'il a été écrit : voyelles brèves et šadda en
    arabe, caractères et ponctuation chinoise."""
    if language == "mandarin":
        pytest.importorskip("pypinyin")
    from db import lang_episode_db as store
    from services import lang_runs

    profile = lang_runs.ensure_feuilleton(language)
    store.update_profile_fields(profile["id"], onboarding_done=1)
    episode_id = store.create_episode(profile["id"], 1, kind="normal", program_point_id=None, format="dialogue",
                                      ladder_step=0, params={"tier_index": 0})
    run_id = store.create_run(profile["id"], mode="episode", plan={
        "version": 2, "language": language,
        "steps": [{"key": "expression", "kind": "expression", "episode_ref": episode_id,
                   "task": {"explain_lang": "fr", "length": {"min": 1, "max": 40, "unit": "words"}}}]},
        episode_id=episode_id, second_wave_episode_id=None, absence_days=None, study_date="2026-09-21")
    monkeypatch.setattr(writing, "schedule_correction", lambda writing_id: True)
    res = client.post(f"/api/lang/run/{run_id}/writing", json={"text": text}).json()
    assert res["status"] == "pending" and res["text"] == unicodedata.normalize("NFC", text)
    assert client.get(f"/api/lang/writing/{res['id']}").json()["text"] == unicodedata.normalize("NFC", text)


def test_pinyin_is_corrected_anyway(client, fake, clock):
    assert writing._in_explanation_language("mandarin", "wo hen hao, xiexie", "fr") is False
    assert writing._in_explanation_language("mandarin", "je suis très content et il est là", "fr") is True
    assert writing._in_explanation_language("espagnol", "He comido en la plaza con mi amigo.", "en") is False


def test_feedback_validation():
    text = "Hoy soy cansado en la plaza."
    good = {"verdict": "partial", "errors": [{"original": "soy cansado", "correction": "estoy cansado",
                                               "error_type": "conjugaison", "explanation": "Un état : estar."}],
            "corrected": "Hoy estoy cansado en la plaza.", "praise": "Bonne phrase."}
    value, errors = writing.validate_feedback(LANG, good, text, "fr")
    assert errors == [] and value["errors"][0]["original"] == "soy cansado"
    # Retrouvé à la casse près : le passage reprend l'écriture de l'apprenant.
    value, errors = writing.validate_feedback(LANG, {**good, "errors": [{**good["errors"][0], "original": "SOY cansado"}]},
                                              text, "fr")
    assert errors == [] and value["errors"][0]["original"] == "soy cansado"
    invented = {**good, "errors": [{**good["errors"][0], "original": "estaba cansado"}]}
    assert any("n'est pas dans le texte" in e for e in writing.validate_feedback(LANG, invented, text, "fr")[1])
    french = {**good, "corrected": "Je suis fatigué et il est très tard."}
    assert any("texte corrigé" in e for e in writing.validate_feedback(LANG, french, text, "fr")[1])
    english = {**good, "errors": [{**good["errors"][0], "explanation": "It is the state of the person, you see."}]}
    assert any("en français" in e for e in writing.validate_feedback(LANG, english, text, "fr")[1])
    many = {**good, "errors": [good["errors"][0]] * 5, "verdict": "correct"}
    value, _ = writing.validate_feedback(LANG, many, text, "fr")
    assert len(value["errors"]) == 3 and value["verdict"] == "partial"
    # « X → X » (vu avec le vrai modèle) : écartée sans relance ; la casse, elle, se corrige.
    noop = {"original": "en la plaza.", "correction": "en  la plaza.", "error_type": "vocabulaire",
            "explanation": "Il manque un point d'exclamation."}
    value, errors = writing.validate_feedback(LANG, {**good, "errors": [good["errors"][0], noop]}, text, "fr")
    assert errors == [] and [e["original"] for e in value["errors"]] == ["soy cansado"]
    case = {**noop, "original": "Hoy", "correction": "hoy"}
    assert len(writing.validate_feedback(LANG, {**good, "errors": [case]}, text, "fr")[0]["errors"]) == 1


def test_unknown_writing_and_run_answer_404(client):
    assert client.get("/api/lang/writing/999").status_code == 404
    assert client.post("/api/lang/writing/999/seen").status_code == 404
    assert client.post("/api/lang/run/999/writing", json={"text": "x"}).status_code == 404
    assert client.get("/api/lang/run/999/lesson").status_code == 404
