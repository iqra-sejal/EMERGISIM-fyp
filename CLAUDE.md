# EMERGISIM

AI-powered ER training simulator (Bahria University FYP).

Before writing any code, read:
1. `docs/TECHNICAL_SPEC.md`: authoritative technical spec (Three-Brain separation, Anaphylaxis FSM, voice pipeline, validator, coding rules, locked vs pending decisions).
2. `docs/PROJECT_CONTEXT.md`: project background, team, scope history.

## Rules
- Brain separation is absolute: PPO = difficulty only, FSM = clinical truth, LLM = patient language only.
- Brain 3 scoring is deterministic; never score with an LLM.
- Every Claude response passes the three-check output validator before reaching the trainee.
- No hardcoded clinical values: load from the dataset; label constants SOURCE / DERIVED / PLACEHOLDER.
- Never commit MIMIC-IV-ED data (PhysioNet DUA).
- Multiplayer is out of scope; don't add or mention it.
- Don't use em dashes in written docs or responses.
- Cite every claim in academic documents; don't overclaim.
