"""Build the committed, aggregate-only derivatives of the MIMIC-IV-ED extract.

    python -m tools.build_anaphylaxis_derived

Reads   data/Anaphylaxis_dataset.json            (local only, PhysioNet DUA)
Writes  data/derived/anaphylaxis_vitals.json     (per-state percentiles)
        data/derived/anaphylaxis_profiles.json   (7 synthetic archetype profiles)

Privacy rules (the repo is public):
  * Only aggregates are written: percentiles, counts and prevalences.
  * Any aggregate over fewer than MIN_CELL_SIZE stays is suppressed.
  * No stay_id, subject_id, timestamps or record-level values are written.
  * Profiles are synthetic archetypes. No profile is a copy of a real patient.
"""
from __future__ import annotations

import json
from datetime import date

from emergisim import config
from emergisim.brain2.loaders.json_loader import (
    FOOD_ANAPHYLAXIS_ICD_PREFIX,
    derive_stable_vitals,
    derive_state_vitals,
    is_confirmed_anaphylaxis,
    load_records,
)

STATES = ("early_reaction", "airway_compromise", "cardiovascular_collapse")


def _lower(x) -> str:
    return x.lower() if isinstance(x, str) else ""


def _home_med_flags(record: dict) -> dict[str, bool]:
    etc = [_lower(m.get("etcdescription")) for m in record["home_medications"]]
    return {
        # Ophthalmic beta-blockers excluded: the cofactor of interest is systemic beta-blockade.
        "beta_blocker": any(("beta blockers" in e or "alpha-beta blockers" in e) and "ophthalmic" not in e for e in etc),
        "ace_inhibitor": any("ace inhibitor" in e for e in etc),
        "nsaid": any("nsaid" in e for e in etc),
        # DERIVED proxy: an inhaled asthma/COPD home medication. The extract's
        # diagnoses are filtered to T78 codes, so asthma cannot be read from ICD.
        "asthma_proxy": any("asthma/copd" in e for e in etc),
    }


def _prevalence(records: list[dict]) -> dict:
    n = len(records)
    counts = {"male": 0, "ambulance_arrival": 0, "food_anaphylaxis_icd": 0, "epinephrine_given_in_ed": 0,
              "admitted": 0, "beta_blocker": 0, "ace_inhibitor": 0, "nsaid": 0, "asthma_proxy": 0}
    for r in records:
        demo = r["demographics"]
        counts["male"] += demo["gender"] == "M"
        counts["ambulance_arrival"] += demo["arrival_transport"] in ("AMBULANCE", "HELICOPTER")
        counts["food_anaphylaxis_icd"] += any(d["icd_code"].startswith(FOOD_ANAPHYLAXIS_ICD_PREFIX) for d in r["diagnoses"])
        counts["epinephrine_given_in_ed"] += any("epinephr" in _lower(m["name"]) for m in r["medications_given"])
        counts["admitted"] += demo["disposition"] == "ADMITTED"
        for k, v in _home_med_flags(r).items():
            counts[k] += v
    out = {}
    for k, c in counts.items():
        if c < config.MIN_CELL_SIZE:
            out[k] = {"n": f"<{config.MIN_CELL_SIZE}", "pct": None}
        else:
            out[k] = {"n": int(c), "pct": round(100 * c / n, 1)}
    return {"n_stays": n, "features": out}


def _vitals_block(sv) -> dict:
    return {"n_stays": sv.n_stays if not sv.suppressed else f"<{config.MIN_CELL_SIZE}" if sv.n_stays else 0,
            "suppressed": sv.suppressed, "percentiles": sv.percentiles}


