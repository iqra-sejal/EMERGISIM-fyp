"""Project-wide constants.

Every value here is labelled:
  SOURCE      clinically sourced, cited
  DERIVED     calculated from data, reasoning given
  PLACEHOLDER team/expert decision pending (open flag named)

Clinical values belong in the dataset workbook. A constant here is only a
fallback that the loaders use when the matching workbook cell is blank.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DERIVED_DIR = DATA_DIR / "derived"

ANAPHYLAXIS_XLSX = DATA_DIR / "EMERGISIM_Anaphylaxis_Dataset_FINAL_v9.xlsx"
# MIMIC-IV-ED extract: PhysioNet DUA, local only, never committed (.gitignore)
ANAPHYLAXIS_MIMIC_JSON = DATA_DIR / "Anaphylaxis_dataset.json"

# ---------------------------------------------------------------- Brain 1
BRAIN1_MODE = "placeholder"  # "placeholder" (rule-based adapter) or "ppo"
BRAIN1_MULTIPLIER_RANGE = (0.5, 2.0)  # SOURCE: TECHNICAL_SPEC section 2 (design range)

# ---------------------------------------------------------------- Brain 2 LLM
LLM_MODEL = "claude-sonnet-4-20250514"  # PLACEHOLDER: re-evaluate against current models (spec 14.4)
LLM_MAX_TOKENS = 200  # SOURCE: TECHNICAL_SPEC section 7
LLM_HISTORY_PAIRS = 5  # SOURCE: TECHNICAL_SPEC section 7

# ---------------------------------------------------------------- Voice
WHISPER_CONFIDENCE_THRESHOLD = 0.6  # SOURCE: project specification (proposal)

# ---------------------------------------------------------------- Pacing (F-23)
# PLACEHOLDER: base pacing window per state; expert validation required (F-23 open).
# Used only while Transitions.base_timer_seconds is blank in the workbook.
PACING_WINDOW_FALLBACK_S = {
    "early_reaction": 60,
    "airway_compromise": 45,
    "cardiovascular_collapse": 30,
}

# ---------------------------------------------------------------- Contraindications (F-24)
# PLACEHOLDER: timer penalty per contraindicated action; expert validation required (F-24 open).
# No guideline gives a numeric value (Verify_Flags F-24). Used only while
# Contraindicated.time_penalty_seconds is blank in the workbook.
CONTRAINDICATION_PENALTY_FALLBACK_S = {"C-01": 20, "C-02": 15, "C-03": 25, "C-04": 20}

# ---------------------------------------------------------------- Response model (D1, Worm 2018)
# PLACEHOLDER: base probability of adequate response to one IM epinephrine dose;
# expert validation required. Anchored on WAO G-10 "most respond to 1-2 doses".
RESPONSE_BASE_PROBABILITY = 0.82
# PLACEHOLDER: damping k in p = p / (1 + (OR - 1) * k); design choice, expert validation required.
RESPONSE_OR_DAMPING = 0.3
# PLACEHOLDER: second-dose multiplier (diminishing returns); expert validation required.
RESPONSE_SECOND_DOSE_FACTOR = 0.7
# PLACEHOLDER: which Worm 2018 Table 1 model to read ("RingMessmer" or "NIAID_FAAN").
# Ring & Messmer is a severity grading, closer to what the response model scales.
WORM_MODEL = "RingMessmer"
# PLACEHOLDER: reference age for the per-year OR (effect = OR ** (age - ref)).
WORM_AGE_REFERENCE_YEARS = 30
RESPONSE_PROBABILITY_BOUNDS = (0.05, 0.99)  # DERIVED: keeps the model stochastic at both ends

# ---------------------------------------------------------------- Physiology
RECOVERY_RATE = 0.4  # PLACEHOLDER: per reassessment tick; expert validation required
DETERIORATION_RATE = 0.6  # PLACEHOLDER: per expired pacing window; expert validation required
ARREST_SBP_THRESHOLD = 50  # PLACEHOLDER: mmHg design threshold; expert validation required

# ---------------------------------------------------------------- MIMIC vitals derivation
# SOURCE: WAO 2020 Table 2 fn a (adult hypotension SBP < 90); the SpO2/HR cut-offs
# are the team's airway-compromise proxy (TECHNICAL_SPEC section 3).
STATE_CLASSIFIER = {"collapse_sbp_below": 90, "airway_spo2_below": 92, "airway_hr_above": 120}
VITALS_FILL_LIMIT_HOURS = 8  # SOURCE: TECHNICAL_SPEC section 3
# DERIVED: physiological plausibility window; values outside are charting
# artifacts (e.g. SBP 0-20 from a failed cuff read) and are set to missing
# before filling. Bounds are generous so real extremes survive.
VITALS_PLAUSIBLE = {
    "heartrate": (20, 250),
    "resprate": (4, 60),
    "o2sat": (50, 100),
    "sbp": (40, 260),
    "dbp": (20, 180),
    "temperature": (90, 110),  # Fahrenheit, as charted in MIMIC-IV-ED
}
# DERIVED: suppress any aggregate built from fewer than this many stays, so no
# published statistic describes an identifiable small group (repo is public).
MIN_CELL_SIZE = 10

# ---------------------------------------------------------------- Brain 3
# PLACEHOLDER: tier weights; expert validation required.
BRAIN3_WEIGHTS = {
    "correct": 1.0,
    "supportive": 0.4,
    "conditional": 0.6,
    "neutral": 0.0,
    "contraindicated": -0.5,
}

# ---------------------------------------------------------------- Brain 1 reward (generic, spec section 2)
# PLACEHOLDER: reward values; team decision.
REWARD_KEY_INTERVENTION_IN_TIME = 1.0
REWARD_SCENARIO_END = -1.0
REWARD_PER_CONTRAINDICATION = -0.3
