"""Load clinical rules from a disease workbook.

The workbook is the single source of truth. Where a cell the FSM needs is
still blank (an open Verify_Flags item), the loader falls back to the
matching PLACEHOLDER in config.py and records that it did so, so nothing
silently pretends to be sourced.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from emergisim import config


@lru_cache(maxsize=None)
def load_sheet(path: Path, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet, header=0, engine="openpyxl")
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _blank(value) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == ""


def _split_states(cell) -> list[str]:
    return [s.strip() for s in str(cell).split(";") if s.strip()]


@dataclass(frozen=True)
class SourcedValue:
    value: float
    provenance: str  # "SOURCE: <sheet>.<column>" or "PLACEHOLDER: <flag>"

    @property
    def is_placeholder(self) -> bool:
        return self.provenance.startswith("PLACEHOLDER")


@dataclass(frozen=True)
class Contraindication:
    id: str
    action: str
    applies_in_states: tuple[str, ...]
    condition_note: str
    penalty_s: SourcedValue


def load_contraindications(path: Path = config.ANAPHYLAXIS_XLSX) -> dict[str, Contraindication]:
    df = load_sheet(path, "Contraindicated")
    out = {}
    for _, row in df.iterrows():
        cid = str(row["id"]).strip()
        raw = row.get("time_penalty_seconds")
        if _blank(raw):
            penalty = SourcedValue(
                float(config.CONTRAINDICATION_PENALTY_FALLBACK_S[cid]),
                "PLACEHOLDER: F-24 open, expert value required",
            )
        else:
            penalty = SourcedValue(float(raw), "SOURCE: Contraindicated.time_penalty_seconds")
        out[cid] = Contraindication(
            id=cid,
            action=str(row["action"]),
            applies_in_states=tuple(_split_states(row["applies_in_states"])),
            condition_note="" if _blank(row.get("condition_note")) else str(row["condition_note"]),
            penalty_s=penalty,
        )
    return out


@dataclass(frozen=True)
class Transition:
    from_state: str
    trigger_type: str
    requirement: str
    to_state: str
    timer_s: SourcedValue | None  # None for action-triggered transitions


def load_transitions(path: Path = config.ANAPHYLAXIS_XLSX) -> list[Transition]:
    df = load_sheet(path, "Transitions")
    out = []
    for _, row in df.iterrows():
        trigger = str(row["trigger_type"]).strip()
        from_state = str(row["from_state"]).strip()
        timer = None
        if trigger in ("timer_expiry", "no_action"):
            raw = row.get("base_timer_seconds")
            if _blank(raw):
                timer = SourcedValue(
                    float(config.PACING_WINDOW_FALLBACK_S[from_state]),
                    "PLACEHOLDER: F-23 open, team/expert value required",
                )
            else:
                timer = SourcedValue(float(raw), "SOURCE: Transitions.base_timer_seconds")
        # "scenario_end (mortality logged)" -> "scenario_end"
        to_state = str(row["to_state"]).split("(")[0].strip()
        out.append(Transition(from_state, trigger, str(row["required_or_condition"]), to_state, timer))
    return out


@dataclass(frozen=True)
class WormModifier:
    cofactor: str
    category: str
    odds_ratio: float
    ci: str
    significant: bool  # 95% CI excludes 1


_CI_RE = re.compile(r"\(?(-?\d+(?:\.\d+)?)\)?\s*-\s*(\d+(?:\.\d+)?)")


def _ci_excludes_one(ci: str) -> bool:
    if "not sig" in ci.lower():
        return False
    m = _CI_RE.search(ci)
    if not m:
        return False
    lo, hi = float(m.group(1)), float(m.group(2))
    return not (lo <= 1.0 <= hi)


def load_worm2018(path: Path = config.ANAPHYLAXIS_XLSX, model: str = config.WORM_MODEL) -> dict[str, WormModifier]:
    """SOURCE: Worm et al. 2018, Allergy 73(6):1322-1330, Table 1 (Worm2018_Modifiers sheet).

    Rows the chosen model marks 'Not used' are skipped (no effect), rather than
    borrowing the other model's OR.
    """
    if model not in ("RingMessmer", "NIAID_FAAN"):
        raise ValueError(f"unknown Worm 2018 model: {model}")
    df = load_sheet(path, "Worm2018_Modifiers")
    out = {}
    for _, row in df.iterrows():
        or_raw, ci_raw = row.get(f"OR_{model}"), row.get(f"CI_{model}")
        if _blank(or_raw) or str(ci_raw).strip().lower() == "not used":
            continue
        ci = "" if _blank(ci_raw) else str(ci_raw)
        name = str(row["cofactor"]).strip()
        out[name] = WormModifier(name, str(row["category"]).strip(), float(or_raw), ci, _ci_excludes_one(ci))
    return out
