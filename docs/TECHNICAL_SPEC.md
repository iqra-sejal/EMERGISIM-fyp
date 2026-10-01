# EMERGISIM: Complete Technical Context Document

**For Claude Code: read this entire document before writing any code.**

This is the authoritative technical specification. `docs/PROJECT_CONTEXT.md` gives the project background; where the two disagree, this document wins.

---

## 1. What this project is

EMERGISIM is an AI-powered emergency room training simulator. A single trainee uses voice commands to work with up to four AI patients who deteriorate at the same time, each simulating a different disease. The system adapts difficulty in real time based on trainee performance, generates clinically constrained patient dialogue, and produces an automated performance report at session end.

**Team:** Iqra Sejal (lead, technical decisions), Javeria Shahzad (dataset lead), Abeer Asif. Supervisor: Miss Salas Akhbar. Bahria University Karachi, BS Artificial Intelligence, 7th semester. FYP proposal defended with 8.5/10.

**Four diseases simulated:** Myocardial Infarction (ICD I21.x), Anaphylaxis (ICD T78.2), Hypoglycemia (ICD E11.649/E16.0), Hyperglycemia/DKA (ICD E11.65/E13.10).

**Target trainees:** ER nurses, junior doctors, paramedical staff.

---

## 2. The three brains: strict separation of responsibility

This is the most important architectural rule. Never mix these responsibilities.

### Brain 1: PPO Reinforcement Learning Agent

**Controls:** Difficulty parameters only. Nothing clinical.
**Library:** Stable-Baselines3, Gymnasium

**What it adjusts:**
- Timer/pacing window speed multiplier (0.5x to 2.0x)
- Number of simultaneously active patients (1 to 4)
- Hint visibility threshold
- Reassessment window duration

**What it absolutely cannot control:** Disease progression, FSM state, treatment response, arrest, physiological correctness, clinical rules.

**How it learns:** PPO (Proximal Policy Optimization). The state vector comes from the Performance Monitor. The reward signal comes from the Brain 3 summary at rollout end. Curriculum learning (Bengio et al., 2009) addresses the cold start: training begins with easy scenarios and difficulty increases as the policy improves.

**Reward signals (per rollout, not per action; disease-agnostic, see section 15):**
- +1.0 per patient whose disease's key intervention was given before that patient left its first active state (for anaphylaxis: ANA-004 while still in early_reaction)
- -1.0 if any patient reached scenario_end
- -0.3 per contraindicated action taken
- 0.0 otherwise

Values live in `config.py` (`REWARD_*`, PLACEHOLDER).

**State vector inputs from the Performance Monitor:**
- Triage accuracy (did the trainee prioritise the most critical patient)
- Response latency (time from deterioration event to first correct action)
- Protocol adherence rate per state
- Hesitation score from Whisper
- Contraindicated action count
- Current FSM state per patient (severity level, not clinical detail)

**Brain 1 placeholder (for demo without a trained PPO):** A rule-based adapter. If the trainee is performing well, increase the multiplier; if poorly, decrease it. Clearly flagged as a placeholder with a comment and a config flag `BRAIN1_MODE = "placeholder"`, which can be switched to `"ppo"` once the PPO policy is trained.

---

### Brain 2: FSM + LLM Patient Simulator

**Controls:** Clinical truth and natural language. These are separate sub-responsibilities.

**FSM sub-component controls:** Clinical truth: disease states, transitions, physiology, treatment response, arrest, contraindications. Deterministic and dataset-driven.

**LLM sub-component controls:** Natural language only, meaning what the patient says. The Claude API generates patient dialogue from a structured prompt. Claude cannot determine diagnosis, state, deterioration, treatment response, recovery, arrest, or any clinical fact.

**Library:** Python `transitions` for the FSM. Anthropic Python SDK for the Claude API. Model: `claude-sonnet-4-20250514`.

**Four FSM instances run in parallel**, one per patient, one per disease. Each is an independent object with its own state, timers, variables, and conversation history.

**One-hot encoding** for FSM state representation (prevents categorical ambiguity when feeding state to Brain 1).

---

### Brain 3: Deterministic Scorer + Claude Narrative

**Controls:** Post-session evaluation. Runs once at session end, not during the session.

**Deterministic scoring component:** Calculates all metrics from the action log. No LLM is involved in scoring. This safety design decision prevents hallucinated evaluation scores.

