# EMERGISIM: Project Context

Full title: **EmergiSim: A Virtual AI-Powered Environment for Emergency Response Education**

Recovered from the team's Claude project memory (project "FYP", last updated 2026-09-25). Background and history only. The authoritative technical spec is `docs/TECHNICAL_SPEC.md`; where they disagree, the spec wins.

## Team

| Role | Name |
|---|---|
| Lead (technical decisions, documentation) | Iqra Sejal |
| Dataset pipeline lead | Javeria Shahzad |
| Member | Abeer Asif |
| Supervisor | Ms. Salas Akbar (also spelled "Akhbar" in some notes; confirm spelling) |

Institution: Computer Science Dept, Bahria University Karachi.
Proposal defence score: **8.5 / 10**.
Timeline (Gantt chart): **Sep 2026 to Apr 2027**.

## Goal

An AI-powered emergency room training simulator for medical staff. It simulates four emergency diseases with adaptive AI patients, real-time difficulty control and automated clinical evaluation, to build trainees' cognitive emergency response skills.

## Disease scope

| Disease | ICD-10 codes |
|---|---|
| Myocardial Infarction (MI) | I21.x |
| Anaphylaxis | T78.2 |
| Hypoglycemia | E11.649, E16.0 |
| Hyperglycemia | E11.65, E13.10 |

Justification: the SALT triage framework (Way et al., 2024; Oh and Jung, 2024) supports the four-disease cognitive skill mapping.

## Architecture: Three-Brain System

### Brain 1: Adaptive difficulty (Reinforcement Learning)
- PPO via Stable-Baselines3.
- Environment: `SimulatedEREnvironment`, using the Gymnasium interface.
- Curriculum learning (Bengio et al., 2009) addresses the cold-start problem.
- PPO was chosen over DQN and A3C, with the architectural justification written up in the documentation.

### Brain 2: Patient behaviour (FSM + LLM hybrid)
- Python `transitions` library; **4 parallel FSM instances**.
- FSM states are **one-hot encoded** to avoid categorical ambiguity.
- The FSM drives the simulated vitals; the LLM produces patient dialogue constrained by the FSM state.
- LLM backbone: Claude API (`claude-sonnet-4-20250514`), chosen based on the AgentClinic benchmark.

### Brain 3: Evaluation (deterministic)
- Scoring is deterministic and based on trainee **action IDs**, which removes the risk of hallucinated grades.
- Claude writes only the narrative feedback, not the score.
- **6 metrics**; validated with **Pearson r**.

## Tech stack

- Backend: FastAPI + WebSocket
- Voice: OpenAI Whisper API, filtering at a 0.6 confidence threshold (also used for hesitation/confidence analysis)
- RL: Gymnasium, Stable-Baselines3
- FSM: Python `transitions`
- LLM: Claude API
- Frontend: Unity + WebXR (VR is kept low-profile in documents for now)
- Training: Google Colab Pro

## Dataset

A merge of two sources:

1. **Clinical guidelines** (ESC / WAO / ADA), extracted into structured Excel through clinical protocol extraction.
2. **MIMIC-IV-ED** (full access confirmed), filtered by the ICD-10 codes above.

MIMIC-IV-ED tables in use:

| Table | Columns |
|---|---|
| edstays | subject_id, hadm_id, stay_id, intime, outtime, gender, race, arrival_transport, disposition |
| triage | stay_id, heartrate, resprate, o2sat, sbp, dbp, temperature, pain, acuity, chiefcomplaint |
| vitalsign | stay_id, charttime, heartrate, resprate, o2sat, sbp, dbp, temperature, pain, rhythm |
| diagnosis | stay_id, seq_num, icd_code, icd_version, icd_title |
| medrecon | stay_id, charttime, name, gsn, ndc, etcname |
| pyxis | stay_id, charttime, name, gsn |

Note: MIMIC data falls under the PhysioNet credentialed data use agreement. **Never commit raw MIMIC data to this repo.**

## Scoping decisions

- **Multiplayer: dropped entirely.** Don't mention it anywhere in the documentation.
- **VR: kept low-profile** at the proposal stage.
- Brain naming conventions may be revised later.
- Visual vitals monitor in the trainee UI: under consideration, **not decided**.

## Current state (as of late Sep 2026)

- Proposal defence passed; development is starting.
- Post-defence supervisor feedback driving current work:
  1. Unsafe LLM answers must be handled by grounding them in the dataset.
  2. The architecture diagram must follow the university's guidelines format.
  3. FSM limitations must be researched comprehensively.
- Chapter 3 (Project Methodology) of the FYP document is going through several iterations.
- Diagrams are built as HTML SVG files and have been rebuilt several times after feedback.
- Prepared: a formal logbook entry, an internal FSM research document, and a MITACS project summary.

## Open items / on the horizon

- [ ] Revise architecture diagrams to the university's formatting guidelines
- [ ] Ground LLM answers in the dataset (safety handling for unsafe answers)
- [ ] Write up FSM limitations comprehensively
- [ ] Decide on the visual vitals monitor in the trainee UI
- [ ] Possibly rename the Brains

## Principles

- **Citation discipline:** every claim is cited and verifiable; nothing is overclaimed. Writing is student-level but professionally analytical.
- **Determinism for safety:** evaluation never depends on LLM output.
- **Dataset grounding:** LLM responses are anchored to clinical data sources, not generated freely.
- **Deliberate scope management:** exclusions are decided on purpose and recorded here.
- Research artifacts come in two forms: formal (for submission) and internal (team reference).

## Key references

- Bengio et al. (2009): curriculum learning
- Way et al. (2024); Oh and Jung (2024): SALT triage framework
- AgentClinic benchmark: LLM selection

## Inconsistencies to resolve

- LLM backbone: resolved. The technical spec confirms Claude (`claude-sonnet-4-20250514`); the "Claude API/GPT-4o" wording in an older CV summary is outdated.
- `claude-sonnet-4-20250514` is an older model. Consider re-evaluating against current Claude models before implementation.
- Supervisor surname spelling: "Akbar" vs "Akhbar".