def build_vitals(records: list[dict]) -> dict:
    confirmed = [r for r in records if is_confirmed_anaphylaxis(r)]
    pool_sv = derive_state_vitals(records)
    conf_sv = derive_state_vitals(confirmed)
    stable = derive_stable_vitals(confirmed)
    if stable.suppressed:
        stable = derive_stable_vitals(records)
        stable_cohort = "allergy_pool"
    else:
        stable_cohort = "confirmed_anaphylaxis"

    recommended = {}
    for s in STATES:
        use_conf = not conf_sv[s].suppressed
        chosen = conf_sv[s] if use_conf else pool_sv[s]
        recommended[s] = {"cohort": "confirmed_anaphylaxis" if use_conf else "allergy_pool", **_vitals_block(chosen)}
    recommended["stable"] = {"cohort": stable_cohort, **_vitals_block(stable)}

    return {
        "description": "Per-state vital sign percentiles derived from MIMIC-IV-ED (aggregate only). "
                       "Vitals_Template min/max = p25/p75; physiology targets = p50.",
        "generated": date.today().isoformat(),
        "method": {
            "classifier": config.STATE_CLASSIFIER,
            "fill": f"per-stay forward then backward fill, capped at {config.VITALS_FILL_LIMIT_HOURS} h, state-blind",
            "aggregation": "median per (stay, state), then 25th/50th/75th percentile across stays",
            "stable": "last observation of stays discharged HOME that classify as early_reaction (DERIVED; WAO gives no stable vitals)",
            "min_cell_size": config.MIN_CELL_SIZE,
            "cohorts": {
                "confirmed_anaphylaxis": "ICD-10 T78.0x or T78.2 on any diagnosis",
                "allergy_pool": "all 1056 stays in the extract (T78.x allergy case pool)",
            },
        },
        "recommended": recommended,
        "by_cohort": {
            "confirmed_anaphylaxis": {s: _vitals_block(conf_sv[s]) for s in STATES},
            "allergy_pool": {s: _vitals_block(pool_sv[s]) for s in STATES},
        },
        "prevalence": {
            "confirmed_anaphylaxis": _prevalence(confirmed),
            "allergy_pool": _prevalence(records),
        },
    }


# --------------------------------------------------------------------------- profiles
# Design choices per profile. Clinical fields follow Patient_Profile_Schema.
# age_years / weight_kg: PLACEHOLDER (not in MIMIC-IV-ED; team to confirm or
# derive from MIMIC-IV hosp.patients.anchor_age via subject_id).
PROFILE_SPECS = [
    {"profile_id": "ANA-P1", "difficulty": "easy", "start_state": "early_reaction", "sex": "female",
     "age_years": 24, "weight_kg": 60, "trigger_group": "food", "trigger_item": "peanut",
     "evidence_features": ["food_anaphylaxis_icd"],
     "rationale": "Most common confirmed presentation: food-triggered, early state, no cofactors."},
    {"profile_id": "ANA-P2", "difficulty": "easy", "start_state": "early_reaction", "sex": "female",
     "age_years": 19, "weight_kg": 58, "trigger_group": "food", "trigger_item": "tree nut",
     "prior_anaphylaxis": True, "has_epinephrine_autoinjector": True,
     "evidence_features": ["food_anaphylaxis_icd"],
     "rationale": "Known allergy with an auto-injector; a cooperative historian."},
    {"profile_id": "ANA-P3", "difficulty": "medium", "start_state": "early_reaction", "sex": "female",
     "age_years": 33, "weight_kg": 65, "trigger_group": "food", "trigger_item": "shellfish",
     "concomitant_diseases": ["asthma"], "evidence_features": ["asthma_proxy"],
     "rationale": "Asthma raises severity odds (Worm 2018, R&M OR 1.425) and adds early wheeze."},
    {"profile_id": "ANA-P4", "difficulty": "medium", "start_state": "airway_compromise", "sex": "female",
     "age_years": 41, "weight_kg": 70, "trigger_group": "food", "trigger_item": "sesame",
     "arrival_transport": "AMBULANCE", "evidence_features": ["ambulance_arrival"],
     "rationale": "Starts one state further on: less time before collapse."},
    {"profile_id": "ANA-P5", "difficulty": "hard", "start_state": "airway_compromise", "sex": "male",
     "age_years": 52, "weight_kg": 85, "trigger_group": "drug", "trigger_item": "antibiotic",
     "concomitant_diseases": ["asthma"], "cofactors": ["psychological burden"],
     "arrival_transport": "AMBULANCE", "evidence_features": ["asthma_proxy", "male", "ambulance_arrival"],
     "rationale": "Several significant Worm 2018 modifiers stack (male, asthma, drug elicitor, psychological burden)."},
    {"profile_id": "ANA-P6", "difficulty": "hard", "start_state": "cardiovascular_collapse", "sex": "female",
     "age_years": 67, "weight_kg": 74, "trigger_group": "drug", "trigger_item": "NSAID",
     "on_beta_blocker": True, "concurrent_medication": ["beta-blockers", "ACE inhibitor", "NSAIDs"],
     "collapse_variant": "conscious_hypotensive", "arrival_transport": "AMBULANCE",
     "evidence_features": ["beta_blocker", "ace_inhibitor", "nsaid", "ambulance_arrival"],
     "rationale": "Beta-blocker blunts the epinephrine response; the refractory pathway and glucagon become relevant (RCUK p.39)."},
    {"profile_id": "ANA-P7", "difficulty": "hard", "start_state": "cardiovascular_collapse", "sex": "male",
     "age_years": 74, "weight_kg": 80, "trigger_group": "drug", "trigger_item": "IV contrast",
     "on_beta_blocker": True, "concurrent_medication": ["beta-blockers"],
     "collapse_variant": "unconscious", "arrival_transport": "AMBULANCE",
     "evidence_features": ["beta_blocker", "male", "ambulance_arrival"],
     "rationale": "Unconscious collapse: no history from the patient, arrest risk, elderly (WAO Fig. 3)."},
]

