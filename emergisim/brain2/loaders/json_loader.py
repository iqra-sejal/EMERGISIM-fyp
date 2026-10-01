"""MIMIC-IV-ED loading and vitals derivation (TECHNICAL_SPEC section 3).

Pipeline:
  1. One time-ordered vitals series per stay: the triage row (taken at ED
     intime) plus every vitalsign row.
  2. Forward- then backward-fill each vital within the stay, capped at
     VITALS_FILL_LIMIT_HOURS. Filling never looks at the state, so the state
     labels cannot leak into the values (no circular filling).
  3. Classify each row with the WAO thresholds (STATE_CLASSIFIER).
  4. Collapse to one median per (stay, state), then take percentiles across
     stays, so long stays with many rows do not dominate.

Everything this module returns to callers is aggregate. Record-level data
stays in memory and is never written out.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from emergisim import config

VITALS = ["heartrate", "resprate", "o2sat", "sbp", "dbp", "temperature"]

# ICD-10 codes in the extract that are anaphylaxis proper (the rest is the
# wider allergy pool: T78.1 food reaction, T78.3 angioedema, T78.4x allergy).
ANAPHYLAXIS_ICD_PREFIXES = ("T780", "T782")
FOOD_ANAPHYLAXIS_ICD_PREFIX = "T780"


def load_records(path: Path = config.ANAPHYLAXIS_MIMIC_JSON) -> list[dict]:
    if not Path(path).exists():
        raise FileNotFoundError(
            f"{path} not found. The MIMIC-IV-ED extract is local only (PhysioNet DUA); "
            "copy it into data/ to run the derivation."
        )
    # The extract contains bare NaN tokens, which Python's json accepts.
    return json.loads(Path(path).read_text())


def is_confirmed_anaphylaxis(record: dict) -> bool:
    return any(d["icd_code"].startswith(ANAPHYLAXIS_ICD_PREFIXES) for d in record["diagnoses"])


def vitals_frame(records: list[dict]) -> pd.DataFrame:
    """Long frame: stay_id, charttime, is_triage, VITALS (implausible values blanked, unfilled)."""
    rows = []
    for r in records:
        stay = r["stay_id"]
        intime = pd.Timestamp(r["demographics"]["intime"])
        for t in r["triage"]:
            rows.append({"stay_id": stay, "charttime": intime, "is_triage": True, **{v: t.get(v) for v in VITALS}})
        for v in r["vitalsign_timeline"]:
            rows.append({"stay_id": stay, "charttime": pd.Timestamp(v["charttime"]), "is_triage": False,
                         **{k: v.get(k) for k in VITALS}})
    df = pd.DataFrame(rows)
    for v in VITALS:
        df[v] = pd.to_numeric(df[v], errors="coerce")
        lo, hi = config.VITALS_PLAUSIBLE[v]
        df.loc[(df[v] < lo) | (df[v] > hi), v] = np.nan
    return df.sort_values(["stay_id", "charttime", "is_triage"], ascending=[True, True, False]).reset_index(drop=True)


def _fill_group(g: pd.DataFrame, limit: pd.Timedelta) -> pd.DataFrame:
    g = g.copy()
    times = g["charttime"]
    for v in VITALS:
        s = g[v]
        have = s.notna()
        # forward fill within the time cap
        last_t = times.where(have).ffill()
        ff = s.ffill().where((times - last_t) <= limit)
        # backward fill within the time cap
        next_t = times.where(have).bfill()
        bf = s.bfill().where((next_t - times) <= limit)
        g[v] = s.fillna(ff).fillna(bf)
    return g


def fill_vitals(df: pd.DataFrame, limit_hours: float = config.VITALS_FILL_LIMIT_HOURS) -> pd.DataFrame:
    limit = pd.Timedelta(hours=limit_hours)
    parts = [_fill_group(g, limit) for _, g in df.groupby("stay_id", sort=False)]
    return pd.concat(parts, ignore_index=True)


def classify_state(sbp: float, o2sat: float, hr: float, rules: dict = config.STATE_CLASSIFIER) -> str | None:
    """WAO-threshold state for one set of vitals; None if the deciding vitals are missing."""
    if not math.isnan(sbp) and sbp < rules["collapse_sbp_below"]:
        return "cardiovascular_collapse"
    if (not math.isnan(o2sat) and o2sat < rules["airway_spo2_below"]) or (not math.isnan(hr) and hr > rules["airway_hr_above"]):
        return "airway_compromise"
    if math.isnan(sbp) or math.isnan(o2sat) or math.isnan(hr):
        return None  # cannot rule out a worse state
    return "early_reaction"


def classify(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["state"] = [classify_state(s, o, h) for s, o, h in zip(df["sbp"], df["o2sat"], df["heartrate"])]
    return df


@dataclass(frozen=True)
class StateVitals:
    state: str
    n_stays: int
    suppressed: bool
    percentiles: dict[str, dict[str, float]]  # vital -> {p25, p50, p75}


def state_vitals(df: pd.DataFrame, min_cell: int = config.MIN_CELL_SIZE) -> dict[str, StateVitals]:
    """Per-state 25th/50th/75th percentiles across per-stay medians."""
    classified = df.dropna(subset=["state"])
    per_stay = classified.groupby(["state", "stay_id"])[VITALS].median()
    out = {}
    for state in ("early_reaction", "airway_compromise", "cardiovascular_collapse"):
        if state not in per_stay.index.get_level_values(0):
            out[state] = StateVitals(state, 0, True, {})
            continue
        block = per_stay.loc[state]
        n = len(block)
        if n < min_cell:
            out[state] = StateVitals(state, n, True, {})
            continue
        pct = {}
        for v in VITALS:
            col = block[v].dropna()
            if len(col) < min_cell:
                continue
            q = np.percentile(col, [25, 50, 75])
            pct[v] = {"p25": round(float(q[0]), 1), "p50": round(float(q[1]), 1), "p75": round(float(q[2]), 1)}
        out[state] = StateVitals(state, n, False, pct)
    return out


def derive_state_vitals(records: list[dict]) -> dict[str, StateVitals]:
    return state_vitals(classify(fill_vitals(vitals_frame(records))))


def derive_stable_vitals(records: list[dict], min_cell: int = config.MIN_CELL_SIZE) -> StateVitals:
    """DERIVED target for the 'stable' state: last filled observation of stays
    discharged HOME whose last observation classifies as early_reaction (i.e.
    no remaining collapse/airway signal). WAO does not define stable vitals."""
    home = [r for r in records if r["demographics"]["disposition"] == "HOME"]
    df = classify(fill_vitals(vitals_frame(home)))
    last = df.groupby("stay_id").tail(1)
    last = last[last["state"] == "early_reaction"]
    n = len(last)
    if n < min_cell:
        return StateVitals("stable", n, True, {})
    pct = {}
    for v in VITALS:
        col = last[v].dropna()
        if len(col) >= min_cell:
            q = np.percentile(col, [25, 50, 75])
            pct[v] = {"p25": round(float(q[0]), 1), "p50": round(float(q[1]), 1), "p75": round(float(q[2]), 1)}
    return StateVitals("stable", n, False, pct)