**Six metrics calculated deterministically:**
1. Time to first key intervention, per patient (seconds from that patient's presentation; for anaphylaxis: first ANA-004). The key intervention per disease comes from that disease's `Key_Interventions` sheet (section 15).
2. Protocol adherence rate per FSM state (correct actions / required actions)
3. Triage accuracy (did the trainee visit the most critical patient first)
4. Response latency (time from state transition event to trainee action)
5. Contraindicated action count, with specific IDs
6. Repeat dose timing errors (violations of the RCUK 5-minute minimum)

**Claude narrative component:** After the deterministic scores are calculated, Claude generates a qualitative feedback paragraph. Input is the scores plus the full action log. Claude cannot change the scores; it only adds a natural language explanation.

**Pearson r validation:** Correlation between Brain 3 scores and expert-rated manual assessments will be used to validate the scoring rubric.

---

## 3. Dataset: single source of truth

**Two sources, merged into one Excel file per disease.**

Source 1: Clinical guidelines extracted into structured Excel sheets.
- Anaphylaxis: WAO Anaphylaxis Guidance 2020 (Cardona et al.), RCUK 2021, EAACI 2021
- MI: ESC STEMI/NSTE-ACS Guidelines
- Hypoglycemia: ADA Standards of Care
- Hyperglycemia/DKA: ADA Standards of Care

Source 2: MIMIC-IV-ED real patient records.
- Full version access confirmed
- Tables used: edstays, triage, vitalsign, diagnosis, medrecon, pyxis
- 1056 anaphylaxis-relevant records in `Anaphylaxis_dataset.json`
- Records are labelled as an allergy case pool, NOT all confirmed anaphylaxis

**Current dataset files:**
- `EMERGISIM_Anaphylaxis_Dataset_FINAL_v9.xlsx`: primary clinical source of truth for anaphylaxis
- `Anaphylaxis_dataset.json`: MIMIC-IV-ED records

**Excel sheets in v9 that the code reads directly (never hardcode values from these):**
- `State_Actions`: action tier per state per action ID
- `Transitions`: FSM transition rules and pacing window values
- `State_Symptoms`: allowed/forbidden/superseded symptoms per state
- `State_Communication`: speech ability per state per variant
- `Contraindicated`: C-01 to C-04 rules, applies_in_states, time penalties
- `Action_Aliases`: synonyms for each action ID, used by the voice parser
- `Hints`: graded hints per state with show_when conditions
- `Post_Stable_Brain3`: post-recovery checklist PS-01 to PS-15
- `Worm2018_Modifiers`: cofactor odds ratios for the response probability model
- `Symptom_Master`: full symptom definitions
- `Observable_Signs`: VR cues and signs the trainee can observe
- `Patient_Profile_Schema`: patient variable definitions
- `State_Variables`: runtime variable definitions
- `Global_Rules`: diagnostic criteria, hypotension definition, epi rules
- `Calculators`: dose and threshold formulas
- `Bundle_Sequence`: RCUK treatment algorithm per state
- `Vitals_Template`: vital sign ranges (filled from MIMIC-IV-ED)

**Vitals calculation rule:** Never hardcode vital sign ranges. Calculate them from the MIMIC-IV-ED JSON using the 25th to 75th percentile per FSM state. Classify patients into states using WAO clinical thresholds (SBP < 90 = cardiovascular_collapse; SpO2 < 92 or HR > 120 = airway_compromise; everything else = early_reaction). Do not fill by state (circular reasoning). Use forward/backward fill with an 8-hour cap for missing values.

**Implementation (done):** `emergisim/brain2/loaders/json_loader.py`, run through `python -m tools.build_anaphylaxis_derived`.
- Implausible values (for example SBP 0 to 20 from a failed cuff read) are blanked before filling, using `config.VITALS_PLAUSIBLE` (DERIVED).
- Aggregation is a median per (stay, state), then percentiles across stays, so long stays do not dominate.
- Cohort: confirmed anaphylaxis (ICD T78.0x or T78.2, 169 stays) where a state has at least 10 stays. Otherwise the full allergy pool (1056 stays).
- `stable` is DERIVED as the last observation of stays discharged home that classify as early_reaction. WAO defines no stable vitals.
- Output: `data/derived/anaphylaxis_vitals.json`. Copy p25/p75 into Vitals_Template min/max.

**Results and limitations (state these in the report):**

| State | Cohort | Stays | HR p50 | SBP p50 | SpO2 p50 |
|---|---|---|---|---|---|
| early_reaction | confirmed | 167 | 89 | 125 | 99 |
| airway_compromise | confirmed | 32 | 128 | 131 | 98 |
| cardiovascular_collapse | allergy pool | 15 | 88 | 86 | 99 |
| stable (derived) | confirmed | 144 | 80.5 | 116 | 99 |

- Fewer than 10 confirmed stays ever reach collapse, so the collapse row uses the wider pool. It shows mild hypotension (SBP 84.5 to 88), not profound shock. Patients mostly arrive treated, and severe cases go straight to resuscitation. The FSM's deterioration toward arrest (SBP < 50) is therefore a design extrapolation, not data.
- In the data, the airway_compromise proxy is driven by HR > 120 (median SpO2 98). It captures tachycardia more than hypoxia.
- MIMIC-IV-ED has no age or weight. These are design inputs in the profiles. They could come from MIMIC-IV `hosp.patients.anchor_age` joined on subject_id.
- Asthma is not readable from ICD (the extract keeps only T78 codes). An inhaled asthma/COPD home medication is used as a DERIVED proxy.

**Privacy (the repo is public):** the raw JSON is git-ignored. Committed derivatives hold only aggregates, with any cell under 10 stays suppressed and no identifiers or timestamps. A test enforces this (`tests/test_data_layer.py`).

---

## 4. Anaphylaxis FSM: complete specification

This is the most developed disease. All code decisions documented here also apply to the MI, Hypoglycemia, and Hyperglycemia FSMs, adapted to their specific clinical rules.

### 4.1 FSM states

| State | WAO Grade | Entry Criteria | Speech Ability |
|---|---|---|---|
| early_reaction | Grade 3 | Skin/mucosal signs AND qualifier (mild wheeze or severe GI) | Full sentences |
| airway_compromise | Grade 4 | Stridor, voice change, severe bronchospasm | Short phrases, hoarse |
| cardiovascular_collapse | Grade 5 | SBP below threshold OR collapse OR respiratory failure | Whisper/single words (conscious variant) or none (unconscious variant) |
| stable | Design state | All stable criteria simultaneously met | Full sentences |
| scenario_end | Design state | Timer expired with no adequate treatment | None |

cardiovascular_collapse has two variants, defined in the State_Communication sheet:
- `conscious_hypotensive`: patient can whisper or say single words
- `unconscious`: patient produces no speech

The variant is set in the patient profile and does not change during the session.

### 4.2 Treatment pipeline (P01: most important architectural rule)

An action does NOT directly cause a state transition. The full pipeline must always run:

```
TRAINEE ACTION
      |
VALIDATE (tier check from State_Actions sheet)
      |
APPLY EFFECT (update physiology based on action)
      |
RESPONSE PROBABILITY CHECK (Worm 2018 model, only for ANA-004)
      |
UPDATE PHYSIOLOGY (gradual, not instant; recovery_rate = 0.4 per tick)
      |
REASSESSMENT (multi-signal evaluator: SBP, HR, RR, SpO2, consciousness, trend)
      |
FSM EVALUATOR (checks if transition criteria are met)
      |
STATE UPDATE (atomic; no half-states)
      |
MANIFESTATION MAPPER (selects allowed symptoms for this state)
      |
CLAUDE API (generates patient dialogue from structured prompt)
      |
OUTPUT VALIDATOR (three deterministic checks)
      |
PATIENT RESPONSE TO TRAINEE
```

### 4.3 Transition rules (from Transitions sheet, F-26 resolved)

**Early Reaction to Stable:**
Required: ANA-004 (IM epinephrine), a single action per the RCUK Bundle_Sequence.
Plus: the adequate response probability check passes.

**Airway Compromise to Stable:**
Required: ANA-004 (IM epinephrine, or a repeat after 5 min).
RCUK F-26: oxygen (ANA-007) is supportive, NOT required for transition.

**Cardiovascular Collapse to Stable:**
Required: two IM epinephrine doses (ANA-004 x2), THEN IV infusion (ANA-014).
CPR (ANA-013) is additionally required ONLY if arrested = True.

**Timer expiry transitions (no correct action taken):**
- early_reaction → airway_compromise
- airway_compromise → cardiovascular_collapse
- cardiovascular_collapse → scenario_end (design choice, not a WAO claim)

### 4.4 Action tiers (from State_Actions sheet)

Every action has a tier per state. Tiers determine scoring and FSM effect:
- `correct`: contributes to FSM transition, full Brain 3 credit (1.0)
- `supportive`: good practice, partial credit (0.4), no transition
- `conditional`: correct only under specific conditions, partial credit (0.6)
- `neutral`: no indication in this state, no credit (0.0)
- `contraindicated`: actively harmful, negative credit (-0.5), timer penalty applied

### 4.5 Contraindicated actions (from Contraindicated sheet)

**C-01: IV epinephrine bolus**
Applies in: all three active states.
Effect: a timer penalty is subtracted from the pacing clock.
Note: IV epinephrine INFUSION (ANA-014) is different and is correct in the refractory pathway.

**C-02: Rapid IV antihistamine**
Applies in: airway_compromise and cardiovascular_collapse only. NOT early_reaction.

**C-03: Adjunct instead of epinephrine**
Applies when epinephrine has NOT yet been given AND the trainee gives ANA-011/012/016/017.
If epinephrine was already given, these adjuncts are supportive or neutral, not contraindicated.

**C-04: Standing patient up suddenly**
Applies in: all states.
EXCEPT: in airway_compromise, when the patient has respiratory_distress = True, sitting up is acceptable (RCUK p.26, F-09).
In cardiovascular_collapse, C-04 applies with NO exemption (F-09 update).

**Time penalties:** read from `Contraindicated.time_penalty_seconds`. That column is blank because F-24 is still open: no guideline gives a numeric value. Until an expert or an authentic source supplies one, the loader falls back to `config.CONTRAINDICATION_PENALTY_FALLBACK_S` (C-01 = 20s, C-02 = 15s, C-03 = 25s, C-04 = 20s) and tags each value `PLACEHOLDER: F-24`. Once the sheet is filled, the sheet wins automatically. The pacing windows (F-23) work the same way.

### 4.6 Response probability model (D1: Option C, Worm 2018)

Applies only to ANA-004 (IM epinephrine), the only action that triggers a response check.

```python
p = RESPONSE_BASE_PROBABILITY            # 0.82, PLACEHOLDER (WAO G-10 "most respond to 1-2 doses")
for OR in applicable Worm2018_Modifiers rows (95% CI excludes 1):
    p = p / (1 + (OR - 1) * RESPONSE_OR_DAMPING)   # k = 0.3, PLACEHOLDER
if dose_number >= 2:
    p *= RESPONSE_SECOND_DOSE_FACTOR      # 0.7, PLACEHOLDER
p = clamp(p, 0.05, 0.99)                  # result: random.random() < p
```

**Resolved (P1):** odds ratios are read from the `Worm2018_Modifiers` sheet (`emergisim/brain2/anaphylaxis/response_model.py`), never from code. The earlier inline table in this spec (beta-blocker 2.4, NSAID 1.8, ...) did not match Worm 2018 and has been removed: the paper reports beta-blocker 1.857 (Ring & Messmer model), and NSAIDs, alcohol and cardiovascular disease are not in Table 1.

- Model: `config.WORM_MODEL = "RingMessmer"` (a severity grading). Rows marked "Not used" in that model have no effect, rather than borrowing the other model's OR.
- Only rows whose 95% CI excludes 1 are applied. That excludes food and insect elicitors in Ring & Messmer.
- Age uses the per-year OR as `OR ** (age - 30)`, with reference age 30 as a PLACEHOLDER.
- **Modelling assumption to state in the report:** Worm 2018 gives odds of a *severe reaction*, not of *non-response to epinephrine*. Mapping one onto the other through k is our design choice, for expert validation.

Resulting first-dose probabilities: ANA-P1 0.85, P2 0.87, P3 0.71, P4 0.77, P5 0.26, P6 0.36, P7 0.27.

If the response probability check passes, physiology shifts toward stable ranges (gradually, recovery_rate = 0.4). Reassessment then checks the stable criteria.

If it fails, the patient stays in the current state and the timer continues. This alone causes no deterioration.

### 4.7 Refractory pathway (Option A)

Triggered when `epi_dose_count >= 2` AND the patient is still in `cardiovascular_collapse` at the next reassessment.

Effect: `refractory_triggered = True`. ANA-014 (IV epinephrine infusion) changes tier from conditional to correct/required in this state.

Source: RCUK pp.34, 37, F-26 resolved.

### 4.8 Arrest detector (P09: runs independently)

Runs at every reassessment regardless of the current FSM state.
Arrest can be triggered from ANY active state (early_reaction, airway_compromise, or cardiovascular_collapse).
Sets `arrested = True` when SBP < 50 mmHg (design threshold; PLACEHOLDER, expert to validate).

When arrested = True:
- ANA-013 (CPR) becomes conditionally correct
- IV/IO epinephrine replaces IM epinephrine
- IM epinephrine is no longer the correct route

### 4.9 Stable state criteria (P04: all must be true at once)

```
airway adequately resolved
AND breathing adequately improved
AND circulation adequate (SBP above hypotension_threshold(), HR < 120)
AND consciousness appropriate
AND life-threatening features resolved
AND SpO2 >= 94%
AND epinephrine_given = True
AND arrested = False
AND improvement maintained on reassessment
```

Mild residual symptoms are allowed. Not instant: vitals must have trended toward target.

### 4.10 Physiology update (Q3: gradual but fast)

After an adequate treatment response:

```python
recovery_rate = 0.4  # PLACEHOLDER: expert to validate
new_vital = current + (target - current) * recovery_rate
# Applied each reassessment tick
```

Target vitals come from the MIMIC-IV-ED early_reaction ranges (median values).

After the pacing window expires with no adequate treatment:

```python
deterioration_rate = 0.6
# Physiology shifts toward the next (worse) state's median values
```

### 4.11 Pacing clock (P02: time drives reassessment, not clinical deterioration)

Base pacing windows per state (PLACEHOLDER; F-23 still open):
- early_reaction: 60 seconds
- airway_compromise: 45 seconds
- cardiovascular_collapse: 30 seconds

Brain 1 multiplier applied: `duration = int(base / brain1_multiplier)`

When the pacing window expires, the physiology update runs (toward the worse state). The multi-signal evaluator checks whether the deterioration criteria are met. If yes, the FSM transitions; if no, the pacing clock restarts.

A contraindicated action's time penalty subtracts from the remaining pacing time without changing state.

### 4.12 Symptom boundary rules (from State_Symptoms sheet)

Each symptom has a status per state: `allowed`, `forbidden`, or `superseded`.

`superseded` means the symptom existed in an earlier state but is replaced by a more severe version in this one. It must NOT appear in the LLM prompt even if it was allowed in an earlier state. Example: SYM-011 (mild wheeze) is superseded in airway_compromise, where severe bronchospasm takes its place.

`forbidden` means clinically inconsistent with this state. It never appears in the LLM prompt.

Symptoms are also filtered by patient sex (SYM-016 applies to females only) and by paediatric variant.

---

## 5. Voice input pipeline

### 5.1 Full pipeline

```
Audio from trainee microphone
      |
Whisper API transcription
(confidence threshold = 0.6, from project overview)
      |
If confidence < 0.6: ask trainee to repeat, log low confidence event
      |
VoiceInputParser.parse(text, confidence, current_patient_id)
      |
Intent classification (action / conversation / system)
      |
If action: entity extraction (drug name, route, dose, site, patient target)
      |
Alias matching against Action_Aliases sheet (longest match wins)
      |
Route conflict check (IV epinephrine = C-01 regardless of alias match)
      |
Ambiguity check (multiple matches → ask for confirmation)
      |
ParsedInput returned to session loop
      |
If action: FSM.process_action(action_id)
If conversation: FSM.generate_patient_response(text)
If system: show status/hints/summary
```

### 5.2 Intent classification

Three intents:
- `action`: any clinical procedure or drug administration detected (keyword list from the Action_Aliases sheet)
- `conversation`: trainee speaking to the patient (the default when no action keywords are detected)
- `system`: "status", "hints", "summary", "score", "quit"

Conversation and action are separate. A trainee saying "how are you feeling" should generate patient dialogue via Claude, not log an action.

### 5.3 Multi-patient voice commands

The trainee specifies a patient with a natural prefix:
- "patient one", "bed one", "first patient" → patient_1
- "patient two", "bed two" → patient_2
- etc.

If no patient is specified, the action applies to the currently focused patient. Focus changes with a "go to bed N" command.

### 5.4 Alias matching

Primary source: the `Action_Aliases` sheet, `pdf_terms_and_synonyms` column.
Secondary source: the `natural_speech_variants` column (to be added by Javeria; currently pending).

Matching: lowercase, split on semicolons and commas, longest match wins.

When ambiguous (multiple actions match), return all options and ask the trainee to confirm. Do not execute until confirmed.

### 5.5 Route and dose extraction

Route synonyms: IM (intramuscular, thigh, anterolateral), IV (intravenous, vein, drip, line), INH (inhaled, nebulised, mask), ORAL (oral, by mouth, tablet).

If the route is IV AND the action mentions epinephrine/adrenaline, trigger C-01 directly without alias matching.

Dose is extracted by regex: patterns like "500 mcg", "0.5 mg", "1:1000".

If the route or dose is wrong, flag it to Brain 3 but do not block the action (unless it maps to a contraindication).

---

## 6. Output validator: three deterministic checks

Runs on every Claude-generated response before it reaches the trainee.

### Check 1: Symptom boundary

Extract all medical symptom terms from the response and check them against the allowed list for the current state (State_Symptoms sheet). Any forbidden or superseded symptom causes a failure.

### Check 2: Information boundary

Regex/keyword check. The response must NOT contain:
- Vital sign numbers (any number + mmHg/bpm/%/SpO2)
- Diagnosis labels (anaphylaxis, allergic reaction, epinephrine needed)
- Treatment recommendations (you should give me, I need an injection)
- Clinical reasoning (this is because, which means, therefore, clinically)
- FSM state labels (early reaction, airway compromise, cardiovascular collapse)
- WAO grade references

### Check 3: Speech ability

Check sentence length against the speech pattern for the current state:
- full sentences: no limit
- short phrases: max 15 words per sentence
- whisper or single words: max 5 words
- no speech: response must be an empty string

### Failure handling

If any check fails:
1. Rebuild the system prompt with an explicit correction instruction naming the violation
2. Call Claude once more
3. If the second attempt also fails, use a pre-written, expert-validated fallback response for this state

Fallbacks are static strings stored in code, reviewed by a clinical expert, never LLM-generated.

---

## 7. Claude LLM integration (Brain 2 dialogue)

### System prompt structure

Built fresh every turn from the current FSM state only. Claude never sees information from other states.

The system prompt contains:
- Patient identity (age, sex, trigger type, cofactors)
- Current state (described as clinical experience, not an FSM label)
- Allowed symptoms the patient can report (from State_Symptoms, filtered by sex and paediatric flag)
- An explicit list of symptoms never to mention (forbidden + superseded)
- Speech ability constraint
- Observable signs (what the trainee sees, NOT what the patient says)
- What has happened so far (epi given, trigger removed, O2 applied)
- Strict rules: no vital numbers, no diagnosis terms, no treatment recommendations, no clinical reasoning

Hidden from Claude at all times: diagnosis label, SBP/HR/RR/SpO2 numbers, WAO grade, FSM state name, clinical reasoning chain.

### Conversation history

The last 5 pairs of turns (10 messages) are passed as conversation history on each call. This keeps the patient's character consistent without excessive token cost.

### Model

`claude-sonnet-4-20250514`, `max_tokens = 200` (patient responses should be short).

---

## 8. Patient profiles

Up to 6 or 7 profiles with easy, medium and hard parameters.

**Anaphylaxis profiles (resolved, P6):** 7 synthetic archetypes in `data/derived/anaphylaxis_profiles.json`, built by `tools/build_anaphylaxis_derived.py`. Presenting vitals are the MIMIC-IV-ED p50 for the start state. Baseline SBP is the derived stable p50. Each profile cites the pool prevalence of the features it uses. Identities are invented; no profile copies a real patient.

| ID | Difficulty | Start state | Sex / age (design) | Trigger | Key features | P(respond), dose 1 |
|---|---|---|---|---|---|---|
| ANA-P1 | easy | early_reaction | F / 24 | food (peanut) | none | 0.85 |
| ANA-P2 | easy | early_reaction | F / 19 | food (tree nut) | prior anaphylaxis, has auto-injector | 0.87 |
| ANA-P3 | medium | early_reaction | F / 33 | food (shellfish) | asthma (14.3% of pool via proxy) | 0.71 |
| ANA-P4 | medium | airway_compromise | F / 41 | food (sesame) | ambulance arrival (28.3%) | 0.77 |
| ANA-P5 | hard | airway_compromise | M / 52 | drug (antibiotic) | male, asthma, psychological burden | 0.26 |
| ANA-P6 | hard | cardiovascular_collapse, conscious | F / 67 | drug (NSAID) | beta-blocker (8.4%), ACE-I (11.6%) | 0.36 |
| ANA-P7 | hard | cardiovascular_collapse, unconscious | M / 74 | drug (IV contrast) | beta-blocker, male, elderly | 0.27 |

2 of 7 profiles are male, close to the 33% male share in the data. Age and weight are PLACEHOLDER (not in MIMIC-IV-ED). Difficulty comes from three levers: start state, Worm 2018 modifiers (response probability) and collapse variant.

Brain 1 assigns harder profiles as trainee performance improves across a session.

---

## 9. Stack and infrastructure

**Backend:** FastAPI with WebSocket. Single entry point for all real-time communication. No AI logic in the backend: pure routing and orchestration.

**FSM library:** Python `transitions`. Four FSM instances run concurrently as **asyncio actors** on FastAPI's single event loop (`emergisim/core/patient_actor.py`). There are no threads.

**Concurrency model (resolved, P3).** Threads plus `threading.Lock()` alongside FastAPI's asyncio loop risked deadlocks and unsafe cross-thread calls into the loop. Replaced by:
- **One actor per patient.** Each patient has an `asyncio.Queue` inbox and a single consumer task. Trainee actions, timer expiries, Brain 1 multiplier changes and penalties are all events in that queue. They are applied one at a time in FIFO order, so transitions are atomic without any lock, and the four patients never block each other.
- **The clock only posts events.** `PacingClock` uses `loop.call_later` and never mutates state. Each pacing window has an **epoch**. A new state starts a new epoch, so an expiry queued just behind a correct action is recognised as stale and discarded. This closes the "timer fires right after the epinephrine" race.
- **Slow I/O stays outside the handler.** Claude and Whisper calls use the async SDK clients in a side task, built from an immutable snapshot. If the epoch changed while Claude was generating, the reply is dropped and regenerated, so dialogue can never describe a state the patient has already left.
- **CPU-bound work** (PPO policy inference) runs through `asyncio.to_thread`.
- Penalties shorten the current window (same epoch). A Brain 1 multiplier change rescales the remaining time and applies to later windows.

Covered by `tests/test_patient_actor.py`: ordered deterioration, cancel-on-correct-action, stale-expiry discard, penalty, multiplier, four independent patients and stale-dialogue detection.

**RL library:** Stable-Baselines3 with Gymnasium. The `SimulatedEREnvironment` class wraps the four FSM instances. PPO algorithm. A one-hot encoded FSM state vector is fed to the PPO policy.

**Voice:** OpenAI Whisper API. Confidence threshold 0.6 from the project specification. `verbose_json` response format for segment-level confidence.

**LLM:** Anthropic Python SDK. Claude API for both Brain 2 dialogue and Brain 3 narrative.

**Data:** pandas + numpy for Excel reading and MIMIC-IV-ED calculations. openpyxl for Excel parsing.

**Python version:** 3.10+ (structural pattern matching in some places, dataclasses throughout).

---

## 10. Constants and open flags

Every value that is not from a guideline must be labelled with one of three label types:

- `# SOURCE: <guideline> <page>`: clinically sourced value; cite it
- `# DERIVED: <reasoning>`: calculated from data; explain how
- `# PLACEHOLDER: expert validation required (F-<flag>)`: team/expert decision pending

Open flags still needing values:
- **F-23:** Base pacing window values per state per trigger type. Team to decide the compression factor.
- **F-24:** Contraindicated time penalties C-01 to C-04. Expert to validate.
- **F-17:** Repeat dose timing scoring. Expert to confirm the penalty for early/late repeats.

Brain 3 score weights (all PLACEHOLDER; expert to validate):

```python
BRAIN3_WEIGHTS = {
    "correct":         1.0,
    "supportive":      0.4,
    "conditional":     0.6,
    "neutral":         0.0,
    "contraindicated": -0.5,
}
```

- Response probability base = 0.82 (PLACEHOLDER; expert to validate)
- Recovery rate = 0.4 per tick (PLACEHOLDER; expert to validate)
- Deterioration rate = 0.6 per expired window (PLACEHOLDER; expert to validate)
- Arrest detection SBP threshold = 50 mmHg (PLACEHOLDER; expert to validate)

---

## 11. What is locked and what is pending

**Locked (do not change without team review):**
- All P01 to P22 architectural decisions
- All D1 to D5 session decisions
- Three-check validator design
- Refractory pathway Option A trigger condition
- Arrest as an independent flag, separate from FSM state
- Treatment pipeline order (action → physiology → reassessment → transition)
- Dataset as the single source of truth for all clinical rules
- Brain responsibility separation (PPO = difficulty, FSM = clinical truth, LLM = language)
- Voice intent classification approach
- Post-stable Brain 3 checklist

**Pending (code with clearly marked placeholders):**
- Timer values (F-23)
- Contraindicated penalties (F-24)
- Score weights (team decision)
- Response probability base rate (expert decision)
- Recovery rate (expert decision)
- Arrest threshold (expert decision)
- Natural speech variants column in Action_Aliases (Javeria to add)
- Full resuscitation pathway implementation (in/out of scope TBD)
- Biphasic reaction handling (in/out of scope TBD)

**Not in scope (do not implement):**
- Multiplayer (explicitly dropped)
- Real-world discharge observation workflow
- Comorbid multi-disease interactions (intentional scope boundary)
- LLM as validator (a second Claude call checking the first is circular, not deterministic)
- PPO controlling any clinical variable (disease truth, treatment response, arrest)
- LLM generating any clinical decision (transition, response, deterioration)
- WAO grade visible to the trainee (hidden variable only)
- Trainee required to say "anaphylaxis" aloud (recognition is inferred from actions)

---

## 12. File and folder structure (recommended)

```
emergisim/
  brain2/
    anaphylaxis/
      fsm.py              # AnaphylaxisFSM class
      response_model.py   # Worm 2018 probability model
      physiology.py       # PhysiologyState and update functions
      validator.py        # Three-check output validator
      prompt_builder.py   # Claude system prompt construction
      profile.py          # PatientProfile and profile library
    mi/
      fsm.py              # MI FSM (same architecture, different clinical rules)
    hypoglycemia/
      fsm.py
    hyperglycemia/
      fsm.py
    loaders/
      excel_loader.py     # All sheet-loading functions
      json_loader.py      # MIMIC-IV-ED JSON loading and vitals calculation
    voice/
      parser.py           # VoiceInputParser class
      intent.py           # Intent classification
      aliases.py          # Alias index building
  brain1/
    environment.py        # SimulatedEREnvironment (Gymnasium)
    adapter.py            # Brain1 placeholder + PPO interface
    train.py              # PPO training script
  brain3/
    scorer.py             # Deterministic metric calculation
    narrative.py          # Claude narrative generation
    summary.py            # Full session report builder
  core/
    patient_actor.py      # PatientActor + PacingClock (asyncio, section 9)
  backend/
    main.py               # FastAPI app, WebSocket handler
    session.py            # Session orchestration
    monitor.py            # Performance monitor
  config.py               # All constants with PLACEHOLDER comments
data/
  EMERGISIM_Anaphylaxis_Dataset_FINAL_v9.xlsx
  Anaphylaxis_dataset.json     # MIMIC-derived: local only, never committed
  derived/                     # aggregate-only outputs, committed
tools/
  build_anaphylaxis_derived.py # MIMIC -> vitals + profiles
tests/
requirements.txt
```

---

## 13. Coding rules for this project

1. Never hardcode any clinical value. Every threshold, range, timer, and rule must load from the Excel file or JSON at runtime.
2. Every PLACEHOLDER constant must have a comment: `# PLACEHOLDER: [what it represents]; expert validation required (F-XX open flag)`.
3. Every clinical value loaded from the dataset must have a comment: `# SOURCE: [sheet name] [column]; [guideline citation]`.
4. All FSM state transitions are atomic. Either they complete fully or they do not happen. No half-states are possible.
5. Concurrency: every patient runs as a `PatientActor` (section 9). State is mutated only inside that actor's event handler. Timers post events and never mutate. No threads, and no state shared between patients.
6. The output validator runs before every Claude response reaches the trainee. No exceptions.
7. Brain 1 can only call `fsm.set_brain1_multiplier(value)`. It cannot call any other FSM method or read raw physiological values. It receives only the processed state vector from the Performance Monitor.
8. Claude receives only the output of `build_system_prompt()`. It never receives raw simulator state, vital sign numbers, FSM state labels, WAO grades, or diagnosis names.
9. Action aliases are loaded from the Excel file. Do not hardcode action keywords in the parser.
10. All score weights live in `config.py` with PLACEHOLDER comments, not scattered through the codebase.
11. MIMIC-IV-ED data (including `Anaphylaxis_dataset.json`) is covered by the PhysioNet credentialed data use agreement. Keep it local; it is git-ignored and must never be committed. Only aggregated statistics derived from it may be committed.

---

## 14. Review notes: status

| # | Issue | Status |
|---|---|---|
| 1 | Hardcoded vs dataset values | **Resolved.** Loaders read the Worm2018_Modifiers, Contraindicated and Transitions sheets. Blank cells fall back to tagged `config.py` placeholders. F-23 (timers) and F-24 (penalties) still need expert or authentic values; no guideline gives them. |
| 2 | Anaphylaxis-only reward and metric | **Resolved in design.** Generic "key intervention" reward and metric (sections 2, 15). Other diseases need their `Key_Interventions` sheets. |
| 3 | Threads plus asyncio | **Resolved.** Per-patient asyncio actor with epoch-guarded timers (section 9). |
| 4 | Older model ID | **Open.** Kept in `config.LLM_MODEL`; re-evaluate before Brain 2 integration. |
| 5 | Deterioration rate unlabelled | **Resolved.** Added to section 10 and `config.py`. |
| 6 | Patient profiles undefined | **Resolved for anaphylaxis** (section 8). |
| 7 | Worm 2018 odds ratios in this spec did not match the paper | **Resolved.** Inline table removed; values come from the sheet (4.6). |
| 8 | MIMIC collapse data is thin and mild | **Open (limitation).** State it in the report (section 3). |
| 9 | MIMIC-IV-ED has no lab values | **Open (dataset blocker for 3 diseases).** See section 15. |

---

## 15. Disease module contract (P2)

Every disease plugs into the same engine. Nothing in Brain 1, Brain 3, the actor or the validator may mention a specific disease. Disease specifics come only from that disease's workbook, using the anaphylaxis workbook's sheet layout, plus one new sheet.

### 15.1 Required workbook sheets (per disease)

Same names and columns as the anaphylaxis v9 workbook: `States`, `State_Actions`, `Transitions`, `State_Symptoms`, `State_Communication`, `Contraindicated`, `Action_Aliases`, `Hints`, `Observable_Signs`, `Patient_Profile_Schema`, `State_Variables`, `Global_Rules`, `Bundle_Sequence`, `Vitals_Template`, `Post_Stable_Brain3`.

Action IDs are prefixed per disease: `ANA-`, `MI-`, `HYPO-`, `DKA-`. Contraindication IDs: `C-ANA-01`, `C-MI-01`, and so on (the existing C-01 to C-04 map to C-ANA-01 to C-ANA-04 when the second disease lands).

**New sheet `Key_Interventions`** (drives the Brain 1 reward and Brain 3 metric 1):

| column | meaning |
|---|---|
| key_id | e.g. `KI-ANA-01` |
| action_id | the action that counts |
| must_be_given_before_leaving | state; giving it while still in this state earns the reward |
| gating_condition | optional precondition (e.g. potassium >= 3.5 for insulin) |
| source | guideline + page |

Anaphylaxis: `KI-ANA-01 | ANA-004 | early_reaction | none | RCUK 2021 Fig. 6 p.25; WAO 2020 p.15`.

### 15.2 Candidate key interventions for the other diseases

**Candidates only.** Javeria/the team must verify each against the guideline PDF and record the exact page before it enters a workbook.

| Disease | Candidate key intervention | Guideline to verify against |
|---|---|---|
| MI | 12-lead ECG within 10 min of first contact; then aspirin loading dose | ESC 2023 ACS Guidelines |
| Hypoglycemia | Fast-acting glucose 15 to 20 g if conscious and able to swallow; glucagon or IV dextrose if not | ADA Standards of Care (section 6) |
| Hyperglycemia/DKA | IV fluids first; insulin only once potassium >= 3.5 mmol/L (insulin with low K+ = contraindicated) | ADA/EASD/JBDS/AACE/DTS 2024 Hyperglycemic Crises consensus |

DKA shows why `gating_condition` exists: the same action (insulin) is correct or contraindicated depending on a lab value.

### 15.3 Code interface

Each disease package (`emergisim/brain2/<disease>/`) provides a model satisfying `PatientModel` in `emergisim/core/patient_actor.py` (`handle_action`, `handle_timer_expiry`, `pacing_window_s`, `penalty_s`, `snapshot`), plus:
- `key_interventions()`: loaded from the `Key_Interventions` sheet
- `response_model(action_id, profile, dose_number)`: disease-specific. Anaphylaxis uses Worm 2018. Others may be deterministic until a sourced model exists.
- `classify_state(vitals, labs)`: the rule used to derive vitals from MIMIC

### 15.4 Dataset blocker: labs

MIMIC-IV-ED has vitals, triage, diagnoses and medications, but **no laboratory values**. Hypoglycemia and DKA states are defined by glucose, ketones, pH and bicarbonate; MI by troponin and ECG. The anaphylaxis approach (state from vitals) therefore cannot be copied directly. Options for Javeria:
1. Join MIMIC-IV `hosp.labevents` on `hadm_id`. This works only for admitted stays, which biases toward sicker patients.
2. Use MIMIC-IV-ECG (separate PhysioNet module) for MI.
3. Take state thresholds from the guidelines (ADA glucose levels; DKA severity table) and use MIMIC-IV-ED only for the accompanying vitals per ICD code.

Option 3 is the most realistic for the timeline; 1 and 2 are stronger if time allows.
