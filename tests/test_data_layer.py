import json

import pytest

from emergisim import config
from emergisim.brain2.anaphylaxis.profile import load_profiles
from emergisim.brain2.anaphylaxis.response_model import applicable_modifiers, response_probability
from emergisim.brain2.loaders.excel_loader import (
    _ci_excludes_one,
    load_contraindications,
    load_transitions,
    load_worm2018,
)
from emergisim.brain2.loaders.json_loader import classify_state

NAN = float("nan")


def test_contraindications_fall_back_to_labelled_placeholder():
    c = load_contraindications()
    assert set(c) == {"C-01", "C-02", "C-03", "C-04"}
    assert "early_reaction" not in c["C-02"].applies_in_states
    for item in c.values():  # F-24 still open: every penalty must say so
        assert item.penalty_s.is_placeholder


def test_transition_timers_are_labelled():
    timed = [t for t in load_transitions() if t.timer_s is not None]
    assert {t.from_state for t in timed} == {"early_reaction", "airway_compromise", "cardiovascular_collapse"}
    assert all(t.timer_s.is_placeholder for t in timed)  # F-23 still open


def test_worm_ci_parsing():
    assert _ci_excludes_one("1.614-2.226")
    assert not _ci_excludes_one("0.317-1.451 (not significant)")
    assert not _ci_excludes_one("(-0.138)-1.183 (coef CI, not sig.)")
    assert _ci_excludes_one("0.582-0.932")


def test_worm_reads_sheet_values():
    rm = load_worm2018(model="RingMessmer")
    assert rm["Beta-blocker intake"].odds_ratio == pytest.approx(1.857)
    assert "ACE-I intake" not in rm  # 'Not used' in Ring & Messmer
    niaid = load_worm2018(model="NIAID_FAAN")
    assert "Beta-blocker intake" not in niaid


def test_classifier_thresholds():
    assert classify_state(85, 99, 80) == "cardiovascular_collapse"
    assert classify_state(120, 90, 80) == "airway_compromise"
    assert classify_state(120, 98, 125) == "airway_compromise"
    assert classify_state(120, 98, 80) == "early_reaction"
    assert classify_state(NAN, 98, 80) is None


def test_profiles_load_and_cover_difficulties():
    profiles = load_profiles()
    assert 6 <= len(profiles) <= 7
    assert {p.difficulty for p in profiles} == {"easy", "medium", "hard"}
    assert {p.start_state for p in profiles} >= {"early_reaction", "airway_compromise", "cardiovascular_collapse"}


def test_harder_profiles_respond_less():
    table = load_worm2018()
    by_id = {p.profile_id: p for p in load_profiles()}
    p_easy = response_probability(by_id["ANA-P1"], 1, table)
    p_hard = response_probability(by_id["ANA-P7"], 1, table)
    assert p_hard < p_easy
    assert response_probability(by_id["ANA-P1"], 2, table) < p_easy
    lo, hi = config.RESPONSE_PROBABILITY_BOUNDS
    assert all(lo <= response_probability(p, 1, table) <= hi for p in by_id.values())


def test_only_significant_modifiers_apply():
    table = load_worm2018()
    for p in load_profiles():
        assert all(m.significant for m, _ in applicable_modifiers(p, table))


@pytest.mark.parametrize("name", ["anaphylaxis_vitals.json", "anaphylaxis_profiles.json"])
def test_committed_derivatives_hold_no_record_identifiers(name):
    text = (config.DERIVED_DIR / name).read_text()
    for banned in ("stay_id", "subject_id", "hadm_id", "charttime", "intime"):
        assert banned not in text
    data = json.loads(text)

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("n", "n_stays") and isinstance(v, int):
                    assert v >= config.MIN_CELL_SIZE, f"small cell {k}={v}"
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data)
