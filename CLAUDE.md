# EMERGISIM

AI-powered ER training simulator (Bahria University FYP). Read `docs/PROJECT_CONTEXT.md` before starting any work. It holds the architecture (Three-Brain System), dataset, scope decisions and open items.

## Rules
- Never commit MIMIC-IV-ED data (PhysioNet DUA).
- Brain 3 (evaluation) must stay deterministic; never score with an LLM.
- LLM patient responses must be grounded in the dataset and constrained by the FSM state.
- Multiplayer is out of scope; don't add or mention it.
- Don't use em dashes in written docs or responses.
- Cite every claim in academic documents; don't overclaim.