_VITAL_KEYS = {"heartrate": "hr", "resprate": "rr", "o2sat": "spo2", "sbp": "sbp", "dbp": "dbp", "temperature": "temp_f"}


def build_profiles(vitals: dict) -> dict:
    rec = vitals["recommended"]
    prev = vitals["prevalence"]
    baseline_sbp = rec["stable"]["percentiles"]["sbp"]["p50"]  # DERIVED: stable-state median
    profiles = []
    for spec in PROFILE_SPECS:
        spec = dict(spec)
        state = spec["start_state"]
        p = rec[state]["percentiles"]
        presenting = {_VITAL_KEYS[k]: v["p50"] for k, v in p.items()}
        features = spec.pop("evidence_features")
        rationale = spec.pop("rationale")
        evidence = {
            "presenting_vitals": f"p50 of {state} ({rec[state]['cohort']}, n_stays={rec[state]['n_stays']})",
            "baseline_sbp": "p50 of derived stable vitals",
            "age_weight": "PLACEHOLDER: not in MIMIC-IV-ED",
            "feature_prevalence_allergy_pool": {f: prev["allergy_pool"]["features"][f] for f in features},
            "rationale": rationale,
        }
        profiles.append({**spec, "baseline_sbp": baseline_sbp, "presenting_vitals": presenting, "evidence": evidence})
    return {
        "description": "Synthetic anaphylaxis patient profiles. Vitals and prevalence evidence are MIMIC-IV-ED "
                       "aggregates; identities are invented. No profile corresponds to a real patient.",
        "generated": vitals["generated"],
        "profiles": profiles,
    }


def main() -> None:
    records = load_records()
    vitals = build_vitals(records)
    profiles = build_profiles(vitals)
    config.DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    (config.DERIVED_DIR / "anaphylaxis_vitals.json").write_text(json.dumps(vitals, indent=2) + "\n")
    (config.DERIVED_DIR / "anaphylaxis_profiles.json").write_text(json.dumps(profiles, indent=2) + "\n")
    print("wrote", config.DERIVED_DIR / "anaphylaxis_vitals.json")
    print("wrote", config.DERIVED_DIR / "anaphylaxis_profiles.json")


if __name__ == "__main__":
    main()
