# Tests de la refonte des systèmes d'écriture (nouvelles langues + taxonomie de
# scripts + introduction continue des caractères pour le mandarin/japonais + tons +
# RTL). Aucun Ollama requis : le seul appel LLM (thème de séance) est remplacé par
# un fake. Voir le rapport system/rapport_apprentissage_langues.md.

from services.lang import (
    get_script_meta,
    script_is_continuous,
    script_is_rtl,
    script_is_tonal,
    writing_to_passive,
)


def _fake_plan(state, level, language, phase, ok, err, model=None):
    ok({"theme": "Au marché", "intro": ""})


# ── Catalogue des langues ─────────────────────────────────────────────────────

def test_catalogue_includes_new_languages(client):
    langs = client.get("/api/lang/languages").json()
    codes = {lang["code"] for lang in langs}
    # Échantillon couvrant toutes les familles d'écriture ajoutées.
    for code in ("mandarin", "japonais", "coréen", "arabe", "hébreu", "hindi",
                 "thaï", "grec", "portugais", "vietnamien"):
        assert code in codes, code
    assert len(langs) >= 21


def test_languages_expose_rtl_flag(client):
    by_code = {lang["code"]: lang for lang in client.get("/api/lang/languages").json()}
    assert by_code["arabe"]["rtl"] is True
    assert by_code["hébreu"]["rtl"] is True
    assert by_code["mandarin"]["rtl"] is False
    assert by_code["anglais"]["rtl"] is False
    assert by_code["mandarin"]["script"] == "hanzi"


# ── Taxonomie de scripts (helpers déterministes, sans DB) ─────────────────────

def test_script_predicates():
    # Logographiques : caractères enseignés en continu.
    assert script_is_continuous("mandarin") is True
    assert script_is_continuous("japonais") is True
    assert script_is_continuous("russe") is False
    # Droite-à-gauche.
    assert script_is_rtl("arabe") is True
    assert script_is_rtl("hébreu") is True
    assert script_is_rtl("anglais") is False
    # Tons : portés par le script (hanzi/thaï) OU par la langue (vietnamien latin).
    assert script_is_tonal("mandarin") is True
    assert script_is_tonal("thaï") is True
    assert script_is_tonal("vietnamien") is True
    assert script_is_tonal("russe") is False


def test_script_meta_kinds():
    assert get_script_meta("arabe")["kind"] == "abjad"
    assert get_script_meta("mandarin")["kind"] == "logographic"
    assert get_script_meta("hindi")["kind"] == "abugida"
    # Repli sans exception pour une langue inconnue.
    assert get_script_meta("klingon")["kind"] == "alphabetic"


def test_writing_phase_longer_for_logographic():
    # L'amorce d'écriture est plus longue pour un script logographique (caractères
    # en nombre ouvert) que pour un alphabet fini.
    assert writing_to_passive("mandarin") == 12
    assert writing_to_passive("japonais") == 12
    assert writing_to_passive("russe") == 6
    assert writing_to_passive("grec") == 6


# ── Phase d'écriture & profil ─────────────────────────────────────────────────

def test_mandarin_starts_in_writing_phase(client):
    client.post("/api/lang/placement/skip", json={"language": "mandarin"})
    body = client.get("/api/lang/profile", params={"language": "mandarin"}).json()
    assert body["script"] == "hanzi"
    assert body["tonal"] is True
    assert body["profile"]["phase"] == "writing"


def test_profile_exposes_rtl(client):
    body = client.get("/api/lang/profile", params={"language": "arabe"}).json()
    assert body["script"] == "arabic"
    assert body["rtl"] is True
    assert body["script_kind"] == "abjad"


# ── Introduction continue des caractères (cœur de la refonte) ─────────────────

def test_continuous_script_injects_writing_slot_in_passive(client, monkeypatch):
    """Un script logographique garde un slot « nouveaux caractères » même en phase
    passive ; un alphabet fini (russe) n'en a pas."""
    monkeypatch.setattr("services.lang_sequencer.plan_lesson_async", _fake_plan)
    from db.lang_db import get_or_create_lang_profile, update_lang_profile
    from services.lang_sequencer import plan_lesson

    man = get_or_create_lang_profile(1, "mandarin")
    update_lang_profile(man["id"], phase="passive", touch_last_session=False)
    man = get_or_create_lang_profile(1, "mandarin")
    man_kinds = [s["render_kind"] for s in plan_lesson(man)["slots"]]
    assert "writing" in man_kinds  # caractères enseignés en continu

    rus = get_or_create_lang_profile(1, "russe")
    update_lang_profile(rus["id"], phase="passive", touch_last_session=False)
    rus = get_or_create_lang_profile(1, "russe")
    rus_kinds = [s["render_kind"] for s in plan_lesson(rus)["slots"]]
    assert "writing" not in rus_kinds  # alphabet fini : plus de slot d'écriture
