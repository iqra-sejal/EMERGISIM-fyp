"""Patient profiles (fields follow the Patient_Profile_Schema sheet)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from emergisim import config

PROFILES_JSON = config.DERIVED_DIR / "anaphylaxis_profiles.json"


@dataclass(frozen=True)
class PatientProfile:
    profile_id: str
    difficulty: str  # easy / medium / hard
    start_state: str
    sex: str  # "female" / "male"
    age_years: int  # PLACEHOLDER per profile: MIMIC-IV-ED has no age (see profiles README)
    weight_kg: float  # PLACEHOLDER per profile: MIMIC-IV-ED has no weight
    baseline_sbp: float
    presenting_vitals: dict[str, float]
    trigger_group: str  # food / insect venom / drug / other / idiopathic
    trigger_item: str
    cofactors: tuple[str, ...] = ()
    concomitant_diseases: tuple[str, ...] = ()
    concurrent_medication: tuple[str, ...] = ()
    on_beta_blocker: bool = False
    mast_cell_disorder: bool = False
    collapse_variant: str = "conscious_hypotensive"
    pregnant: bool = False
    paediatric_variant: bool = False
    skin_signs_present: bool = True
    prior_anaphylaxis: bool = False
    has_epinephrine_autoinjector: bool = False
    arrival_transport: str = "WALK IN"
    evidence: dict = field(default_factory=dict)


def load_profiles(path: Path = PROFILES_JSON) -> list[PatientProfile]:
    raw = json.loads(Path(path).read_text())
    out = []
    for p in raw["profiles"]:
        p = dict(p)
        for k in ("cofactors", "concomitant_diseases", "concurrent_medication"):
            p[k] = tuple(p.get(k, ()))
        out.append(PatientProfile(**p))
    return out
