# Simulation longue du feuilleton (plan V13), version courte pour la suite.
#
# tools/simulate_lang_feuilleton.py rejoue des mois d'apprentissage avec des
# épisodes synthétiques ; ici, 150 jours pour deux profils d'apprenant. C'est
# cette simulation qui a trouvé le dépassement du plafond de cartes après une
# longue absence (contrôle sur cartes + étape cartes).
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

from config.settings import LANG_DUE_CARDS_CAP, LANG_MAX_CONSECUTIVE_RESPIRATION  # noqa: E402
from simulate_lang_feuilleton import simulate  # noqa: E402


@pytest.fixture(scope="module")
def reports(tmp_path_factory):
    import db

    base = tmp_path_factory.mktemp("sim")
    out = {kind: simulate("espagnol", 150, kind, seed=3, db_path=base / f"{kind}.db") for kind in ("aise", "difficulte")}
    db.close_connection()
    return out


@pytest.mark.parametrize("kind", ["aise", "difficulte"])
def test_difficulty_stays_within_its_bounds(reports, kind):
    r = reports[kind]
    assert r["ladder_jump_ok"] and r["out_of_band_episodes"] == []
    assert r["max_consecutive_respirations"] <= LANG_MAX_CONSECUTIVE_RESPIRATION


@pytest.mark.parametrize("kind", ["aise", "difficulte"])
def test_every_mode_of_the_rhythm_appears(reports, kind):
    r = reports[kind]
    assert r["modes"]["zero"] == 1 and r["modes"]["bilan"] >= 3
    assert r["steps"].get("jalon", 0) >= 1


def test_long_absences_bring_reprises(reports):
    # Seul le profil « difficulte » s'absente longtemps avec cette graine.
    assert reports["difficulte"]["modes"].get("reprise", 0) >= 1
    assert reports["difficulte"]["steps"].get("controle", 0) + reports["difficulte"]["modes"]["reprise"] >= 1


def test_the_second_wave_starts_after_episode_fifty(reports):
    assert reports["aise"]["episodes_played"] >= 50
    assert reports["aise"]["steps"].get("deuxieme_vague", 0) > 0


@pytest.mark.parametrize("kind", ["aise", "difficulte"])
def test_due_cards_never_exceed_the_cap(reports, kind):
    assert reports[kind]["max_cards_per_run"] <= LANG_DUE_CARDS_CAP


def test_the_comfortable_learner_goes_further(reports):
    easy, hard = reports["aise"], reports["difficulte"]
    assert easy["program_order"] > hard["program_order"]
    assert hard["respirations"] > easy["respirations"]
    assert len(easy["games"]) >= 5 and len(easy["formats"]) >= 2
