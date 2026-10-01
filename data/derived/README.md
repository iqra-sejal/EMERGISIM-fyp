# Derived data (committed, aggregate only)

Built from the local MIMIC-IV-ED extract by:

    python -m tools.build_anaphylaxis_derived

- `anaphylaxis_vitals.json`: per-state vital sign percentiles (p25/p50/p75), cohort sizes, feature prevalence.
- `anaphylaxis_profiles.json`: 7 synthetic patient profiles (easy/medium/hard).

The raw extract `data/Anaphylaxis_dataset.json` is covered by the PhysioNet credentialed data use agreement. It is git-ignored and must never be committed. Files here contain only aggregates, any group under 10 stays is suppressed, and there are no identifiers or timestamps. `tests/test_data_layer.py` checks this.
