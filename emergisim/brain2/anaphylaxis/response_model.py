"""Response probability for IM epinephrine (ANA-004). Decision D1, Option C.

Odds ratios come from the Worm2018_Modifiers sheet, never from code.

Modelling note: Worm et al. (2018) Table 1 reports odds of a *severe*
reaction, not odds of non-response to epinephrine. Using them to lower the
response probability is a design assumption (damping k = RESPONSE_OR_DAMPING),
to be stated as such in the report and validated by the expert.
"""
from __future__ import annotations

import random

from emergisim import config
from emergisim.brain2.anaphylaxis.profile import PatientProfile
from emergisim.brain2.loaders.excel_loader import WormModifier, load_worm2018

# Profile attribute -> Worm2018_Modifiers.cofactor row
_ELICITOR_ROWS = {"food": "Food as elicitor", "drug": "Drugs as elicitor", "insect venom": "Insects as elicitor"}


def applicable_modifiers(profile: PatientProfile, table: dict[str, WormModifier]) -> list[tuple[WormModifier, float]]:
    """Return (modifier, exponent) pairs that apply to this profile.

    Only modifiers whose 95% CI excludes 1 are used.
    """
    hits: list[tuple[str, float]] = []
    hits.append(("Age (per year)", profile.age_years - config.WORM_AGE_REFERENCE_YEARS))
    if profile.sex == "male":
        hits.append(("Male sex", 1))
    if profile.mast_cell_disorder:
        hits.append(("Concomitant mastocytosis", 1))
    if "asthma" in profile.concomitant_diseases:
        hits.append(("Concomitant asthma", 1))
    if "thyroid disease" in profile.concomitant_diseases:
        hits.append(("Concomitant thyroid disease", 1))
    if "psychological burden" in profile.cofactors:
        hits.append(("Psychological burden", 1))
    for level in ("mild", "moderate", "vigorous"):
        if f"{level} exercise" in profile.cofactors:
            hits.append((f"{level.capitalize()} exercise", 1))
    if profile.on_beta_blocker:
        hits.append(("Beta-blocker intake", 1))
    if "ACE inhibitor" in profile.concurrent_medication:
        hits.append(("ACE-I intake", 1))
    if profile.trigger_group in _ELICITOR_ROWS:
        hits.append((_ELICITOR_ROWS[profile.trigger_group], 1))

    return [(table[name], exp) for name, exp in hits if name in table and table[name].significant and exp]


def response_probability(profile: PatientProfile, dose_number: int, table: dict[str, WormModifier] | None = None) -> float:
    table = table if table is not None else load_worm2018()
    p = config.RESPONSE_BASE_PROBABILITY
    k = config.RESPONSE_OR_DAMPING
    for mod, exponent in applicable_modifiers(profile, table):
        odds_ratio = mod.odds_ratio ** exponent
        p = p / (1 + (odds_ratio - 1) * k)
    if dose_number >= 2:
        p *= config.RESPONSE_SECOND_DOSE_FACTOR
    lo, hi = config.RESPONSE_PROBABILITY_BOUNDS
    return min(hi, max(lo, p))


def responds(profile: PatientProfile, dose_number: int, rng: random.Random | None = None) -> bool:
    rng = rng or random
    return rng.random() < response_probability(profile, dose_number)
